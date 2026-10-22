"""知识点抽取流水线（方案 §7.1，0.2.0 第六十二批，Phase 7 批次 61a；
2026-10-22 用户口径改规则判定——批次 66；目录信号三路规则——批次 67）。

链路：候选条目（active、有正文、未抽过）→ **形态判定=三路确定性规则**：
- 文学创作类（分类祖先链含锚词）→ forced split：LLM 只切点不判定；
- 杂烩目录（目录信号粗规则，批次 67 用户口径：项目内文档≈方案、杂烩≈知识点）
  → 走 LLM 形态判定（宁整勿碎偏置，judge 可 integral 可 split）；
- 其余 = 方案 integral，整条即点**零 LLM 费用**。
→ split 走 point_extract（forced split 切点-only prompt）→ 规范化 hash 去重
（点正文 去零宽/压空白/casefold 后 sha1）→ put_point 落库（content_hash 命中
即合并为一点多溯源——溯源数=可信度信号）。

口径依据（用户裁决原话）：「基本可以肯定：所有脑图，和文学创作相关的肯定都是
知识点，剩下的，全是方案」；目录规则（批次 67 输入）：「在某个项目内的文档，
多半就是方案，其他的多数是知识点（同一目录底下有若干内容相差颇大的文件……
这个判断很粗疏）」——杂烩信号必须保守（错误成本不对称：误切=灾难），见
_mixed_dir_entry_ids。

纪律：
- 幂等：已产出过溯源指针的条目自动跳过（point_source_entry_ids 游标），
  LLM 失败条目下次重跑自然补抽；
- 降级：LLM 未启用 → integral 照产（零费用），split/杂烩条目记 error 跳过；
  单条失败记 error 继续下一条，绝不阻塞；
- 原文永不动：点 text 是抽取产物，条目与 content_store 零写入。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..semantic.base import TaskContext
from ..semantic.llm import LlmClient
from ..semantic.tasks import point_extract

_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_WS = re.compile(r"\s+")
_BODY_CAP = 6000      # 送 LLM 的正文字符上限（控成本；截断计数进 stats）
_MIN_BODY_CHARS = 50  # 短于此的正文跳过（无点可抽）
_POINT_BODY_CAP = 20000  # integral 点 text 上限（零 LLM 不心疼 token，保真优先）
_SPLIT_CATEGORY_HINT = "文学创作"  # 用户口径：此分类子树 = 知识点（切），其余 = 方案
# 目录信号杂烩（批次 67）：目录末段名含暗示词（用户自己起的名即信号）——
# 只认粗颗粒暗示词，宁整勿碎；不搞语义猜测。
_MIXED_DIR_HINT = re.compile(r"其他|杂项|临时|收集|整理|归档|misc|archive|backup", re.I)
# 杂烩第二信号：代码/文本类后缀 ≥3 种（用户原话「后端目录中可能有 python 和
# java」）。办公后缀（docx/xlsx/pdf…）**不计数**——同一项目工作流的形态差异
# ≠ 内容杂烩（真实库教训：「Data/百卓/PECOS」docx+xlsx+pdf 是项目目录，机械
# 按后缀多样性判杂烩会误伤 79 条方案）。
_CODE_SUFFIXES = frozenset({
    ".py", ".java", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".md", ".ipynb", ".sh", ".ps1", ".bat", ".sql",
    ".rb", ".php", ".lua", ".kt", ".swift", ".scala", ".vue"})
_MIXED_DIR_MIN_CODE_TYPES = 3

JUDGES = ("integral", "split")


def normalize_point_text(text: str) -> str:
    """点正文规范化（去重键口径）：去零宽字符 → 全部空白序列压单空格 → casefold。

    比 ids.normalize_text（行级、保大小写）更激进：点粒度短，同观点改写通常
    差在空白/全半角外的大小写与装饰性空白；标点差异不归一（宁漏勿误——去重
    键错了会错误合并不同观点）。
    """
    return _WS.sub(" ", _ZERO_WIDTH.sub("", text)).casefold().strip()


def point_hash(text: str) -> str:
    """content_hash = sha1(规范化点正文)；同 hash 即同点（一点多溯源）。"""
    return hashlib.sha1(normalize_point_text(text).encode("utf-8")).hexdigest()


def _entry_body(dl: Any, entry: Any) -> str:
    """条目正文：inline_content 优先，缺了从 content_store 取（K1 未抓正文则为空）。"""
    body = (entry.inline_content or "").strip()
    if not body and entry.content_hash:
        body = (dl.get_content(entry.content_hash) or "").strip()
    return body


def _candidates(dl: Any, limit: int,
                only_ids: list[str] | None = None) -> tuple[list[Any], dict[str, int]]:
    """候选条目：active + 有正文 + 非待清理 + 未抽过。返回 (列表, 跳过统计)。

    only_ids（批次 70 条目级形态覆盖）：指定条目直取——跳过游标检查（调用方
    已 purge_entry_points 清溯源，重抽即视为新候选）；仍要求 active + 有正文。
    """
    done = dl.point_source_entry_ids()
    skipped = {"no_body": 0, "not_knowledge": 0, "already_done": 0, "too_short": 0}
    out: list[Any] = []
    pool = ([dl.get_entry(eid) for eid in only_ids] if only_ids
            else dl.list_entries(status="active", limit=10000))
    for e in pool:
        if e is None:
            continue
        if only_ids is None and e.id in done:
            skipped["already_done"] += 1
            continue
        if str(e.meta.get("value_flag", "")) == "not_knowledge":
            skipped["not_knowledge"] += 1
            continue
        body = _entry_body(dl, e)
        if not body:
            skipped["no_body"] += 1
            continue
        if len(body) < _MIN_BODY_CHARS:
            skipped["too_short"] += 1
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out, skipped


def _offset_of(text: str, body: str) -> int | None:
    """点正文在条目正文中的字符偏移（前 50 字符定位；LLM 改写定位不中 → None）。"""
    head = text[:50]
    pos = body.find(head)
    return pos if pos >= 0 else None


def _split_entry_ids(dl: Any) -> set[str]:
    """用户口径 split 集：分类路径含「文学创作」的条目（确定性规则，零费用）。

    路径=祖先链全名（CTE 派生），子分类名字面不含锚词但祖先含 → 命中；
    无分类条目 → integral（默认方案——口径「剩下的全是方案」的安全侧）。
    """
    hit_cats: dict[str, bool] = {}
    out: set[str] = set()
    for eid, cids in dl.all_entry_categories().items():
        for cid in cids:
            if cid not in hit_cats:
                paths = dl.get_category_paths(cid)
                hit_cats[cid] = any(_SPLIT_CATEGORY_HINT in p for p in paths)
            if hit_cats[cid]:
                out.add(eid)
                break
    return out


def _locator_suffix(locator: str) -> str:
    """条目文件后缀（folder 条目文件名在 locator 路径里；title 已去后缀）。"""
    p = urlparse(locator) if "://" in locator else None
    return Path((p.path if p else locator).rstrip("/")).suffix.lower()


def _mixed_dir_entry_ids(dl: Any) -> set[str]:
    """目录信号杂烩集（批次 67 用户粗规则）：这些条目走 LLM 形态判定。

    仅 folder 源（emmx 有自有判定缓存口径；bookmark 是 URL 集）。
    双信号命中其一即杂烩，但信号本身保守（宁整勿碎）：
    - 目录末段名含暗示词（其他/杂项/临时/归档/misc/archive…）；
    - 目录内代码/文本类后缀 ≥3 种；办公后缀不计数（同项目工作流 ≠ 杂烩）。
    杂烩 ≠ forced split：只取消「零 LLM integral」豁免，交给 LLM 按宁整勿碎
    偏置判（真方案大概率仍 integral，误伤成本=一次调用）。
    """
    by_dir: dict[str, list[Any]] = {}
    for e in dl.list_entries(status="active", limit=10000):
        if e.source_type != "folder":
            continue
        if _locator_suffix(e.locator) == ".emmx":
            continue  # 脑图走 emmx 适配器判定缓存口径（文学创作规则之外，用户口径）
        np = (e.native_path or "").strip().rstrip("/")
        if np:
            by_dir.setdefault(np, []).append(e)
    out: set[str] = set()
    for np, entries in by_dir.items():
        leaf = np.rsplit("/", 1)[-1]
        code_types = {_locator_suffix(e.locator) for e in entries} & _CODE_SUFFIXES
        if _MIXED_DIR_HINT.search(leaf) or len(code_types) >= _MIXED_DIR_MIN_CODE_TYPES:
            out.update(e.id for e in entries)
    return out


def _integral_result(e: Any, body: str, reason: str | None = None) -> dict[str, Any]:
    """integral（零 LLM）：整条即点，text=正文截断保真，summary=标题。"""
    text = body if len(body) <= _POINT_BODY_CAP else body[:_POINT_BODY_CAP] + "…[截断]"
    return {"judge": "integral",
            "reason": reason or "用户口径 2026-10-22：非文学创作=方案整条即点（规则判定，零 LLM）",
            "summary": str(e.title or "")[:120],
            "points": [{"text": text, "summary": str(e.title or "")[:120]}],
            "llm_used": False}


def run_points_extract(cfg: Any, dl: Any, limit: int = 10, dry_run: bool = False,
                       llm: Any = None,
                       entry_ids: list[str] | None = None) -> dict[str, Any]:
    """跑一批知识点抽取；返回统计（CLI 打印 / 测试断言）。

    llm 参数为测试注入口；缺省从 cfg 构建（未启用 → split 条目记 error，
    integral 照产——零费用不依赖 LLM）。
    entry_ids（批次 70 条目级形态覆盖）：只抽指定条目——配套调用方先
    purge_entry_points 清溯源；覆盖判定见主循环 force_form。
    """
    if llm is None:
        llm = LlmClient.from_config(cfg)
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "kpoints")
    stats: dict[str, Any] = {"run_id": run_id, "limit": limit, "dry_run": dry_run,
                             "processed": 0, "integral": 0, "split": 0,
                             "mixed_dir": 0, "force_overrides": 0,
                             "points_created": 0, "points_linked": 0,
                             "body_truncated": 0, "errors": []}
    dry_seen: set[str] = set()  # dry-run 内存态去重（模拟 created/linked 归并）
    try:
        cand, skipped = _candidates(dl, limit, only_ids=entry_ids)
        stats["skip_counts"] = skipped
        stats["pool_remaining"] = max(0, dl.count_entries("active")
                                      - len(cand) - sum(skipped.values()))
        split_ids = _split_entry_ids(dl)
        mixed_ids = _mixed_dir_entry_ids(dl)
        for e in cand:
            body = _entry_body(dl, e)
            # 条目级形态覆盖（批次 70）：meta.force_form 优先于目录/分类规则——
            # "integral" 强制合（文学创作/杂烩也整条即点，零 LLM）；
            # "split" 强制拆（非文学创作也走 LLM 切点）；无/auto → 回归规则。
            force = str(e.meta.get("force_form", "")).strip().lower()
            if force == "integral":
                stats["force_overrides"] += 1
                if len(body) > _POINT_BODY_CAP:
                    stats["body_truncated"] += 1
                res = _integral_result(
                    e, body, reason="用户强制覆盖 meta.force_form=integral（整条即点）")
            elif force == "split" or e.id in split_ids:
                stats["force_overrides"] += 1 if force == "split" else 0
                if llm is None:
                    stats["errors"].append({"entry_id": e.id, "title": e.title[:40],
                                            "error": "split 需 LLM 切点但 llm 未启用"})
                    continue
                if len(body) > _BODY_CAP:
                    body = body[:_BODY_CAP]
                    stats["body_truncated"] += 1
                res = point_extract.run(
                    {"entry_id": e.id, "title": e.title,
                     "source_type": e.source_type, "body": body,
                     "forced_judge": "split"},
                    TaskContext(run_id=run_id, llm=llm))
                if not res.get("llm_used"):
                    stats["errors"].append({"entry_id": e.id, "title": e.title[:40],
                                            "error": res.get("error", "llm 未产出")})
                    continue
            elif e.id in mixed_ids:
                # 杂烩目录（批次 67 目录信号）：走 LLM 形态判定（宁整勿碎偏置，
                # judge 可 integral 可 split）——只取消零 LLM 豁免，不 forced split
                stats["mixed_dir"] += 1
                if llm is None:
                    stats["errors"].append({"entry_id": e.id, "title": e.title[:40],
                                            "error": "杂烩目录需 LLM 判定但 llm 未启用"})
                    continue
                if len(body) > _BODY_CAP:
                    body = body[:_BODY_CAP]
                    stats["body_truncated"] += 1
                res = point_extract.run(
                    {"entry_id": e.id, "title": e.title,
                     "source_type": e.source_type, "body": body},
                    TaskContext(run_id=run_id, llm=llm))
                if not res.get("llm_used"):
                    stats["errors"].append({"entry_id": e.id, "title": e.title[:40],
                                            "error": res.get("error", "llm 未产出")})
                    continue
            else:
                # integral：零 LLM（用户口径「剩下的全是方案」，整条即点）
                if len(body) > _POINT_BODY_CAP:
                    stats["body_truncated"] += 1
                res = _integral_result(e, body)
            stats["processed"] += 1
            stats[res["judge"]] = stats.get(res["judge"], 0) + 1
            for p in res["points"]:
                ph = point_hash(p["text"])
                if not normalize_point_text(p["text"]):
                    continue  # 防御：规范化后为空的点不落库
                point = {"content_hash": ph, "text": p["text"],
                         "summary": p.get("summary", ""),
                         "source_type": e.source_type, "judge": res["judge"],
                         "meta": {"judge_reason": res.get("reason", "")}}
                source = {"entry_id": e.id,
                          "char_offset": _offset_of(p["text"], body),
                          "anchor": p["text"][:80]}
                if dry_run:
                    if ph in dry_seen:
                        stats["points_linked"] += 1
                    else:
                        dry_seen.add(ph)
                        stats["points_created"] += 1
                    continue
                status = dl.put_point(point, source)
                stats[f"points_{status}"] = stats.get(f"points_{status}", 0) + 1
    finally:
        if not dry_run:
            stats["points_total"] = dl.count_points()
        # finish_run 兜底：中途异常也留痕（errors 计数，不丢明细）
        dl.finish_run(run_id, {k: v for k, v in stats.items() if k != "errors"} |
                      {"errors": len(stats["errors"])})
    return stats
