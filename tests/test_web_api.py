"""Web API 测试：分类管理、条目改分类、关系图数据（H5 守卫行为一并验证）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knowatlas.web.app import create_app


@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    # conftest 的 cfg 指向 KNOWATLAS_TEST_TOKEN；按 cfg 实际 token_env 设置
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")), "test-token-123")
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    # H5 Host 白名单：TestClient 默认 host=testserver 会被拦截，显式指定
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def _auth():
    return {"X-KnowAtlas-Token": "test-token-123", "Origin": "http://127.0.0.1:8420"}


def test_category_crud_flow(client):
    r = client.post("/api/categories", json={"name": "临时类"}, headers=_auth())
    assert r.status_code == 200
    cid = r.json()["id"]
    assert client.post("/api/categories", json={"name": "临时类"}, headers={}).status_code == 403
    r = client.post(f"/api/categories/{cid}/rename", json={"name": "临时类改名"}, headers=_auth())
    assert r.status_code == 200 and r.json()["name"] == "临时类改名"
    target = client.post("/api/categories", json={"name": "落点类"}, headers=_auth()).json()["id"]
    r = client.post(f"/api/categories/{cid}/merge", json={"target_id": target}, headers=_auth())
    assert r.status_code == 200
    names = [n["name"] for n in client.get("/api/tree").json()["tree"]]
    assert "临时类改名" not in names and "落点类" in names


def test_recategorize_manual_overrides_machine(client, dl):
    """人工校正：manual 挂接 + 机器旧分类摘除；再次同步/校正不覆盖 manual。"""
    cid_new = client.post("/api/categories", json={"name": "软件特别类"}, headers=_auth()).json()["id"]
    cat = dl.get_category(cid_new)
    # 直接在数据层造一条目 + 机器分类挂接
    from knowatlas.models import Entry
    e = Entry.build(source_type="bookmark", source_key="edge:9999", title="某页",
                    locator="https://recat.example/a", locator_canonical="https://recat.example/a",
                    native_path="书签栏/某处")
    dl.upsert_entries([e])
    dl.attach_category(e.id, cid_new, 0.8, "rule", "r1")
    r = client.post(f"/api/entries/{e.id}/recategorize",
                    json={"target_path": "人工校正/待读"}, headers=_auth())
    assert r.status_code == 200
    links = dl.get_entry_categories(e.id)
    assert {l["path"] for l in links} == {"人工校正/待读"}
    assert all(l["origin"] == "manual" for l in links)
    # 再校正到另一分类：manual 也可被人工更新（人工→人工允许）
    r = client.post(f"/api/entries/{e.id}/recategorize",
                    json={"target_path": "人工校正/已读"}, headers=_auth())
    assert r.status_code == 200
    assert {l["path"] for l in dl.get_entry_categories(e.id)} == {"人工校正/已读"}


def test_graph_data_shape(client, dl):
    """图数据：分类/条目/域名三类节点；同 host 多条目出域名节点与 same_host 边。"""
    from knowatlas.models import Entry
    entries = [
        Entry.build(source_type="bookmark", source_key=f"edge:{i}", title=f"页{i}",
                    locator=f"https://same.example/{i}", locator_canonical=f"https://same.example/{i}",
                    native_path="书签栏")
        for i in range(3)
    ]
    dl.upsert_entries(entries)
    cat = dl.create_category("图分类", [], "rule")
    for e in entries:
        dl.attach_category(e.id, cat.id, 1.0, "prior", "r1")
    data = client.get("/api/graph").json()
    kinds = {n["kind"] for n in data["nodes"]}
    assert {"entry", "category"} <= kinds
    assert any(n["kind"] == "domain" and n["name"] == "same.example" for n in data["nodes"])
    assert any(l["kind"] == "same_host" for l in data["links"])
    assert any(l["kind"] == "prior" for l in data["links"])


def test_recategorize_requires_token(client, dl):
    from knowatlas.models import Entry
    e = Entry.build(source_type="bookmark", source_key="edge:777", title="t",
                    locator="https://x.example/z", locator_canonical="https://x.example/z")
    dl.upsert_entries([e])
    r = client.post(f"/api/entries/{e.id}/recategorize", json={"target_path": "a/b"})
    assert r.status_code == 403
