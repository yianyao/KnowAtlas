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
from typing import Any

from ..adapters.bookmark import collect_bookmarks
from ..errors import AdapterError, DegradedParseError, FetchError
from ..ids import content_hash
from ..models import Entry, FetchResult
from ..registry.capability import FetchContext
from ..semantic.base import SemanticInput, TaskContext
from .kadd import ensure_category_path

# 全量遍历型批量源注册：源配置名 → 收集函数（新批量源 = 一行 + 适配器文件）
_BATCH_COLLECTORS: dict[str, Any] = {
    "bookmarks": collect_bookmarks,
}

_INLINE_LIMIT = 4096
_TRUNCATED_AT = 4000


def _categorize(dl: Any, semantics: Any, entries: list[Entry], target_ids: set[str],
                run_id: str) -> dict[str, int]:
    """对本次新建条目批量跑 classify_coarse；未命中进暂存区（不挂分类）。"""
    targets = [e for e in entries if e.id in target_ids]
    if not targets:
        return {"classified": 0, "staged": 0}
    _, classify = semantics.resolve_task("classify_coarse")
    known = frozenset(dl.all_category_paths())
    inputs = [
        SemanticInput(entry_id=e.id, title=e.title, body=e.inline_content,
                      native_path=e.native_path, meta=e.meta)
        for e in targets
    ]
    outputs = classify(inputs, TaskContext(run_id=run_id, known_paths=known))
    classified = staged = 0
    for entry, out in zip(targets, outputs):
        if not out.classifications:
            staged += 1
            continue
        for classification in out.classifications:
            cid = ensure_category_path(dl, classification.category_path, classification.origin)
            dl.attach_category(entry.id, cid, classification.confidence,
                               classification.origin, run_id)
        classified += 1
    return {"classified": classified, "staged": staged}


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
        if e.locator_canonical is None:  # 非 http/https 条目无正文可抓
            continue
        if e.content_hash and dl.get_content(e.content_hash) is not None:
            continue  # 正文已在 content_store（抓过一次不重复抓）
        try:
            text, title = fetch_with_fallback(e.locator, locators, ctx)
        except (FetchError, DegradedParseError):
            failed += 1
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


def run_sync(cfg: Any, dl: Any, locators: Any, semantics: Any, *,
             full: bool = False, source: str | None = None, dry_run: bool = False,
             limit: int | None = None, fetch_limit: int | None = None) -> dict[str, Any]:
    """同步入口。返回统计 dict（各源 created/updated/unchanged/archived/分类分布）。"""
    run_id = uuid.uuid4().hex[:16]
    kind = "sync_full" if full else "sync_incremental"
    dl.start_run(run_id, kind)
    stats: dict[str, Any] = {"sources": {}}

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

        # 预检新建 id（upsert 幂等；分类只挂新建条目，unchanged 不重复挂）
        new_ids = {e.id for e in entries if dl.get_entry(e.id) is None}
        result = dl.upsert_entries(entries)
        cat = _categorize(dl, semantics, entries, new_ids, run_id)

        src_stats: dict[str, Any] = {
            "entries": len(entries),
            "created": result.created, "updated": result.updated,
            "unchanged": result.unchanged, **cat, **out.stats,
        }
        if full:
            archived = dl.archive_missing(source_type="bookmark",
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
