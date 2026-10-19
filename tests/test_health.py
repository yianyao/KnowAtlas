"""链接体检（kcheck）：mock 检测函数，测试不真发网络请求。"""

from __future__ import annotations

import pytest

from knowatlas.models import Entry
from knowatlas.pipeline import health


@pytest.fixture
def entries(dl):
    out = []
    for i, (key, url) in enumerate([
        ("h1", "https://ok.example/a"),        # 200 → ok
        ("h2", "https://gone.example/b"),      # 404 → dead
        ("h3", "https://deny.example/c"),      # 403 → blocked（反爬，对人有效）
    ]):
        e = Entry.build(source_type="bookmark", source_key=key, title=f"页{i}",
                        locator=url, locator_canonical=url)
        dl.upsert_entries([e])
        out.append(e)
    return out


def test_health_check_marks_meta(dl, entries, monkeypatch):
    codes = {"https://ok.example/a": (200, "ok"),
             "https://gone.example/b": (404, "dead"),
             "https://deny.example/c": (403, "blocked")}
    monkeypatch.setattr(health, "check_link",
                        lambda url, timeout=10.0: (codes[url][1], codes[url][0]))
    monkeypatch.setattr(health.time, "sleep", lambda s: None)
    stats = health.run_health_check(object(), dl, limit=100, qps=1000.0)
    assert stats == {"checked": 3, "ok": 1, "dead": 1, "blocked": 1, "error": 0}
    e_dead = dl.get_entry(entries[1].id)
    assert e_dead.meta["link_status"] == "dead" and e_dead.meta["link_code"] == 404
    assert e_dead.meta["link_checked_at"]
    assert dl.get_entry(entries[0].id).meta["link_status"] == "ok"


def test_list_by_link_status(dl, entries, monkeypatch):
    codes = {"https://ok.example/a": ("ok", 200),
             "https://gone.example/b": ("dead", 404),
             "https://deny.example/c": ("blocked", 403)}
    monkeypatch.setattr(health, "check_link",
                        lambda url, timeout=10.0: (codes[url][0], codes[url][1]))
    monkeypatch.setattr(health.time, "sleep", lambda s: None)
    health.run_health_check(object(), dl, limit=100, qps=1000.0)
    assert [e.id for e in dl.list_by_link_status("dead")] == [entries[1].id]
    assert [e.id for e in dl.list_by_link_status("blocked")] == [entries[2].id]
    assert [e.id for e in dl.list_by_link_status("ok")] == [entries[0].id]
    # UI 死链视图只展示 dead/error（数据层按参数过滤，行为正确）
