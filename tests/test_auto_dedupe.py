"""自动去重（2026-10-30 工单《收录与源脱节》§2.3）：存量扫描 + 转正后补跑。"""

from __future__ import annotations

from knowatlas.ids import content_hash
from knowatlas.models import Entry, FetchResult
from knowatlas.pipeline.sync import run_sync


def _entry(dl, key: str, text: str, *, created_at: str | None = None) -> Entry:
    h = content_hash(text)
    dl.put_content(FetchResult(text=text, content_hash=h, fetcher="test",
                               fetched_at="2026-10-30T00:00:00+08:00"))
    e = Entry.build(
        source_type="manual", source_key=key, title=f"标题-{key}",
        locator=f"https://example.com/posts/{key}",
        locator_canonical=f"https://example.com/posts/{key}",
        content_hash=h, meta={}, created_at=created_at,
    )
    dl.upsert_entries([e])
    return e


def test_sync_tail_merges_stock_duplicates(cfg, dl, registries):
    """存量同正文条目：不用手敲 --dedupe-scan，任何一次同步收尾都会合并。"""
    a = _entry(dl, "a", "同一篇正文，重复出现两次。",
               created_at="2026-01-01T00:00:00+08:00")
    b = _entry(dl, "b", "同一篇正文，重复出现两次。")
    stats = run_sync(cfg, dl, registries[0], registries[1])
    assert stats["dedupe_scan"]["merged"] == 1
    assert dl.get_entry(b.id).meta["dedupe_master"] == a.id
    assert not dl.get_entry(a.id).meta.get("dedupe_master")


def test_sync_tail_dry_run_does_not_merge(cfg, dl, registries):
    a = _entry(dl, "a", "干跑不该写库的正文。")
    b = _entry(dl, "b", "干跑不该写库的正文。")
    stats = run_sync(cfg, dl, registries[0], registries[1], dry_run=True)
    assert stats["dedupe_scan"]["dry_run"] is True
    assert stats["dedupe_scan"]["merged"] == 0
    assert not dl.get_entry(a.id).meta.get("dedupe_master")
    assert not dl.get_entry(b.id).meta.get("dedupe_master")


def test_activate_pending_dedupes(cfg, dl):
    """pending 转正后补跑判重：转正即归位，不用等下一次同步。"""
    a = _entry(dl, "a", "待审转正后应与主条目合并的正文。",
               created_at="2026-01-01T00:00:00+08:00")
    b = _entry(dl, "b", "待审转正后应与主条目合并的正文。")
    dl.set_status([b.id], "pending")

    from knowatlas.pipeline.ingest import activate_pending

    st = activate_pending(cfg, dl)
    assert st["activated"] == 1
    assert dl.get_entry(b.id).status == "active"
    assert dl.get_entry(b.id).meta["dedupe_master"] == a.id
