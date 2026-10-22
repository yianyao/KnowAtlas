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
    """图数据：分类/条目节点 + 挂接边；同 host 不再聚合域名节点（用户裁决：域名不作关联项）。"""
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
    assert not any(n["kind"] == "domain" or n["id"].startswith("d:")
                   for n in data["nodes"])
    assert not any(l["kind"] == "same_host" for l in data["links"])
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

    # 层级模式（批次 63）：非叶子只出下一级子分类；叶子层条目自动出现
    hier = client.get(f"/api/graph/subtree?category_id={a.id}&hierarchy=true").json()
    assert {n["name"] for n in hier["nodes"]} == {"图谱大类", "图谱子类"}
    assert hier["links"] == [{"source": f"c:{a.id}", "target": f"c:{b.id}", "kind": "child"}]
    leaf = client.get(f"/api/graph/subtree?category_id={b.id}&hierarchy=1").json()
    assert {n["name"] for n in leaf["nodes"] if n["kind"] == "entry"} == {"搜索样本1"}

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
    assert client.get("/api/entries/linkage?ids=").json() == {"linkage": {}, "mind_paths": {}}
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
    assert client.get("/api/entries/linkage?ids=").json() == {"linkage": {}, "mind_paths": {}}
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
    """静态页探针（第三十七批立；第五十九批页签化改版）：六页签+管理集中+收录对话框。"""
    from knowatlas.web.app import _STATIC_DIR

    graph = (_STATIC_DIR / "graph.html").read_text(encoding="utf-8")
    assert "/^https?:/i.test(loc)" in graph       # 只有 http(s) 渲染「打开原文」链接
    assert "ccopy" in graph                       # file:// / emmx:// 走 locator+复制
    index = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # 六页签齐全（第五十九批）：检索 / 关系图 / 串联 / 词云 / 时间线 / 管理
    for v in ("search", "graph", "thread", "cloud", "timeline", "mgmt"):
        assert f'data-view="{v}"' in index
    # 检索默认显示，其余视图默认隐藏
    assert '<section id="view-search" class="view">' in index
    for v in ("graph", "thread", "cloud", "timeline", "mgmt"):
        assert f'<section id="view-{v}" class="view" hidden>' in index
    # 管理页集中七入口（第五十九批六入口 + 第六十四批勘误裁决：暂存/待清理/失效/时效/勘误/已舍弃/数据管理）
    for sub in ("staged", "nonk", "dead", "fresh", "errata", "rejected", "data"):
        assert f'data-sub="{sub}"' in index
    # 勘误三级 L3 探针（第六十四批，方案 §7.6）：附注并显 + 原文不改写说明在 UI
    assert "errata" in index and "原文永不改写" in index
    # 手动收录上移顶栏对话框（同 kadd 链路；说明悬停出）；日常消费页无管理控件
    assert 'id="ingest-dialog"' in index and 'id="add-url-btn"' in index
    assert "同 kadd" in index
    assert "/api/entries" in index                # 收录走 kadd 同一链路
    assert 'class="cid-btn"' in index             # 条目行复制 ID
    assert 'id="bm-dock"' in index                # bookmarklet 左缘小书签坞（收缩/hover 展开）
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


# ---- 源配置状态端点（第五十九批：管理页「数据管理」）----


def test_sources_status_readonly(client):
    """/api/sources 只报配置状态布尔，不回传任何路径/凭证明文。"""
    r = client.get("/api/sources")
    assert r.status_code == 200
    data = r.json()["sources"]
    names = {s["name"] for s in data}
    assert {"bookmarks", "folders", "emmx", "mail", "session", "manual"} <= names
    for s in data:
        assert set(s) == {"name", "label", "configured"}
        assert isinstance(s["configured"], bool)
    # conftest cfg 只配置了 sources.manual（必填项）
    manual = next(s for s in data if s["name"] == "manual")
    assert manual["configured"] is True
    assert "tmp" not in r.text and ".toml" not in r.text  # 无路径泄漏


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
    assert r2.json()["uncategorized"] == 1   # 精确 COUNT（本测试唯一条目未挂分类）

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


# ---- ③默认聚合呈现 + ④一键合并/拆开（批次 67）----

