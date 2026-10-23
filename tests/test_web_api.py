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
    """静态页探针（第三十七批立；第五十九批页签化改版；第七十五批三栏+浮层套件）。"""
    import re

    from knowatlas.web.app import _STATIC_DIR

    graph = (_STATIC_DIR / "graph.html").read_text(encoding="utf-8")
    assert "/^https?:/i.test(loc)" in graph       # 只有 http(s) 渲染「打开原文」链接
    assert "ccopy" in graph                       # file:// / emmx:// 走 locator+复制
    index = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # 六页签齐全（第五十九批）：检索 / 关系图 / 串联 / 词云 / 时间线 / 管理
    for v in ("search", "graph", "thread", "cloud", "timeline", "mgmt"):
        assert f'data-view="{v}"' in index
    # 检索默认显示，其余视图默认隐藏
    assert '<section id="view-search" class="view view-split">' in index   # 第七十五批：三栏
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
    # 桌面壳（第七十四批）：令牌/组件外链 + 拖拽区 + 窗口控制 + 状态栏 + 树折叠
    assert "/tokens.css" in index and "/components.css" in index
    assert "pywebview-drag-region" in index       # 标题栏拖拽区（pywebview 官方 drag region）
    assert 'id="win-ctrls"' in index and 'id="wc-min"' in index
    assert 'class="shell-status"' in index and 'id="st-text"' in index
    assert 'id="side-collapse"' in index          # 分类树折叠键（树面板头部）
    assert 'knowatlas-side") === "hide"' in index  # 桌面壳默认展开，显式收起才折叠
    thread = (_STATIC_DIR / "thread.html").read_text(encoding="utf-8")
    assert "color-scheme: dark" in graph and "color-scheme: dark" in thread
    # 关系图令牌化（第七十六批）：tokens 外链 + 画布调色板走运行时取色，旧硬编码清零
    assert '<link rel="stylesheet" href="/tokens.css">' in graph
    assert 'tok("--accent"' in graph and "PAL.focus" in graph   # 画布色从令牌变量读真值
    assert "backgroundColor: PAL.tipBg" in graph                # 边 tooltip 深色化
    for legacy in ("#4a9eff", "#ffd04b", "#33506b", "#7ba7d7", "#8886"):
        assert legacy not in graph, legacy                      # 旧硬编码色零残留
    # 检索视图三栏 + 预览常驻 + 命令面板 + 拖拽调宽（第七十五批）
    assert 'id="search-col"' in index and 'id="side-split"' in index
    assert 'id="pv-split"' in index and 'id="preview-panel"' in index
    assert 'id="pv-restore"' in index and 'id="pv-empty"' in index
    assert 'id="resize-mask"' in index               # 拖拽期全屏掩体（防 iframe 吞事件）
    assert 'id="cmdk"' in index and 'id="cmdk-input"' in index
    assert '"knowatlas-pv-w"' in index and '"knowatlas-side-w"' in index  # 宽度偏好持久化
    assert '"k" || e.key === "K"' in index           # Ctrl/Cmd+K 命令面板快捷键
    # 浮层套件：三页均引 ui.js/ui.css，原生弹窗全量替换为零残留
    # （WebView2 下原生 prompt/alert/confirm 是 Chromium 浅色对话框，与深色壳断裂）
    for f in ("index.html", "graph.html", "thread.html"):
        t = (_STATIC_DIR / f).read_text(encoding="utf-8")
        assert "/ui.js" in t and "/ui.css" in t
        assert not re.search(r"(?<![a-zA-Z._])(confirm|alert|prompt)\(", t), f
        assert "ka.toast" in t                       # 轻提示通道已接入
    assert "ka.confirm" in index and "ka.prompt" in index
    # 线索库令牌化（第七十七批）：tokens 外链 + 硬编码色/Canvas 系统色清零
    assert '<link rel="stylesheet" href="/tokens.css">' in thread
    for legacy in ("#4a9eff", "#888", "Canvas", "#ff4a4a"):
        assert legacy not in thread, legacy
    # 词云/时间线令牌化（第七十七批）：后端词色经界面层深色映射，时间线轴/柱走令牌
    assert "CLOUD_DARK_MAP" in index and "cloudDark(w.color)" in index
    assert 'tok("--accent"' in index                 # 时间线柱色运行时取令牌
    assert '{ color: "#3f6fb5" }' not in index       # 时间线旧柱色硬编码用法清零
    #                                                （#3f6fb5 作为映射表键保留属预期）
    # 收尾令牌化（第七十八批）：JS 模板内联色清零 + 树操作/书签坞/多选条覆盖块
    assert 'color:var(--accent-text)" class="add-id"' in index
    assert "border-left:3px solid var(--warning)" in index   # 勘误附注金条改令牌
    # 内联 <style> 旧文本按覆盖策略保留（components.css 后加载胜出），只禁用法回潮
    assert "border-left:3px solid #c9a227" not in index
    assert 'style="font-size:12px;color:#888' not in index   # HTML 内联属性不走覆盖
    comps = (_STATIC_DIR / "components.css").read_text(encoding="utf-8")
    for probe in (".ops button", ".cat-chip", ".mind-path", "#bm-tab",
                  "#bulk-bar button.primary", "@keyframes catflash",
                  "rgba(91, 141, 239, 0.33)"):
        assert probe in comps, probe
    # 第八十一批：display:flex 作者样式会压过 UA 的 [hidden]{display:none}，
    # 检索视图切走后仍叠在其他视图上（真机验收实测）——同特异性反制规则必须存在
    assert "#view-search.view-split[hidden]" in comps


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


