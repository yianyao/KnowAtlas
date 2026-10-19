"""万兴脑图适配器（source_type=emmx，完整方案 §3.2 / §12 步骤 15，M1）。

.emmx = ZIP 包。真实格式（MindMaster 9.x，2026-10-19 以 9 个真实样本解剖定稿）：
- 主题树在 page/page.xml（document.xml 的 Properties/Pages 指明页名，可能多页）；
- 节点 = <Shape Type="MainIdea|MainTopic|SubTopic|SummaryTopic">，标题文本在
  Text/TextBlock/Text 深层的 <tp> 元素里（多段合并）；
- 层级不是 XML 嵌套，而是 <LevelData><Super V="父 Shape ID"/> 引用；父指向
  Boundary/Summary 等装饰容器时断链，按顶层分支处理；
- Boundary/Summary/Callout/MMConnector 等非主题 Shape 不建条目；
- page.xml 缺失（如仅 mmpage/page.bin 旧版二进制）/ 坏 ZIP / 无主题节点 →
  降级标题级单条目，meta.degraded=true。

契约：source_key = 文件相对路径 + "#页名/节点id"；locator = emmx://<相对路径>#<页名/节点id>；
native_path = 文件所在目录层级（先验信号），脑图内部主题路径进 meta.mind_path。
"""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..errors import AdapterError
from ..models import Entry
from .base import AdapterOutput

_MAX_NODES = 3000  # 单脑图节点上限（防失控）
_MAX_DEPTH = 30  # Super 引用上溯深度上限（防引用环死循环）
_TOPIC_TYPES = {"MainIdea", "MainTopic", "SubTopic", "SummaryTopic"}


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


def _parse_page(data: bytes, page_name: str, rel: str, native_dir: str,
                entries: list[Entry], stats: dict[str, Any]) -> bool:
    """解析单页 page.xml；返回是否产出条目。"""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return False
    # 第一遍：收集主题节点 id -> (标题, 父 id)
    topics: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    for i, shape in enumerate(root.iter("Shape")):
        if (shape.get("Type") or "") not in _TOPIC_TYPES:
            continue
        if len(order) >= _MAX_NODES:
            stats["truncated"] = stats.get("truncated", 0) + 1
            break
        sid = (shape.get("ID") or "").strip() or f"s{i}"
        topics[sid] = (_shape_title(shape), _super_id(shape))
        order.append(sid)
    # 第二遍：沿 Super 引用上溯构建 mind_path，产出条目
    produced = 0
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
        entries.append(Entry.build(
            source_type="emmx",
            source_key=f"{rel}#{node_id}",
            title=title,
            locator=f"emmx://{rel}#{node_id}",
            locator_canonical=None,
            native_path=native_dir,
            meta={"source_type": "emmx", "mind_path": "/".join(chain),
                  "depth": max(1, len(chain))},
            created_at=None,
        ))
        produced += 1
        stats["nodes"] += 1
    return produced > 0


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
                entries: list[Entry], stats: dict[str, Any]) -> bool:
    """解析单个 .emmx；返回 True=结构化解析成功，False=降级标题级。

    native_dir = 根名/文件所在子目录层级（先验信号，与 folder 适配器同构）。
    """
    try:
        with zipfile.ZipFile(path) as zf:
            page_list = _page_xml_names(zf)
            if not page_list:
                return False
            produced_any = False
            for page_name, xml_path in page_list:
                try:
                    data = zf.read(xml_path)
                except KeyError:
                    continue
                if _parse_page(data, page_name, rel, native_dir, entries, stats):
                    produced_any = True
            return produced_any
    except (zipfile.BadZipFile, OSError):
        return False


def collect_emmx(config: Any) -> AdapterOutput:
    """按 [sources.emmx].roots 遍历 .emmx 文件，产出脑图节点条目。"""
    roots = [str(r) for r in (config.get("sources.emmx.roots") or []) if str(r).strip()]
    if not roots:
        raise AdapterError("[sources.emmx].roots 为空",
                           hint="在 config/knowatlas.toml 填写脑图文件所在目录")
    entries: list[Entry] = []
    stats: dict[str, Any] = {"files": 0, "degraded_files": 0, "nodes": 0,
                             "roots_ok": []}
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
            structured = _parse_emmx(p, rel, native_dir, entries, stats)
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
    return AdapterOutput(entries=entries, stats=stats)