def test_entries_points_batch(client, dl):
    """③批量取条目挂的点：无点条目空列表、text 服务端截断、judge 透传。"""
    from knowatlas.models import Entry
    e = Entry.build(source_type="manual", source_key=f"pt67:{id(dl)}",
                    title="聚合样本", locator=f"https://pt67.example/{id(dl)}",
                    inline_content="FTS5 用 trigram。" * 10,
                    meta={"source_type": "manual"})
    dl.upsert_entries([e])
    import uuid
    dl.put_point({"content_hash": "h67" + uuid.uuid4().hex[:12],
                  "text": "点" * 600, "summary": "一点",
                  "source_type": "manual", "judge": "integral",
                  "meta": {"judge_reason": "方案整条即点"}},
                 {"entry_id": e.id, "char_offset": 0, "anchor": "点"})
    r = client.get(f"/api/entries/points?ids={e.id}").json()
    pts = r["points"][e.id]
    assert len(pts) == 1
    assert pts[0]["summary"] == "一点" and pts[0]["judge"] == "integral"
    assert pts[0]["text_len"] == 600 and pts[0]["text"].endswith("…[截断]")  # 500 cap
    # 无点条目 → 空列表；空 ids → 空对象
    e2 = Entry.build(source_type="manual", source_key=f"pt67b:{id(dl)}",
                     title="无点样本", locator=f"https://pt67b.example/{id(dl)}",
                     inline_content="无点正文。", meta={"source_type": "manual"})
    dl.upsert_entries([e2])
    r2 = client.get(f"/api/entries/points?ids={e2.id}").json()
    assert r2["points"][e2.id] == []
    assert client.get("/api/entries/points?ids=").json() == {"points": {}}
    # "points" 不被 /api/entries/{entry_id} 路径参数吞掉（声明顺序保证）
    assert client.get("/api/entries/points").status_code == 200


def test_emmx_rejudge_validation(client):
    """④人工裁决参数校验：form 非法 400、缺 rel 400、文件不存在 404（不写库）。"""
    h = _auth()
    assert client.post("/api/sources/emmx/rejudge", json={"rel": "x.emmx", "form": "maybe"},
                       headers=h).status_code == 400
    assert client.post("/api/sources/emmx/rejudge", json={"rel": "", "form": "integral"},
                       headers=h).status_code == 400
    r = client.post("/api/sources/emmx/rejudge",
                    json={"rel": "不存在.emmx", "form": "integral"}, headers=h)
    assert r.status_code == 404
    # 无 token → 写守卫拦截（403）
    assert client.post("/api/sources/emmx/rejudge",
                       json={"rel": "x.emmx", "form": "integral"},
                       headers={}).status_code == 403


def test_bulk_status_and_pending_queue(client, dl):
    """批次 68：批量流转（activate/reject）+ 待审队列——审查闭环。"""
    from knowatlas.models import Entry
    import uuid
    batch = uuid.uuid4().hex[:6]
    es = []
    for i in range(3):
        e = Entry.build(source_type="manual", source_key=f"b68:{batch}:{i}",
                        title=f"待审{i}", locator=f"https://b68.example/{batch}/{i}",
                        inline_content="待审正文。", meta={"source_type": "manual"})
        dl.upsert_entries([e])
        dl.set_status([e.id], "pending")
        es.append(e)
    ids = [e.id for e in es]
    # 待审队列列出
    r = client.get("/api/pending").json()
    pend = [x for x in r["entries"] if x["id"] in ids]
    assert len(pend) == 3
    # 批量转正 2 条
    r1 = client.post("/api/entries/bulk-status",
                     json={"ids": ids[:2], "action": "activate"}, headers=_auth()).json()
    assert len(r1["done"]) == 2 and r1["status"] == "active"
    assert dl.get_entry(ids[0]).status == "active"
    # 批量舍弃 1 条（带冷却起点）
    r2 = client.post("/api/entries/bulk-status",
                     json={"ids": [ids[2]], "action": "reject"}, headers=_auth()).json()
    assert len(r2["done"]) == 1 and r2["cooling_days"] == 30
    rej = dl.get_entry(ids[2])
    assert rej.status == "rejected" and rej.meta.get("rejected_at")
    # 参数校验：非法 action / 空 ids / 无 token
    assert client.post("/api/entries/bulk-status", json={"ids": ids, "action": "x"},
                       headers=_auth()).status_code == 400
    assert client.post("/api/entries/bulk-status", json={"ids": [], "action": "activate"},
                       headers=_auth()).status_code == 400
    assert client.post("/api/entries/bulk-status", json={"ids": ids, "action": "activate"},
                       headers={}).status_code == 403
    # missing 列出（含不存在 id）
    r3 = client.post("/api/entries/bulk-status",
                     json={"ids": [ids[0], "ghost"], "action": "activate"},
                     headers=_auth()).json()
    assert r3["missing"] == ["ghost"]


