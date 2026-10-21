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


def test_entry_summary_endpoint(client, dl):
    """关系图弹窗卡概要：轻端点截断 snippet（160，第三十七批）、无正文空串、404、免令牌。"""
    from knowatlas.models import Entry, FetchResult
    e = Entry.build(source_type="manual", source_key="sum1", title="概要条目",
                    locator="https://x.example/a", locator_canonical="https://x.example/a",
                    content_hash="hash-sum-001")
    dl.upsert_entries([e])
    dl.put_content(FetchResult(text="第一段  摘要正文\n第二段 " + "长" * 500,
                               content_hash="hash-sum-001",
                               fetcher="test", fetched_at="2026-10-20T00:00:00+08:00"))
    r = client.get(f"/api/entries/{e.id}/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "概要条目"
    assert len(body["snippet"]) == 160 and "  " not in body["snippet"]  # 截断+空白归一
    assert body["snippet"].startswith("第一段 摘要正文 第二段")
    assert body["locator"] == "https://x.example/a"
    # 无正文条目 → 空串而非报错
    e2 = Entry.build(source_type="manual", source_key="sum2", title="无正文",
                     locator="https://x.example/b", locator_canonical="https://x.example/b")
    dl.upsert_entries([e2])
    assert client.get(f"/api/entries/{e2.id}/summary").json()["snippet"] == ""
    assert client.get("/api/entries/nope1234567890ab/summary").status_code == 404


def test_static_pages_consumption_defaults():
    """静态页探针（第三十七批）：弹窗卡仅 http(s) 出「打开原文」；管理入口默认折叠。"""
    from knowatlas.web.app import _STATIC_DIR

    graph = (_STATIC_DIR / "graph.html").read_text(encoding="utf-8")
    assert "/^https?:/i.test(loc)" in graph       # 只有 http(s) 渲染「打开原文」链接
    assert "ccopy" in graph                       # file:// / emmx:// 走 locator+复制
    index = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert '<details id="mgmt"' in index          # 管理分组存在
    assert 'details id="mgmt" open' not in index  # 且默认收起（消费页优先）
    # 五个数据管理入口都在 details 块内（第四十二批起 add-url 手动收录也在其中）
    for eid in ("add-url", "staged-btn", "rejected-link", "dead-link", "nonk-link",
                "fresh-link"):
        assert index.index('<details id="mgmt"') < index.index(f'id="{eid}"')
    # 第四十二批：手动收录入口 + 复制条目 ID 统一注入（弹窗卡同款能力）
    assert 'id="add-url-btn"' in index
    assert "/api/entries" in index                # 收录走 kadd 同一链路
    assert 'class="cid-btn"' in index             # 条目行复制 ID
    assert "ccid" in graph                        # 弹窗卡 ID 行（点击复制）


def test_manual_ingest_endpoint_idempotent(client):
    """手动收录端点（第四十二批 UI 入口走同一链路）：抓正文入库；重复收录幂等 duplicate。"""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802  stdlib 命名
            body = ("<h1>手动收录探针页</h1>"
                    + "<p>统一消息总线的路由与过滤实践，手动收录链路验证正文。" * 10).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # 静默
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/probe.html"
        r1 = client.post("/api/entries", json={"url": url}, headers=_auth())
        assert r1.status_code == 200
        j1 = r1.json()
        assert j1["status"] == "created" and j1["fetched"] is True
        assert len(j1["entry_id"]) == 16
        r2 = client.post("/api/entries", json={"url": url}, headers=_auth())
        assert r2.status_code == 200 and r2.json()["status"] == "duplicate"
        assert r2.json()["entry_id"] == j1["entry_id"]
        # 缺 url → 400
        assert client.post("/api/entries", json={}, headers=_auth()).status_code == 400
    finally:
        srv.shutdown()


def test_manual_ingest_endpoint_idempotent(client):
    """手动收录端点（第四十二批 UI 入口走同一链路）：抓正文入库；重复收录幂等 duplicate。"""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802  stdlib 命名
            body = ("<h1>手动收录探针页</h1>"
                    + "<p>统一消息总线的路由与过滤实践，手动收录链路验证正文。" * 10).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # 静默
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/probe.html"
        r1 = client.post("/api/entries", json={"url": url}, headers=_auth())
        assert r1.status_code == 200
        j1 = r1.json()
        assert j1["status"] == "created" and j1["fetched"] is True
        assert len(j1["entry_id"]) == 16
        r2 = client.post("/api/entries", json={"url": url}, headers=_auth())
        assert r2.status_code == 200 and r2.json()["status"] == "duplicate"
        assert r2.json()["entry_id"] == j1["entry_id"]
        # 缺 url → 400
        assert client.post("/api/entries", json={}, headers=_auth()).status_code == 400
    finally:
        srv.shutdown()


# ---- MCP 只读端点（第四十六批）----


def test_mcp_endpoints_readonly(client, dl):
    """MCP 三端点：search/tree/entry 只读查询 + 404。"""
    from knowatlas.models import Entry

    dl.upsert_entries([Entry.build(
        source_type="bookmark", source_key="https://mcp.test/1",
        title="消息总线入门", locator="https://mcp.test/1",
        locator_canonical="https://mcp.test/1",
        inline_content="路由与过滤实践要点。", meta={"source_type": "bookmark"})])
    eid = dl.list_entries(limit=10)[0].id

    r = client.get("/api/mcp/search", params={"q": "消息总线"})
    assert r.status_code == 200
    j = r.json()
    assert j["count"] >= 1 and j["hits"][0]["entry_id"] == eid
    assert j["hits"][0]["title"] == "消息总线入门"

    r2 = client.get("/api/mcp/tree")
    assert r2.status_code == 200 and "tree" in r2.json()

    r3 = client.get(f"/api/mcp/entry/{eid}")
    assert r3.status_code == 200
    j3 = r3.json()
    assert j3["id"] == eid and j3["title"] == "消息总线入门"
    assert "路由与过滤" in j3["content"]
    assert j3["category_ids"] == []           # 未挂分类

    assert client.get("/api/mcp/entry/0123456789abcdef").status_code == 404


def test_mcp_handlers_ast_readonly():
    """探针⑤：AST 级只读校验——三个 MCP handler 无任何写操作。

    黑名单：DataLayer/管道层的写方法 + 裸 _conn.execute 非 SELECT。
    （v0 REST 只读投影的硬约束，供 agent 安全调用。）
    """
    import ast
    from pathlib import Path

    src = Path("src/knowatlas/web/api.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    handlers = {}
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in ("mcp_search", "mcp_tree", "mcp_entry")):
            handlers[node.name] = node
    assert set(handlers) == {"mcp_search", "mcp_tree", "mcp_entry"}

    write_methods = {
        "put_entry", "put_content", "upsert_entries", "upsert_conv_messages",
        "delete", "merge_meta", "set_status", "attach_category", "detach_category",
        "create_category", "rename_category", "move_category", "attach_parent",
        "create_thread", "add_thread_item", "remove_thread_item", "set_conv_thread",
        "log_task", "start_run", "finish_run", "vacuum_into", "transaction",
    }
    for name, fn in handlers.items():
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                # dl.<写方法>(...) / self.dl.<写方法>(...)
                func = sub.func
                if isinstance(func, ast.Attribute) and func.attr in write_methods:
                    raise AssertionError(f"{name} 调用了写方法 {func.attr}")
                # 裸 _conn.execute(...)（只读端点不该摸私有连接）
                if (isinstance(func, ast.Attribute) and func.attr == "execute"
                        and isinstance(func.value, ast.Attribute)
                        and func.value.attr == "_conn"):
                    raise AssertionError(f"{name} 摸了私有 _conn")
                # SQL 字面量非 SELECT（如 conn.execute("INSERT ...")）
                if (isinstance(func, ast.Attribute) and func.attr == "execute"
                        and sub.args and isinstance(sub.args[0], ast.Constant)
                        and isinstance(sub.args[0].value, str)
                        and not sub.args[0].value.lstrip().upper().startswith("SELECT")
                        and "PRAGMA" not in sub.args[0].value.upper()):
                    raise AssertionError(f"{name} 执行了非 SELECT SQL")