def test_rename_preview_and_merge(client, dl):
    """批次 71：改名（display_name 覆盖层）+ 预览 + 合并（locator/点/分类归主）。"""
    from knowatlas.models import Entry
    import uuid
    batch = uuid.uuid4().hex[:6]
    # 主条目（有点 + 分类挂接）+ 被并条目（不同 locator）
    main = Entry.build(source_type="manual", source_key=f"m71:{batch}",
                       title="原主条目", locator=f"https://m71.example/{batch}/main",
                       inline_content="主条目正文，预览应显示。",
                       meta={"source_type": "manual"})
    sub = Entry.build(source_type="bookmark", source_key=f"s71:{batch}",
                      title="被并书签", locator=f"https://s71.example/{batch}/sub",
                      inline_content="被并正文。", meta={"source_type": "bookmark"})
    dl.upsert_entries([main, sub])
    from knowatlas.models import FetchResult
    fr = FetchResult(text="主条目正文，预览应显示。", content_hash="h71pv" + batch,
                     fetcher="test", fetched_at="2026-10-22T00:00:00+08:00")
    dl.put_content(fr)  # 正文块落库 → preview 可取
    dl._conn.execute("UPDATE entries SET content_hash=? WHERE id=?",
                     (fr.content_hash, main.id))
    dl._conn.commit()
    dl.put_point({"content_hash": "h71" + batch, "text": "点" * 50,
                  "summary": "主点", "source_type": "manual", "judge": "integral",
                  "meta": {"judge_reason": "测试"}},
                 {"entry_id": sub.id, "char_offset": 0, "anchor": "点"})  # 点挂在被并条目上
    # 改名：写覆盖层 → get_entry 标题即新名（_row_to_entry 统一应用）
    r = client.post(f"/api/entries/{sub.id}/rename",
                    json={"name": "知识化短名"}, headers=_auth()).json()
    assert r["name"] == "知识化短名"
    assert dl.get_entry(sub.id).title == "知识化短名"
    # 覆盖层写进 meta；entries.title 原值仍在（重同步冲不回）
    assert dl.get_entry(sub.id).meta["display_name"] == "知识化短名"
    # 空名=清除覆盖回归源标题
    client.post(f"/api/entries/{sub.id}/rename", json={"name": ""}, headers=_auth())
    assert dl.get_entry(sub.id).title == "被并书签"
    # 120 字上限 400；404；403
    assert client.post(f"/api/entries/{sub.id}/rename", json={"name": "x" * 121},
                       headers=_auth()).status_code == 400
    assert client.post("/api/entries/ghost/rename", json={"name": "x"},
                       headers=_auth()).status_code == 404
    assert client.post(f"/api/entries/{sub.id}/rename", json={"name": "x"},
                       headers={}).status_code == 403
    # 合并：sub 并入 main → locator 挂接 + 点溯源转移 + sub 舍弃带冷却
    r2 = client.post("/api/entries/merge",
                     json={"primary_id": main.id, "merge_ids": [sub.id]},
                     headers=_auth()).json()
    assert r2["merged"] == 1 and r2["points_moved"] >= 1
    assert dl.get_entry(sub.id).status == "rejected"
    assert dl.get_entry(sub.id).meta.get("merged_into") == main.id
    locs = {r["locator"] for r in dl._conn.execute(
        "SELECT locator FROM entry_locators WHERE entry_id=?", (main.id,)).fetchall()}
    assert f"https://s71.example/{batch}/sub" in locs  # 被并 locator 挂主条目
    moved = dl._conn.execute(
        "SELECT ps.entry_id FROM point_sources ps JOIN points p ON p.id=ps.point_id"
        " WHERE p.summary='主点'").fetchone()["entry_id"]
    assert moved == main.id  # 点溯源随并转移（点不丢）
    # 预览：display_name/正文/分类/来源计数
    r3 = client.get(f"/api/entries/{main.id}/preview").json()
    assert r3["title"] == "原主条目" and "主条目正文" in r3["body"]
    assert len(r3["extra_locators"]) >= 1 and r3["source_type"] == "manual"
    # 参数校验：缺 primary 400 / 主在列表 400 / 主不存在 400 / 无 token 403
    assert client.post("/api/entries/merge", json={"merge_ids": [sub.id]},
                       headers=_auth()).status_code == 400
    assert client.post("/api/entries/merge",
                       json={"primary_id": main.id, "merge_ids": [main.id]},
                       headers=_auth()).status_code == 400
    assert client.post("/api/entries/merge",
                       json={"primary_id": "ghost", "merge_ids": [sub.id]},
                       headers=_auth()).status_code == 400
    assert client.post("/api/entries/merge",
                       json={"primary_id": main.id, "merge_ids": [sub.id]},
                       headers={}).status_code == 403


