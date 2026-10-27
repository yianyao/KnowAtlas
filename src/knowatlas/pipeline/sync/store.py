"""pipeline/sync/store.py（拆分产物）。"""

# 拆分自 pipeline/sync.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


from dataclasses import replace
from typing import Any
from ...ids import content_hash
from ...models import Entry, FetchResult
from ..clean import CleanThresholds, clean_text
from ._common import _INLINE_LIMIT, _TRUNCATED_AT
from .flags import _now_iso


def _apply_content(entry: Entry, text: str, content_hash_hex: str,
                   fetcher: str, fetched_at: str,
                   clean_meta: dict | None = None) -> Entry:
    """补抓成功后重建条目（同 id upsert 更新正文；截断规则与 manual 源一致）。"""
    inline: str | None
    if len(text) <= _INLINE_LIMIT:
        inline = text
    else:
        inline = text[:_TRUNCATED_AT] + "…[截断，全文在 content_store]"
    meta = dict(entry.meta)
    meta["fetch_backend"] = fetcher
    meta["fetched_at"] = fetched_at
    meta["fetch_status"] = "ok"
    if clean_meta is not None:
        meta["clean"] = clean_meta   # 批 97a：清洗统计（删了多少行、保留率、是否放弃）
    return Entry(
        id=entry.id, source_type=entry.source_type, title=entry.title,
        locator=entry.locator, locator_canonical=entry.locator_canonical,
        native_path=entry.native_path, inline_content=inline,
        content_hash=content_hash_hex, meta=meta, created_at=entry.created_at,
        exported_at=entry.exported_at, status=entry.status,
    )


def _store_bodies(cfg: Any, dl: Any, bodies: dict[str, str],
                  fetcher: str) -> list[Entry]:
    """适配器产出的全量正文（mail/session/emmx）走同一清洗口径。

    与 `_ingest_content` 的差别：这些源的 `inline_content` 是适配器算好的增量摘要
    （例如邮件要去掉引用块），**不能**用全量正文重建——这里只清正文库那一份，
    条目仅更新 `content_hash` 与 `meta.clean`（批 97a）。
    """
    enabled, redact_on, thresholds = _clean_options(cfg)
    out: list[Entry] = []
    for eid, text in bodies.items():
        e = dl.get_entry(eid)
        if e is None:
            continue
        if e.content_hash and dl.get_content(e.content_hash) is not None:
            continue  # 已入库（幂等：重复同步不重建）
        body, clean_meta = text, None
        if enabled:
            result = clean_text(text, thresholds, redact_enabled=redact_on)
            body, clean_meta = result.text, result.as_meta()
        fhash = content_hash(body)
        dl.put_content(FetchResult(text=body, content_hash=fhash,
                                   fetcher=fetcher, fetched_at=_now_iso()))
        meta = dict(e.meta)
        if clean_meta is not None:
            meta["clean"] = clean_meta
        out.append(replace(e, content_hash=fhash, meta=meta))
    if out:
        dl.upsert_entries(out)
    return out


def _ingest_content(cfg: Any, dl: Any, entry: Entry, raw_text: str,
                    fetcher: str, fetched_at: str) -> Entry:
    """**唯一正文收口**（批 97a）：清洗 → 脱敏 → 内容 SHA-256 → content_store。

    所有正文入库路径都必须过这里，否则库里会同时存在"洗过的"和"没洗的"正文，
    点层无法解释。`content_hash` 一律按**清洗后**文本计算——同一篇文不会因清洗前后
    变成两条记录。返回重建后的条目（调用方负责 upsert）。
    """
    enabled, redact_on, thresholds = _clean_options(cfg)
    if enabled:
        # clean_text 会按有无页分隔符（\f）自动选 clean_paged / clean_common：
        # PDF 快速通道带页边界，能无条件删页边页码与跨页页眉（批 97b）
        result = clean_text(raw_text, thresholds, redact_enabled=redact_on)
        text, clean_meta = result.text, result.as_meta()
    else:
        text, clean_meta = raw_text, None
    fhash = content_hash(text)
    dl.put_content(FetchResult(text=text, content_hash=fhash,
                               fetcher=fetcher, fetched_at=fetched_at))
    return _apply_content(entry, text, fhash, fetcher, fetched_at,
                          clean_meta=clean_meta)


def _clean_options(cfg: Any) -> tuple[bool, bool, CleanThresholds]:
    """读 [clean] 段：是否清洗 / 是否脱敏 / 阈值。

    兜底值**必须**取 `CleanThresholds()` 的默认值，不能另抄一份数字——
    否则配置里没写 [clean] 时，这里的兜底会静默覆盖掉默认阈值
    （真实踩坑：这里抄了 0.90，导致 0.856 的书被判"洗太狠"整篇退回原文）。
    """
    defaults = CleanThresholds()
    try:
        keep = float(cfg.get("clean.min_keep_ratio", defaults.min_keep_ratio))
    except (TypeError, ValueError):
        keep = defaults.min_keep_ratio
    return (bool(cfg.get("clean.enabled", True)),
            bool(cfg.get("clean.redact_enabled", True)),
            CleanThresholds(min_keep_ratio=keep))
