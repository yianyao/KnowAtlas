"""万兴脑图适配器（source_type=emmx，完整方案 §3.2 / §12 步骤 15，M1；
§7.8 全删重灌形态判定，第六十五批）。

.emmx = ZIP 包。真实格式（MindMaster 9.x，2026-10-19 以 9 个真实样本解剖定稿）：
- 主题树在 page/page.xml（document.xml 的 Properties/Pages 指明页名，可能多页）；
- 节点 = <Shape Type="MainIdea|MainTopic|SubTopic|SummaryTopic">，标题文本在
  Text/TextBlock/Text 深层的 <tp> 元素里（多段合并）；
- 层级不是 XML 嵌套，而是 <LevelData><Super V="父 Shape ID"/> 引用；父指向
  Boundary/Summary 等装饰容器时断链，按顶层分支处理；
- Boundary/Summary/Callout/MMConnector 等非主题 Shape 不建条目；
- page.xml 缺失（如仅 mmpage/page.bin 旧版二进制）/ 坏 ZIP / 无主题节点 →
  降级标题级单条目，meta.degraded=true。

形态判定（方案 §7.8 用户二轮裁决：方案型脑图此前被切散，推倒重来）：
- 结构化解析成功且 [llm] 可用时，每 .emmx 文件先 LLM 判定 integral/split
  （判定依据=脑图主题+一级分支大纲，理由落 meta.judge_reason 可抽检）；
- integral（方案型）→ 整图一条目：节点树确定性压缩为结构化大纲入
  inline_content（零发明，只缩进排版原文标题），mind_path 保留中心主题；
- split（讨论型）→ 节点照旧切条目，meta 附 judge 供区分；
- LLM 不可用（未启用/无 key/调用失败）→ 回落现行节点粒度（保守：宁碎勿丢），
  stats.judge.errors 计数，下次同步重判。

判定缓存：KNOWATLAS_HOME/emmx_judge_cache.json（键=文件字节 sha256）——
重复 ksync 不重判不重扣费；home 未设（如测试）不缓存。

契约：source_key = 文件相对路径 + "#页名/节点id"（split/降级）或文件相对路径
（integral，locator=emmx://<相对路径>#<map>）；native_path = 文件所在目录层级
（先验信号），脑图内部主题路径进 meta.mind_path。
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..errors import AdapterError
from ..ids import content_hash
from ..models import Entry
from .base import AdapterOutput

_MAX_NODES = 3000  # 单脑图节点上限（防失控）
_MAX_DEPTH = 30  # Super 引用上溯深度上限（防引用环死循环）
_TOPIC_TYPES = {"MainIdea", "MainTopic", "SubTopic", "SummaryTopic"}
_JUDGE_OUTLINE_DEPTH = 2  # 判定依据只看主题+一级分支（方案 §7.8 口径）
_JUDGE_OUTLINE_CHARS = 1800  # 判定输入大纲截断（判定不需要全文）
_BODY_CHARS = 20000  # integral 整图大纲入正文上限（超长截断留痕）
_OUTLINE_INDENT = "  "  # 大纲缩进单位

_JUDGE_SYSTEM_PROMPT = (
    "你是个人知识库的脑图形态判定助手。给定一张脑图的大纲（主题+分支），判定"
    "它的知识形态：\n"
    "- integral（方案型）：整图是一个不可拆的整体——方案、设计、论证、计划、"
    "流程，分支互相依赖，拆开各自不成立，应整图作为一个知识点；\n"
    "- split（讨论型）：各分支独立成立、可单独复用——讨论记录、问题集、杂项"
    "收集、多主题清单，应按节点切分入库。\n"
    "规则：\n"
    '1. 只输出 JSON 对象：{"judge":"integral"或"split","reason":"一句话判定理由"}。\n'
    "2. 只有整图明确是单一方案/整体论证时才判 integral；内容杂、多主题或拿不准"
    " → split。\n"
    "3. 不要输出 JSON 以外的任何文字。"
)


def _shape_title(shape: ElementTree.Element) -> str:
    """Shape 标题：Text/TextBlock/Text 下所有 <tp> 文本，多段合并。"""
    parts: list[str] = []
    for tp in shape.iter("tp"):
        t = "".join(tp.itertext()).strip()
        if t:
            parts.append(t)
    return " ".join(parts).strip()


def _super_id(shape: ElementTree.Element) -> str:
    """父 Shape ID（LevelData/Super V），无则空串。"""
    ld = shape.find("LevelData")
    if ld is not None:
        sup = ld.find("Super")
        if sup is not None:
            return (sup.get("V") or "").strip()
    return ""


def _outline(topics: dict[str, tuple[str, str]], order: list[str],
             page_name: str, max_depth: int, char_cap: int) -> str:
    """节点树 → 缩进大纲（确定性排版原文标题，零发明）。

    只收录标题非空的节点；父断链（Super 指向不存在/非主题 Shape）按顶层处理；
    引用环由 max_depth 兜底。char_cap 截断防 LLM 输入/正文失控。
    """
    children: dict[str, list[str]] = {}
    for sid in order:
        sup = topics[sid][1]
        children.setdefault(sup if sup in topics else "", []).append(sid)
    lines: list[str] = [f"# {page_name}"]

    def _walk(sid: str, depth: int) -> None:
        if depth > max_depth or sum(len(x) for x in lines) > char_cap:
            return
        title = topics[sid][0]
        if title:
            lines.append(f"{_OUTLINE_INDENT * (depth - 1)}- {title}")
        for child in children.get(sid, []):
            _walk(child, depth + 1)

    for root in children.get("", []):
        _walk(root, 1)
    text = "\n".join(lines)
    return text if len(text) <= char_cap else text[:char_cap] + "…[截断]"


def _judge_cache_path(config: Any) -> Path | None:
    home = getattr(config, "home", None)
    return home / "emmx_judge_cache.json" if home else None


def _load_judge_cache(config: Any) -> dict[str, Any]:
    path = _judge_cache_path(config)
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}  # 缓存坏了不当回事：重判一遍而已


def _save_judge_cache(config: Any, cache: dict[str, Any]) -> None:
    path = _judge_cache_path(config)
    if path is None:
        return
    try:
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=0),
                        encoding="utf-8")
    except OSError:
        pass  # 缓存写失败不阻断采集（下次重判）


def _judge_form(llm: Any, title: str, outline: str, fkey: str,
                cache: dict[str, Any], stats: dict[str, Any]) -> tuple[str, str] | None:
    """LLM 形态判定；返回 (integral|split, reason)，失败返回 None。

    缓存命中零费用；判定失败/输出非法一律 None（调用方回落节点粒度——保守：
    宁碎勿丢，stats.judge.errors 留痕，下次同步重判）。
    """
    hit = cache.get(fkey)
    if isinstance(hit, dict) and hit.get("judge") in ("integral", "split"):
        stats["judge"]["cache_hits"] += 1
        return str(hit["judge"]), str(hit.get("reason", ""))
    try:
        from ..semantic.llm import extract_json_object

        obj = extract_json_object(llm.chat(
            _JUDGE_SYSTEM_PROMPT, f"标题:{title[:100]}\n脑图大纲:\n{outline}"))
        judge = str(obj.get("judge", "")).strip()
        if judge not in ("integral", "split"):
            raise ValueError(f"非法判定：{judge!r}")
        reason = str(obj.get("reason", "")).strip()
    except Exception:  # LlmError/JSON 解析/非法判定——统一回落
        stats["judge"]["errors"] += 1
        return None
    stats["judge"]["calls"] += 1
    cache[fkey] = {"judge": judge, "reason": reason}
    return judge, reason


def _page_topics(data: bytes) -> tuple[dict[str, tuple[str, str]], list[str], int] | None:
    """第一遍：收集主题节点 id -> (标题, 父 id)；返回 (topics, order, 截断数)。

    坏 XML / 无主题节点 → None（调用方按降级处理）。
    """
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return None
    topics: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    truncated = 0
    for i, shape in enumerate(root.iter("Shape")):
        if (shape.get("Type") or "") not in _TOPIC_TYPES:
            continue
        if len(order) >= _MAX_NODES:
            truncated += 1
            continue
        sid = (shape.get("ID") or "").strip() or f"s{i}"
        topics[sid] = (_shape_title(shape), _super_id(shape))
        order.append(sid)
    return (topics, order, truncated) if order else None


def _emit_nodes(topics: dict[str, tuple[str, str]], order: list[str],
                page_name: str, rel: str, native_dir: str,
                entries: list[Entry], stats: dict[str, Any]) -> None:
    """第二遍：沿 Super 引用上溯构建 mind_path，产出节点条目（现行逻辑 + judge 附带）。"""
    for sid in order:
        title, sup = topics[sid]
        chain = [title] if title else []
        seen = {sid}
        cur, depth = sup, 0
        while cur and cur in topics and cur not in seen and depth < _MAX_DEPTH:
            seen.add(cur)
            if topics[cur][0]:
                chain.append(topics[cur][0])
            cur, depth = topics[cur][1], depth + 1
        chain.reverse()
        node_id = f"{page_name}/{sid}"
        meta: dict[str, Any] = {"source_type": "emmx",
                                "mind_path": "/".join(chain),
                                "depth": max(1, len(chain))}
        if stats["judge"]["form"] in ("integral", "split"):
            meta["judge"] = stats["judge"]["form"]
            if stats["judge"]["reason"]:
                meta["judge_reason"] = stats["judge"]["reason"]
        entries.append(Entry.build(
            source_type="emmx",
            source_key=f"{rel}#{node_id}",
            title=title,
            locator=f"emmx://{rel}#{node_id}",
            locator_canonical=None,
            native_path=native_dir,
            meta=meta,
            created_at=None,
        ))
        stats["nodes"] += 1


def _page_xml_names(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """发现页 XML：优先 document.xml 的 Pages 属性，失败则按文件名扫描兜底。"""
    names = set(zf.namelist())
    pages: list[tuple[str, str]] = []
    try:
        doc = ElementTree.fromstring(zf.read("document.xml"))
        v = (doc.findtext("Properties/Pages") or "").strip()
    except (KeyError, ElementTree.ParseError):
        v = ""
    for p in [s.strip() for s in v.split(";") if s.strip()]:
        cand = f"{p}/page.xml"
        if cand in names:
            pages.append((p, cand))
    if not pages:
        pages = [(n.rsplit("/", 1)[0], n) for n in sorted(names)
                 if n.lower().endswith("page.xml")]
    return pages


def _parse_emmx(path: Path, rel: str, native_dir: str,
                entries: list[Entry], stats: dict[str, Any], llm: Any,
                cache: dict[str, Any]) -> bool:
    """解析单个 .emmx；返回 True=结构化解析成功，False=降级标题级。

    native_dir = 根名/文件所在子目录层级（先验信号，与 folder 适配器同构）。
    llm 非 None 时先做形态判定（方案 §7.8）：integral → 整图一条目（大纲入
    正文）；split → 节点条目照旧；llm 为 None → 节点条目照旧（无 judge 键）。
    """
    try:
        with zipfile.ZipFile(path) as zf:
            page_list = _page_xml_names(zf)
            if not page_list:
                return False
            pages: list[tuple[str, dict[str, tuple[str, str]], list[str]]] = []
            for page_name, xml_path in page_list:
                try:
                    data = zf.read(xml_path)
                except KeyError:
                    continue
                parsed = _page_topics(data)
                if parsed is not None:
                    stats["truncated"] += parsed[2]
                    pages.append((page_name, parsed[0], parsed[1]))
            if not pages:
                return False
            node_count = sum(len(order) for _, _, order in pages)
            if llm is None:  # LLM 未启用：现行节点粒度，无 judge 键
                for page_name, topics, order in pages:
                    _emit_nodes(topics, order, page_name, rel, native_dir,
                                entries, stats)
                return True
            # 形态判定：判定依据 = 中心主题 + 一级分支大纲（方案 §7.8 口径）
            topics0 = pages[0][1]
            title0 = path.stem
            for sid in _roots(topics0, pages[0][2]):
                if topics0[sid][0]:
                    title0 = topics0[sid][0]
                    break
            outline_judge = "\n".join(
                _outline(topics, order, name, _JUDGE_OUTLINE_DEPTH,
                         _JUDGE_OUTLINE_CHARS)
                for name, topics, order in pages)
            fkey = hashlib.sha256(path.read_bytes()).hexdigest()
            judged = _judge_form(llm, title0, outline_judge, fkey, cache, stats)
            if judged is None:
                # 判定失败回落节点粒度（保守宁碎勿丢），不计 split——下次重判
                for page_name, topics, order in pages:
                    _emit_nodes(topics, order, page_name, rel, native_dir,
                                entries, stats)
                return True
            form, reason = judged
            stats["judge"]["form"] = form
            stats["judge"]["reason"] = reason
            stats["judge"][form] += 1
            if form == "split":  # 讨论型：节点照旧切条目，meta 附 judge
                for page_name, topics, order in pages:
                    _emit_nodes(topics, order, page_name, rel, native_dir,
                                entries, stats)
                return True
            # integral（方案型）：整图一条目，节点树确定性压缩为大纲入正文
            body = "\n".join(
                _outline(topics, order, name, _MAX_DEPTH, _BODY_CHARS)
                for name, topics, order in pages)
            meta: dict[str, Any] = {"source_type": "emmx", "mind_path": title0,
                                    "depth": 1, "nodes": node_count,
                                    "pages": len(pages), "judge": form}
            if reason:
                meta["judge_reason"] = reason
            # 大纲超 4096 契约上限 → inline 留截断摘要 + content_hash 指向
            # content_store 全文（与 fetch 补抓同构；全文由 sync 落库）
            inline = body
            fhash = None
            if len(body) > 4096:
                inline = body[:4000] + "…[截断，全文在 content_store]"
                fhash = content_hash(body)
                meta["outline_truncated"] = True
            entry = Entry.build(
                source_type="emmx",
                source_key=rel,  # 整图文件级单条目
                title=title0,
                locator=f"emmx://{rel}#map",
                locator_canonical=None,
                native_path=native_dir,
                inline_content=inline,
                content_hash=fhash,
                meta=meta,
                created_at=datetime.fromtimestamp(path.stat().st_mtime)
                .astimezone().isoformat(timespec="seconds"),
            )
            if fhash is not None:
                stats["_full_bodies"][entry.id] = body
            entries.append(entry)
            stats["nodes"] += 1
            return True
    except (zipfile.BadZipFile, OSError):
        return False


def _roots(topics: dict[str, tuple[str, str]], order: list[str]) -> list[str]:
    """顶层节点（Super 不在主题集内 = 断链/无父，与 _outline 同口径）。"""
    return [sid for sid in order if topics[sid][1] not in topics]


def collect_emmx(config: Any) -> AdapterOutput:
    """按 [sources.emmx].roots 遍历 .emmx 文件，先形态判定再产出条目（§7.8）。"""
    roots = [str(r) for r in (config.get("sources.emmx.roots") or []) if str(r).strip()]
    if not roots:
        raise AdapterError("[sources.emmx].roots 为空",
                           hint="在 config/knowatlas.toml 填写脑图文件所在目录")
    from ..semantic.llm import LlmClient

    llm = LlmClient.from_config(config)  # 未启用/无 key → None → 现行节点粒度
    cache = _load_judge_cache(config)
    entries: list[Entry] = []
    stats: dict[str, Any] = {"files": 0, "degraded_files": 0, "nodes": 0,
                             "truncated": 0, "roots_ok": [], "_full_bodies": {},
                             "judge": {"calls": 0, "errors": 0, "cache_hits": 0,
                                       "integral": 0, "split": 0,
                                       "form": "", "reason": "",
                                       "llm_used": llm is not None}}
    for root_str in roots:
        root = Path(root_str)
        if not root.is_dir():
            raise AdapterError(f"脑图根目录不存在：{root_str}",
                               hint="修正 config [sources.emmx].roots 中的路径")
        stats["roots_ok"].append(root.name)
        for p in sorted(root.rglob("*.emmx")):
            if p.is_symlink() or not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            native_dir = (root.name if p.parent == root
                          else "/".join([root.name, *p.parent.relative_to(root).parts]))
            stats["files"] += 1
            stats["judge"]["form"] = ""  # 每文件重置：judge 键只归本文件条目
            stats["judge"]["reason"] = ""
            structured = _parse_emmx(p, rel, native_dir, entries, stats, llm, cache)
            if not structured:
                stats["degraded_files"] += 1
                entries.append(Entry.build(
                    source_type="emmx",
                    source_key=rel,  # 降级：文件级单条目
                    title=p.stem,
                    locator=f"emmx://{rel}#file",
                    locator_canonical=None,
                    native_path=native_dir,
                    meta={"source_type": "emmx", "degraded": True,
                          "reason": "page.xml 缺失或无主题节点（标题级降级）"},
                    created_at=datetime.fromtimestamp(p.stat().st_mtime)
                    .astimezone().isoformat(timespec="seconds"),
                ))
    if llm is not None and stats["judge"]["calls"]:
        _save_judge_cache(config, cache)
    return AdapterOutput(entries=entries, stats=stats)
