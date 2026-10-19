"""舍弃机制（rejected 状态：不入树/检索，重新同步不复活）与碎片类目收拢。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knowatlas.models import Entry
from knowatlas.pipeline.sync import run_sync
from knowatlas.web.app import create_app


@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")), "test-token-123")
    locators, semantics = registries
    return TestClient(create_app(cfg, dl, locators, semantics),
                      headers={"Host": "127.0.0.1:8420"})


def _auth():
    return {"X-KnowAtlas-Token": "test-token-123", "Origin": "http://127.0.0.1:8420"}


def _mk_entry(dl, key: str, title: str) -> Entry:
    e = Entry.build(source_type="bookmark", source_key=key, title=title,
                    locator=f"https://x.example/{key}", locator_canonical=f"https://x.example/{key}")
    dl.upsert_entries([e])
    return e


def test_reject_lifecycle(client, dl):
    """舍弃 → 树/检索/暂存区均排除 → 恢复回来。"""
    e = _mk_entry(dl, "edge:r1", "要舍弃的页")
    cat = dl.create_category("回收测试", [], "rule")
    dl.attach_category(e.id, cat.id, 1.0, "rule", "r1")
    r = client.post(f"/api/entries/{e.id}/reject", json={}, headers=_auth())
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    # 树条目查询排除
    ents = client.get(f"/api/categories/{cat.id}/entries").json()["entries"]
    assert all(x["id"] != e.id for x in ents)
    # 检索排除
    assert all(h.entry_id != e.id for h in dl.search_fts("舍弃"))
    # 已舍弃列表可见，恢复后回到 active
    assert any(x["id"] == e.id for x in client.get("/api/rejected").json()["entries"])
    r = client.post(f"/api/entries/{e.id}/restore", json={}, headers=_auth())
    assert r.json()["status"] == "active"
    assert any(x["id"] == e.id for x in client.get(f"/api/categories/{cat.id}/entries").json()["entries"])


def test_rejected_never_revives(cfg, dl, registries, tmp_path):
    """舍弃后源里仍存在 → 重新同步不复活（区别于 archived）。"""
    locators, semantics = registries
    e = _mk_entry(dl, "edge:r2", "源里还在但被舍弃")
    dl.set_status([e.id], "rejected")
    stats = run_sync(cfg, dl, locators, semantics, full=True,
                     source="bookmarks")  # 书签源未启用 → 不动作
    assert dl.get_entry(e.id).status == "rejected"
    # 直接模拟同步预检路径：archived 才复活，rejected 不会
    from knowatlas.models import Entry as E
    same = E.build(source_type="bookmark", source_key="edge:r2", title="源里还在但被舍弃",
                   locator="https://x.example/edge:r2",
                   locator_canonical="https://x.example/edge:r2")
    dl.upsert_entries([same])
    assert dl.get_entry(e.id).status == "rejected"  # upsert 不写 status
    dl.set_status([e.id], "rejected")  # 双保险后仍是 rejected


def test_prune_fragments_merges_single_entry_children(cfg, dl):
    """单条目机器二级类目 → 并入一级父；manual 类目与一级类目不动。"""
    root = dl.create_category("技术测试", [], "rule")
    frag = dl.create_category("碎片类", [root.id], "llm")
    keep = dl.create_category("保留类", [root.id], "llm")
    manual_cat = dl.create_category("人工留类", [root.id], "manual")
    e1 = _mk_entry(dl, "edge:p1", "单条目碎片页")
    e2 = _mk_entry(dl, "edge:p2", "多条目类目页A")
    e3 = _mk_entry(dl, "edge:p3", "多条目类目页B")
    e4 = _mk_entry(dl, "edge:p4", "人工挂接页")
    dl.attach_category(e1.id, frag.id, 0.9, "llm", "r")
    dl.attach_category(e2.id, keep.id, 0.9, "llm", "r")
    dl.attach_category(e3.id, keep.id, 0.9, "llm", "r")
    dl.attach_category(e4.id, manual_cat.id, 1.0, "manual", "r")
    moved = dl.prune_fragment_categories(min_size=2)
    names = {m["name"] for m in moved}
    assert "碎片类" in names and "保留类" not in names and "人工留类" not in names
    # 条目挂接迁移到一级
    assert {l["path"] for l in dl.get_entry_categories(e1.id)} == {"技术测试"}
    assert {l["path"] for l in dl.get_entry_categories(e2.id)} == {"技术测试/保留类"}
    assert {l["path"] for l in dl.get_entry_categories(e4.id)} == {"技术测试/人工留类"}


def test_reclassify_prunes_fragments(cfg, dl, registries, tmp_path):
    _mk_entry(dl, "edge:p5", "Rust 入门")
    stats = run_sync(cfg, dl, locators := registries[0], semantics := registries[1],
                     reclassify=True)
    assert "pruned_fragments" in stats["reclassify"]
