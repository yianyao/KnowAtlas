"""人工校正扩展（0.2.0 第五十二批）：多父挂接 / 批量改类 / 复现性。

单条 recategorize 基础语义（替换、task_log 前后值）已有测试背书
（test_web_api），本文件只覆盖第五十二批增量：keep_existing 追加语义、
batch-recategorize 端点、DAG 多父真实共存。
"""

from __future__ import annotations

import pytest


def _mk_entry(dl, key: str, title: str):
    from knowatlas.models import Entry
    return dl.upsert_entries([Entry.build(
        source_type="manual", source_key=key, title=title,
        locator=f"https://x.com/{key}", locator_canonical=f"https://x.com/{key}",
        meta={})]).ids[0]


@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    from fastapi.testclient import TestClient

    from knowatlas.web.app import create_app
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")), "test-token-123")
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def _auth():
    return {"X-KnowAtlas-Token": "test-token-123", "Origin": "http://127.0.0.1:8420"}


def test_keep_existing_adds_parent(dl, client):
    """多父挂接：keep_existing=true 旧挂接保留、新挂接共存（DAG 多父）。"""
    e = _mk_entry(dl, "p1", "多父样本")
    dev = dl.create_category("技术开发", [], "manual")
    dl.attach_category(e, dev.id, 1.0, "manual", "t")

    r = client.post(f"/api/entries/{e}/recategorize",
                    json={"target_path": "人工智能/方法论", "keep_existing": True},
                    headers=_auth())
    assert r.status_code == 200
    paths = {l["path"]: l["origin"] for l in dl.get_entry_categories(e)}
    assert paths == {"技术开发": "manual", "人工智能/方法论": "manual"}  # 两父共存
    # task_log 记 keep_existing（复现性：改类动作可追溯含模式）
    log = [t for t in dl.get_task_log() if t["action"] == "recategorize"][0]
    assert log["detail"]["keep_existing"] is True
    assert "技术开发" in log["detail"]["old_paths"]


def test_default_replace_strips_old(dl, client):
    """默认（keep_existing=false）保持替换语义：旧挂接全摘除。"""
    e = _mk_entry(dl, "p2", "替换样本")
    dev = dl.create_category("技术开发", [], "manual")
    dl.attach_category(e, dev.id, 0.9, "rule", "t")

    r = client.post(f"/api/entries/{e}/recategorize",
                    json={"target_path": "人工智能"}, headers=_auth())
    assert r.status_code == 200
    paths = [l["path"] for l in dl.get_entry_categories(e)]
    assert paths == ["人工智能"]


def test_batch_recategorize(dl, client):
    """批量：逐条 task_log（同 batch_id 串联）+ not_found 跳过 + 去重保序。"""
    e1 = _mk_entry(dl, "b1", "批一")
    e2 = _mk_entry(dl, "b2", "批二")
    r = client.post("/api/entries/batch-recategorize",
                    json={"entry_ids": [e1, e2, "ghost-id", e1],  # 幽灵 + 重复
                          "target_path": "技术开发/前端"},
                    headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert data["done"] == [e1, e2]                 # 去重保序，幽灵跳过
    assert data["skipped"] == [{"entry_id": "ghost-id", "reason": "not_found"}]
    assert data["category_path"] == "技术开发/前端"
    for eid in (e1, e2):
        assert [l["path"] for l in dl.get_entry_categories(eid)] == ["技术开发/前端"]
    # 复现性：每条独立 task_log，batch_id 串联，old_paths 记前值
    logs = [t for t in dl.get_task_log() if t["action"] == "batch_recategorize"]
    assert len(logs) == 2
    assert len({t["detail"]["batch_id"] for t in logs}) == 1
    assert {t["target"] for t in logs} == {e1, e2}


def test_batch_keep_existing(dl, client):
    """批量多父：keep_existing=true 每条保留原挂接。"""
    e1 = _mk_entry(dl, "bk1", "批多父一")
    dev = dl.create_category("技术开发", [], "manual")
    dl.attach_category(e1, dev.id, 1.0, "manual", "t")
    r = client.post("/api/entries/batch-recategorize",
                    json={"entry_ids": [e1], "target_path": "人工智能",
                          "keep_existing": True},
                    headers=_auth())
    assert r.status_code == 200
    assert {l["path"] for l in dl.get_entry_categories(e1)} == {"技术开发", "人工智能"}


def test_batch_validation(dl, client):
    """空 entry_ids / 缺 target_path → 400；无 token → 403。"""
    assert client.post("/api/entries/batch-recategorize",
                       json={"entry_ids": [], "target_path": "x"},
                       headers=_auth()).status_code == 400
    assert client.post("/api/entries/batch-recategorize",
                       json={"entry_ids": ["a"]},
                       headers=_auth()).status_code == 400
    assert client.post("/api/entries/batch-recategorize",
                       json={"entry_ids": ["a"], "target_path": "x"}).status_code == 403
