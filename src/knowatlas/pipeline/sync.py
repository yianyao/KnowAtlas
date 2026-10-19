"""同步编排（完整方案 §3.6）。

两类同步策略：
- 全量遍历型（bookmark/folder/emmx/bili/session/db/wx 文件产物）：全量拉取 + 幂等 upsert
  + 删除检测（full=True 时 missing_in_source → archived）——按 M1 起逐个接入；
- 游标型（mail/ima/txdoc）：各自游标增量，M3 起接入。

已接入批量源：bookmarks（adapters/bookmark.py）。

纪律：
- K1：同步默认不抓正文（fetch.on_sync=false）——--fetch-limit N 显式开启，本次最多 N 条
  缺正文的 http 条目走 fetch_with_fallback 补抓；
- 分类只跑 classify_coarse（L1 先验 + L2 规则，未命中进暂存区，绝不硬猜），
  且只对本次新建条目执行——unchanged 条目幂等跳过，不重复挂分类；
- 适配器抛 AdapterError → 跳过该源、其余源继续（完整方案 §10.1）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ..adapters.bookmark import collect_bookmarks
from ..adapters.folder import collect_folders
from ..errors import AdapterError, DegradedParseError, FetchError
from ..ids import content_hash
from ..models import Entry, FetchResult
from ..registry.capability import FetchContext
from ..semantic.base import SemanticInput, TaskContext
from .kadd import ensure_category_path


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

# 全量遍历型批量源注册：源配置名 → 收集函数（新批量源 = 一行 + 适配器文件）
_BATCH_COLLECTORS: dict[str, Any] = {
    "bookmarks": collect_bookmarks,
    "folders": collect_folders,
}
# 配置名 → source_type（archive_missing 按条目来源类型做删除检测）
_SOURCE_TYPE_BY_NAME: dict[str, str] = {"bookmarks": "bookmark", "folders": "folder"}

_INLINE_LIMIT = 4096
_TRUNCATED_AT = 4000


_INLINE_LIMIT = 4096
_TRUNCATED_AT = 4000

# 与 datalayer.db._SOURCE_FIELDS 保持一致（upsert 的 updated 判定字段）——
# 改动任一处必须同步另一处并跑全量测试
_SOURCE_FIELDS = ("title", "locator", "locator_canonical", "native_path",
                  "inline_content", "content_hash")


def _categorize(dl: Any, semantics: Any, cfg: Any, entries: list[Entry], new_ids: set[str],
                updated_ids: set[str], run_id: str) -> dict[str, int]:
    """对本次新建/更新条目批量跑 classify_coarse；未命中进暂存区（不挂分类）。

    更新条目（书签移动文件夹、标题变化等）先 detach 机器来源（origin != manual）
    的旧挂接再重挂——人工校正（origin=manual）永不覆盖（H3）。
    L3 LLM：cfg 的 [llm] 启用且 key 已设时自动生效，否则静默跳过。
    """
    targets = [e for e in entries if e.id in new_ids or e.id in updated_ids]
    if not targets:
        return {"classified": 0, "staged": 0, "reclassified": 0}
    _, classify = semantics.resolve_task("classify_coarse")
    from ..semantic.llm import LlmClient

    known = frozenset(dl.all_category_paths())
    inputs = [
        SemanticInput(entry_id=e.id, title=e.title, body=e.inline_content,
                      native_path=e.native_path,
                      meta={**e.meta, "locator": e.locator})
        for e in targets
    ]
    outputs = classify(inputs, TaskContext(run_id=run_id, known_paths=known,
                                           llm=LlmClient.from_config(cfg), config=cfg))
    classified = staged = 0
    for entry, out in zip(targets, outputs):
        if "not_knowledge" in out.tags and entry.meta.get("value_flag") != "ok":
            # LLM 判非知识 → 待清理候选；用户已否决（value_flag=ok）的不再标记
            dl.merge_meta(entry.id, {"value_flag": "not_knowledge"})
        if entry.id in updated_ids:
            # 旧机器分类清理：书签换文件夹等场景下避免新旧分类并存
            for link in dl.get_entry_categories(entry.id):
                if link["origin"] != "manual":
                    dl.detach_category(entry.id, link["category_id"])
        if not out.classifications:
            staged += 1
            continue
        for classification in out.classifications:
            cid = ensure_category_path(dl, classification.category_path, classification.origin)
            dl.attach_category(entry.id, cid, classification.confidence,
                               classification.origin, run_id)
        classified += 1
    return {"classified": classified, "staged": staged,
            "reclassified": sum(1 for e in targets if e.id in updated_ids)}


def _apply_content(entry: Entry, text: str, content_hash_hex: str,
                   fetcher: str, fetched_at: str) -> Entry:
    """补抓成功后重建条目（同 id upsert 更新正文；截断规则与 manual 源一致）。"""
    inline: str | None
    if len(text) <= _INLINE_LIMIT:
        inline = text
    else:
        inline = text[:_TRUNCATED_AT] + "…[截断，全文在 content_store]"
    meta = dict(entry.meta)
    meta["fetch_backend"] = fetcher
    meta["fetched_at"] = fetched_at
    return Entry(
        id=entry.id, source_type=entry.source_type, title=entry.title,
        locator=entry.locator, locator_canonical=entry.locator_canonical,
        native_path=entry.native_path, inline_content=inline,
        content_hash=content_hash_hex, meta=meta, created_at=entry.created_at,
        exported_at=entry.exported_at, status=entry.status,
    )


def _fetch_missing(cfg: Any, dl: Any, locators: Any, entries: list[Entry],
                   limit: int, run_id: str) -> dict[str, int]:
    """K1 显式补抓：对缺正文的 http(s) 条目抓取，最多 limit 条；失败计数不中断。"""
    import httpx
    from datetime import datetime

    from ..fetchers.base import fetch_with_fallback

    done = failed = 0
    ctx = FetchContext(config=cfg, datalayer=dl, http=httpx.Client(), run_id=run_id)
    updates: list[Entry] = []
    for e in entries:
        if done >= limit:
            break
        is_file = e.locator.startswith("file://")
        if e.locator_canonical is None and not is_file:
            continue  # 非 http 且非 file，无正文可抓
        if e.content_hash and dl.get_content(e.content_hash) is not None:
            continue  # 正文已在 content_store（抓过一次不重复抓）
        try:
            text, title = fetch_with_fallback(e.locator, locators, ctx)
        except (FetchError, DegradedParseError):
            failed += 1  # 不可读文件（乱码/解析失败）在此暴露——条目保留，可手动舍弃
            continue
        fhash = content_hash(text)
        dl.put_content(FetchResult(text=text, content_hash=fhash,
                                   fetcher=str(cfg.get("fetch.default_backend", "simple")),
                                   fetched_at=datetime.now().astimezone().isoformat(timespec="seconds")))
        updates.append(_apply_content(e, text, fhash,
                                      str(cfg.get("fetch.default_backend", "simple")),
                                      datetime.now().astimezone().isoformat(timespec="seconds")))
        done += 1
    if updates:
        dl.upsert_entries(updates)
    return {"fetched": done, "fetch_failed": failed}


def _reclassify_all(cfg: Any, dl: Any, semantics: Any, run_id: str) -> dict[str, Any]:
    """全量重分类：active 条目重跑 classify_coarse 三级流水线。

    语义（0.2.0 修正，用户反馈"LLM 不该顺手归并残留类目"）：
    - 先统一 detach 全部机器分类；候选路径（known_paths）只保留**人工挂接**的分类——
      LLM 的类目候选由用户认可的类目决定，不再被旧机器类目 anchor；
    - 含人工挂接的条目整条跳过（人工结论优先，H3）；
    - 重跑后自动清理空壳机器类目（无条目、无子类、origin != manual）；
    - [llm] 未启用 / key 未设时 L3 静默跳过，结果 = 先验+规则（stats.llm_used=false）。
    """
    from ..semantic.base import SemanticInput, TaskContext
    from ..semantic.llm import LlmClient

    llm = LlmClient.from_config(cfg)
    _, classify = semantics.resolve_task("classify_coarse")
    entries = dl.list_entries(status="active", limit=10000)
    # 含人工挂接的条目跳过；其余先统一摘除机器分类
    # 1) detach 前清理真·空壳（历史遗留、无挂接无子类且非人工）
    dropped = dl.delete_empty_categories()
    # 1.5) 碎片收拢：单条目的机器二级类目并入一级（树由内容聚出来，2026-10-19 用户定调）
    moved = dl.prune_fragment_categories(min_size=2)
    if moved:
        dl.log_task(_now_iso(), "sync", "prune_fragments", "auto",
                    {"count": len(moved), "names": [m["name"] for m in moved]})
    # 2) 快照大类骨架：detach 前有真实条目支撑的一级类目（防待清理类目混入候选）
    root_names = {n["name"] for n in dl.get_tree()}
    # 3) 摘除全部机器分类
    targets: list[Entry] = []
    for e in entries:
        links = dl.get_entry_categories(e.id)
        if any(l["origin"] == "manual" for l in links):
            continue
        targets.append(e)
        for link in links:
            dl.detach_category(e.id, link["category_id"])
    # 候选 = 人工挂接路径 ∪ 大类骨架（完整旧路径不进候选，防顺手归并碎片类目）
    known = frozenset(dl.manual_category_paths() | root_names)
    classified = staged = 0
    max_batch = int(cfg.get("llm.max_batch", 20) or 20)
    for i in range(0, len(targets), max_batch):
        chunk = targets[i:i + max_batch]
        outputs = classify(
            [SemanticInput(entry_id=e.id, title=e.title, body=e.inline_content,
                           native_path=e.native_path,
                           meta={**e.meta, "locator": e.locator}) for e in chunk],
            TaskContext(run_id=run_id, known_paths=known, llm=llm, config=cfg),
        )
        for e, out in zip(chunk, outputs):
            if "not_knowledge" in out.tags and e.meta.get("value_flag") != "ok":
                # LLM 判非知识 → 待清理候选；用户已否决的不再标记
                dl.merge_meta(e.id, {"value_flag": "not_knowledge"})
            if not out.classifications:
                staged += 1
                continue
            for classification in out.classifications:
                cid = ensure_category_path(dl, classification.category_path,
                                           classification.origin)
                dl.attach_category(e.id, cid, classification.confidence,
                                   classification.origin, run_id)
            classified += 1
    dropped = dl.delete_empty_categories()
    # 分类后再收拢一次：本轮 LLM 新产生的单条目碎片也并入一级
    moved = dl.prune_fragment_categories(min_size=2)
    if moved:
        dl.log_task(_now_iso(), "sync", "prune_fragments", "auto",
                    {"count": len(moved), "names": [m["name"] for m in moved]})
    if dropped:
        dl.log_task(_now_iso(), "sync", "drop_empty_categories", ",".join(d[0] for d in dropped),
                    {"names": [d[1] for d in dropped], "count": len(dropped)})
    stats = {"reclassify_total": len(targets), "classified": classified,
             "staged": staged, "llm_used": llm is not None,
             "dropped_empty_categories": [d[1] for d in dropped],
             "pruned_fragments": len(moved)}
    dl.log_task(_now_iso(), "sync", "reclassify", "all",
                {k: v for k, v in stats.items()})
    return stats


def run_sync(cfg: Any, dl: Any, locators: Any, semantics: Any, *,
             full: bool = False, source: str | None = None, dry_run: bool = False,
             limit: int | None = None, fetch_limit: int | None = None,
             reclassify: bool = False) -> dict[str, Any]:
    """同步入口。返回统计 dict（各源 created/updated/unchanged/archived/分类分布）。

    reclassify=True 时跳过源收集，只对库中全部 active 条目重跑分类。
    """
    run_id = uuid.uuid4().hex[:16]
    kind = "sync_full" if full else "sync_incremental"
    dl.start_run(run_id, kind)
    stats: dict[str, Any] = {"sources": {}}
    if reclassify:
        stats["reclassify"] = _reclassify_all(cfg, dl, semantics, run_id)
        dl.finish_run(run_id, stats)
        return {"run_id": run_id, **stats}

    for name, collector in _BATCH_COLLECTORS.items():
        if source is not None and source != name:
            continue
        sec = cfg.get(f"sources.{name}") or {}
        if not sec.get("enabled"):
            continue
        try:
            out = collector(cfg)
        except AdapterError as exc:
            stats["sources"][name] = {"error": f"{type(exc).__name__}: {exc}"}
            continue

        entries: list[Entry] = list(out.entries)
        if limit is not None:
            entries = entries[:limit]
        if dry_run:
            stats["sources"][name] = {"reachable": True, "entry_count": len(entries), **out.stats}
            continue

        # 预检：新建 id、更新 id（源字段有真实变化）、归档复活（曾 missing → 源里重新出现）
        new_ids: set[str] = set()
        updated_ids: set[str] = set()
        revived_ids: list[str] = []
        for e in entries:
            old = dl.get_entry(e.id)
            if old is None:
                new_ids.add(e.id)
                continue
            if old.status == "archived":
                revived_ids.append(e.id)
            if any(getattr(old, f) != getattr(e, f) for f in _SOURCE_FIELDS):
                updated_ids.add(e.id)
        result = dl.upsert_entries(entries)
        if revived_ids:
            dl.set_status(revived_ids, "active")  # upsert 不写 status；源里重现即恢复
            dl.log_task(_now_iso(), "sync", "revive", ",".join(revived_ids),
                        {"count": len(revived_ids),
                         "source_type": _SOURCE_TYPE_BY_NAME.get(name, name)})
        cat = _categorize(dl, semantics, cfg, entries, new_ids, updated_ids, run_id)

        src_stats: dict[str, Any] = {
            "entries": len(entries),
            "created": result.created, "updated": result.updated,
            "unchanged": result.unchanged, **cat, **out.stats,
        }
        if full:
            archived = dl.archive_missing(
                source_type=_SOURCE_TYPE_BY_NAME.get(name, name),
                seen_ids={e.id for e in entries}, run_id=run_id)
            src_stats["archived"] = len(archived)
        if fetch_limit:
            src_stats.update(_fetch_missing(cfg, dl, locators, entries, fetch_limit, run_id))
        stats["sources"][name] = src_stats

    if not stats["sources"]:
        stats["note"] = ("无可同步的已启用批量源：在 config/knowatlas.toml 启用"
                         " [sources.bookmarks] 等源，或用 kadd 手动收录")
    dl.finish_run(run_id, stats)
    return {"run_id": run_id, **stats}
