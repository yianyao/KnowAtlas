"""正文库孤儿回收（TODO 8.15）：content_store 无条目引用 → 按阈值回收。

覆盖：dry-run 零写入 / 实跑只删孤儿 / 有新引用的正文一行不少 / 过新孤儿跳过 /
content_fts 同步清理 / 幂等（重跑 candidates=0）/ task_log 审计留痕。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from knowatlas.models import Entry, FetchResult

OLD = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat(timespec="seconds")
RECENT = datetime.now(timezone.utc).isoformat(timespec="seconds")


def _content(dl, text: str, fetched_at: str) -> str:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    dl.put_content(FetchResult(text=text, content_hash=h, fetcher="test",
                               fetched_at=fetched_at))
    return h


def _entry(dl, key: str, url: str, content_hash: str | None = None) -> Entry:
    e = Entry.build(source_type="bookmark", source_key=key, title=key,
                    locator=url, locator_canonical=url, content_hash=content_hash)
    dl.upsert_entries([e])
    return e


def _seed(dl) -> dict[str, str]:
    """3 行孤儿（老/新/无时间戳）+ 1 行被条目引用。"""
    h_old = _content(dl, "孤儿正文（旧）" * 20, OLD)
    h_new = _content(dl, "孤儿正文（新，竞态保护）" * 20, RECENT)
    h_blank = _content(dl, "孤儿正文（无 fetched_at 的历史行）" * 20, "")
    h_used = _content(dl, "被条目引用的正文" * 20, OLD)
    _entry(dl, "kept", "https://kept.example/a", h_used)
    return {"old": h_old, "new": h_new, "blank": h_blank, "used": h_used}


def test_dry_run_reports_without_writing(dl):
    hs = _seed(dl)
    before = dl._conn.execute("SELECT COUNT(*) FROM content_store").fetchone()[0]
    stats = dl.gc_orphan_contents(max_age_days=1.0, dry_run=True)
    assert (stats["candidates"], stats["eligible"], stats["skipped_recent"],
            stats["deleted"]) == (3, 2, 1, 0)
    assert stats["freed_chars"] > 0
    after = dl._conn.execute("SELECT COUNT(*) FROM content_store").fetchone()[0]
    assert after == before                              # dry-run 零写入
    assert dl.get_content(hs["old"]) is not None
    assert [r for r in dl.get_task_log(10) if r["task_name"] == "content_gc"] == []


def test_gc_deletes_only_orphans_and_keeps_referenced(dl):
    hs = _seed(dl)
    stats = dl.gc_orphan_contents(max_age_days=1.0, dry_run=False)
    assert (stats["candidates"], stats["eligible"], stats["deleted"]) == (3, 2, 2)
    assert dl.get_content(hs["old"]) is None             # 老孤儿删
    assert dl.get_content(hs["blank"]) is None           # 无时间戳按最老处理
    assert dl.get_content(hs["new"]) is not None         # 过新：竞态保护
    assert dl.get_content(hs["used"]) is not None        # 有引用：一行不动
    # content_fts 同步清理（正文检索索引不留悬挂行）
    n = dl._conn.execute("SELECT COUNT(*) AS c FROM content_fts WHERE content_hash=?",
                         (hs["old"],)).fetchone()["c"]
    assert n == 0
    n_new = dl._conn.execute("SELECT COUNT(*) AS c FROM content_fts WHERE content_hash=?",
                             (hs["new"],)).fetchone()["c"]
    assert n_new == 1
    # task_log 审计一次，detail 带现场数字
    log = [r for r in dl.get_task_log(10) if r["task_name"] == "content_gc"]
    assert len(log) == 1 and log[0]["action"] == "gc_orphan"
    assert log[0]["detail"]["deleted"] == 2 and log[0]["detail"]["candidates"] == 3


def test_gc_is_idempotent(dl):
    _seed(dl)
    first = dl.gc_orphan_contents(max_age_days=1.0, dry_run=False)
    assert (first["eligible"], first["deleted"]) == (2, 2)
    again = dl.gc_orphan_contents(max_age_days=1.0, dry_run=False)
    assert (again["eligible"], again["deleted"]) == (0, 0)
    assert again["candidates"] == 1          # 只剩被阈值保护的过新孤儿
    # 放开阈值再跑一次 → 清零；第三跑 candidates=0（真幂等）
    dl.gc_orphan_contents(max_age_days=0, dry_run=False)
    third = dl.gc_orphan_contents(max_age_days=0, dry_run=False)
    assert third["candidates"] == 0 and third["deleted"] == 0


def test_gc_days_zero_collects_recent_orphans_too(dl):
    hs = _seed(dl)
    stats = dl.gc_orphan_contents(max_age_days=0, dry_run=False)
    assert (stats["candidates"], stats["eligible"], stats["deleted"]) == (3, 3, 3)
    assert dl.get_content(hs["new"]) is None
    assert dl.get_content(hs["used"]) is not None