def test_entry_form_override(client, dl):
    """批次 70：条目级形态覆盖——写 meta.force_form + 清点溯源 + 即时重抽。"""
    from knowatlas.models import Entry
    import uuid
    batch = uuid.uuid4().hex[:6]
    e = Entry.build(source_type="folder", source_key=f"f70:{batch}",
                    title="覆盖测试文档", locator=f"file:///{batch}/doc.txt",
                    inline_content="一套完整的排查方案，" + "细节 " * 60,
                    meta={"source_type": "folder"})
    dl.upsert_entries([e])
    em = Entry.build(source_type="emmx", source_key=f"e70:{batch}#map",
                     title="脑图", locator=f"emmx://图{batch}.emmx#map",
                     meta={"source_type": "emmx"})
    dl.upsert_entries([em])
    # 合（integral）：整条一点，零 LLM（测试 cfg 无 [llm] 也必须成功）
    r1 = client.post(f"/api/entries/{e.id}/form", json={"form": "integral"},
                     headers=_auth()).json()
    assert r1["points_created"] == 1 and r1["errors"] == []
    assert dl.get_entry(e.id).meta.get("force_form") == "integral"
    assert dl.count_points() == 1
    # 拆（split）：无 LLM → 覆盖已写但重抽记 error（不静默）
    r2 = client.post(f"/api/entries/{e.id}/form", json={"form": "split"},
                     headers=_auth()).json()
    assert r2["purged_sources"] == 1
    assert dl.get_entry(e.id).meta.get("force_form") == "split"
    assert len(r2["errors"]) == 1 and "llm 未启用" in r2["errors"][0]["error"]
    assert dl.count_points() == 0
    # 回归（auto）：清覆盖
    r3 = client.post(f"/api/entries/{e.id}/form", json={"form": "auto"},
                     headers=_auth()).json()
    assert "force_form" not in dl.get_entry(e.id).meta
    assert r3["points_created"] == 1 and dl.count_points() == 1   # 回归 integral 规则
    # 边界：非法 form 400 / emmx 拒绝 400 / 不存在 404 / 无 token 403
    assert client.post(f"/api/entries/{e.id}/form", json={"form": "x"},
                       headers=_auth()).status_code == 400
    assert client.post(f"/api/entries/{em.id}/form", json={"form": "split"},
                       headers=_auth()).status_code == 400
    assert client.post("/api/entries/ghost0000000/form", json={"form": "split"},
                       headers=_auth()).status_code == 404
    assert client.post(f"/api/entries/{e.id}/form", json={"form": "integral"},
                       headers={}).status_code == 403


def test_linkage_mind_paths(client, dl):
    """批次 68：linkage 扩展 mind_paths——emmx 节点条目带脑图内路径，其余无键。"""
    from knowatlas.models import Entry
    import uuid
    batch = uuid.uuid4().hex[:6]
    m = Entry.build(source_type="emmx", source_key=f"mp:{batch}#page/108",
                    title="供应商管理", locator=f"emmx://图{batch}.emmx#page/108",
                    native_path="脑图库",
                    meta={"source_type": "emmx", "mind_path": "PECOS进度/采购/供应商管理"})
    o = Entry.build(source_type="manual", source_key=f"mpo:{batch}",
                    title="普通条目", locator=f"https://mp.example/{batch}",
                    inline_content="x", meta={"source_type": "manual"})
    dl.upsert_entries([m, o])
    r = client.get(f"/api/entries/linkage?ids={m.id},{o.id}").json()
    assert r["mind_paths"][m.id] == "PECOS进度/采购/供应商管理"
    assert o.id not in r["mind_paths"]
    assert client.get("/api/entries/linkage?ids=").json() == {"linkage": {}, "mind_paths": {}}