def test_auto_name_degrades_and_skips(client, dl, monkeypatch):
    """批次 71：AI 起名——已有名跳过/无正文降级剪尾/LLM 缺失不炸。"""
    from knowatlas.models import Entry
    import uuid
    batch = uuid.uuid4().hex[:6]
    e1 = Entry.build(source_type="bookmark", source_key=f"an71a:{batch}",
                     title="以MVP思维，解析最小可行的进销存产品 | 人人都是产品经理",
                     locator=f"https://an71.example/{batch}/a",
                     meta={"source_type": "bookmark"})  # 无正文 → 降级剪尾
    e2 = Entry.build(source_type="bookmark", source_key=f"an71b:{batch}",
                     title="已有名书签", locator=f"https://an71.example/{batch}/b",
                     meta={"source_type": "bookmark", "display_name": "已命名"})
    dl.upsert_entries([e1, e2])
    r = client.post("/api/entries/auto-name",
                    json={"ids": [e1.id, e2.id]}, headers=_auth()).json()
    assert r["count"] == 1 and r["skipped"][0]["id"] == e2.id
    d1 = r["degraded"][0]
    assert d1["name"] == "以MVP思维，解析最小可行的进销存产品"  # 尾巴剪净
    assert dl.get_entry(e1.id).meta["display_name"] == d1["name"]
    # 空 ids 400 / 无 token 403
    assert client.post("/api/entries/auto-name", json={"ids": []},
                       headers=_auth()).status_code == 400
    assert client.post("/api/entries/auto-name", json={"ids": [e1.id]},
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
