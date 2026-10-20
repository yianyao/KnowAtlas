"""Web API 测试：分类管理、条目改分类、关系图数据（H5 守卫行为一并验证）。"""

from __future__ import annotations

import os

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


def test_token_hint_fingerprint(cfg, dl, registries):
    """令牌核对辅助：/api/token-hint 只回指纹不回明文；令牌不匹配的 403 消息带指纹。"""
    from fastapi.testclient import TestClient
    from knowatlas.web.app import create_app
    app = create_app(cfg, dl, *registries)
    c = TestClient(app, headers={"Host": f"127.0.0.1:{cfg.get('general.server_port', 8420)}"})
    tok = "unit-test-token"
    os.environ["KNOWATLAS_TEST_TOKEN"] = tok
    try:
        hint = c.get("/api/token-hint").json()
        assert hint["configured"] is True
        assert tok not in str(hint)                      # 明文绝不回传
        assert len(hint["fingerprint"]) == 8
        r = c.post("/api/entries/999999/reject", json={},
                   headers={"X-KnowAtlas-Token": "wrong-token"})
        assert r.status_code == 403
        assert hint["fingerprint"] in r.json()["error"]["message"]
    finally:
        os.environ.pop("KNOWATLAS_TEST_TOKEN", None)


def test_session_cookie_auto_auth(cfg, dl, registries):
    """同源自动写凭据：/api/session 种 HttpOnly+SameSite=Strict Cookie，带 cookie 的写操作
    通过守卫——用户零手工填令牌（浏览器自动携带）。"""
    from fastapi.testclient import TestClient
    from knowatlas.web.app import create_app
    tok = "unit-test-token-2"
    os.environ["KNOWATLAS_TEST_TOKEN"] = tok
    try:
        app = create_app(cfg, dl, *registries)
        c = TestClient(app, headers={"Host": f"127.0.0.1:{cfg.get('general.server_port', 8420)}"})
        r = c.get("/api/session")
        assert r.status_code == 200
        assert tok not in r.text                       # 明文不回传到 JS
        set_cookie = r.headers.get("set-cookie", "")
        assert "knowatlas_write=" in set_cookie
        assert "HttpOnly" in set_cookie and "SameSite=strict" in set_cookie.replace("Strict", "strict")
        # TestClient 自动带上刚种的 cookie：不带任何 header 也能通过写守卫
        w = c.post("/api/entries/999999/reject", json={})
        assert w.status_code == 404, w.text            # 过了守卫，只是条目不存在
    finally:
        os.environ.pop("KNOWATLAS_TEST_TOKEN", None)


def test_write_guard_rejects_bad_cookie(cfg, dl, registries):
    """错误 cookie 仍被拒（守卫不因 cookie 通道而放松）。"""
    from fastapi.testclient import TestClient
    from knowatlas.web.app import create_app
    os.environ["KNOWATLAS_TEST_TOKEN"] = "right-token"
    try:
        app = create_app(cfg, dl, *registries)
        c = TestClient(app, headers={"Host": f"127.0.0.1:{cfg.get('general.server_port', 8420)}"})
        c.cookies.set("knowatlas_write", "wrong-token")
        w = c.post("/api/entries/999999/reject", json={})
        assert w.status_code == 403
    finally:
        os.environ.pop("KNOWATLAS_TEST_TOKEN", None)


# ---- 关系图三视图端点（0.2.0 第二十二批） ----

def test_graph_view_endpoints(client, dl):
    from knowatlas.models import Entry
    es = [Entry.build(source_type="bookmark", source_key=f"edge:{i}",
                      title=f"搜索样本{i}", locator=f"https://gv.example/{i}",
                      locator_canonical=f"https://gv.example/{i}", native_path="书签栏")
          for i in range(2)]
    dl.upsert_entries(es)
    a = dl.create_category("图谱大类", [], "rule")
    b = dl.create_category("图谱子类", [a.id], "rule")
    dl.attach_category(es[0].id, a.id, 1.0, "prior", "r1")
    dl.attach_category(es[1].id, b.id, 1.0, "prior", "r1")

    ov = client.get("/api/graph/overview").json()
    root = next(n for n in ov["nodes"] if n["name"] == "图谱大类")
    assert root["kind"] == "category" and root["value"] == 2  # 子树 active 计数

    sub = client.get(f"/api/graph/subtree?category_id={a.id}").json()
    assert {n["name"] for n in sub["nodes"] if n["kind"] == "category"} >= {"图谱大类", "图谱子类"}
    assert client.get("/api/graph/subtree?category_id=nope").status_code == 404

    sr = client.get("/api/graph/search?q=搜索样本").json()
    assert {n["name"] for n in sr["nodes"] if n["kind"] == "entry"} == {"搜索样本0", "搜索样本1"}
    assert {n["name"] for n in sr["nodes"] if n["kind"] == "category"} >= {"图谱大类"}
    assert client.get("/api/graph/search?q=").json()["nodes"] == []


# ---- 双向联动②端点（0.2.0 第二十三批）：批量取条目分类挂接 ----

def test_entries_linkage_batch(client, dl):
    from knowatlas.models import Entry
    es = [Entry.build(source_type="bookmark", source_key=f"edge:lk{i}",
                      title=f"联动样本{i}", locator=f"https://lk.example/{i}",
                      locator_canonical=f"https://lk.example/{i}", native_path="书签栏")
          for i in range(2)]
    dl.upsert_entries(es)
    a = dl.create_category("联动大类", [], "rule")
    dl.attach_category(es[0].id, a.id, 1.0, "prior", "r1")
    r = client.get(f"/api/entries/linkage?ids={es[0].id},{es[1].id}").json()
    assert r["linkage"][es[0].id][0]["path"] == "联动大类"
    assert r["linkage"][es[1].id] == []  # 未挂接条目返回空列表而非缺键
    assert client.get("/api/entries/linkage?ids=").json() == {"linkage": {}}
    # "linkage" 不被 /api/entries/{entry_id} 路径参数吞掉（声明顺序保证）
    assert client.get("/api/entries/linkage").status_code == 200


# ---- 双向联动②端点（0.2.0 第二十三批）：批量取条目分类挂接 ----

def test_entries_linkage_batch(client, dl):
    from knowatlas.models import Entry
    es = [Entry.build(source_type="bookmark", source_key=f"edge:lk{i}",
                      title=f"联动样本{i}", locator=f"https://lk.example/{i}",
                      locator_canonical=f"https://lk.example/{i}", native_path="书签栏")
          for i in range(2)]
    dl.upsert_entries(es)
    a = dl.create_category("联动大类", [], "rule")
    dl.attach_category(es[0].id, a.id, 1.0, "prior", "r1")
    r = client.get(f"/api/entries/linkage?ids={es[0].id},{es[1].id}").json()
    assert r["linkage"][es[0].id][0]["path"] == "联动大类"
    assert r["linkage"][es[1].id] == []  # 未挂接条目返回空列表而非缺键
    assert client.get("/api/entries/linkage?ids=").json() == {"linkage": {}}
    # "linkage" 不被 /api/entries/{entry_id} 路径参数吞掉（声明顺序保证）
    assert client.get("/api/entries/linkage").status_code == 200
