"""放射导航测试（0.2.0 第三十三批）：radiate / reverse_reach 数据层 + API。

工单探针（CHANGELOG 第三十三批）：
- 三类焦点均返回邻域，且每个节点 reasons 非空、每条边 reason 非空
- per_channel 上限生效且 truncated 计数正确
- 条目焦点 thread 通道带线索名；reverse 对条目返回分类（带 path）+ 域名 + 线索
- 空分类空层降级（不造节点）；未知节点 API 404
- radiate/reverse 免令牌可读；写端点无令牌 403
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knowatlas.models import Entry
from knowatlas.web.app import create_app


@pytest.fixture
def seeded(dl):
    """种子：2 条同 host 书签（同分类挂接）+ 1 条本地文件，条目0 与条目2 同线索。"""
    es = [
        Entry.build(source_type="bookmark", source_key="b1", title="Python 教程",
                    locator="https://docs.example.org/py",
                    locator_canonical="https://docs.example.org/py"),
        Entry.build(source_type="bookmark", source_key="b2", title="docs 站另一篇",
                    locator="https://docs.example.org/other",
                    locator_canonical="https://docs.example.org/other"),
        Entry.build(source_type="folder", source_key="f1", title="本地笔记",
                    locator="file:///D/notes/py.md", native_path="D:/Data"),
    ]
    dl.upsert_entries(es)
    cat = dl.create_category("技术开发", [], "manual")
    sub = dl.create_category("编程语言", [cat.id], "rule")
    for e in es[:2]:
        dl.attach_category(e.id, sub.id, 1.0, "rule", "r1")
    t = dl.create_thread("Python 线")
    dl.add_thread_item(t.id, es[0].id)
    dl.add_thread_item(t.id, es[2].id)
    return {"entries": es, "cat": cat, "sub": sub, "thread": t}


# ---- 数据层：radiate ----

def test_radiate_category_focus_reasons_complete(dl, seeded):
    r = dl.radiate(f"c:{seeded['sub'].id}")
    assert r is not None and r["focus"]["kind"] == "category"
    assert r["nodes"], "挂接条目 + 父分类应构成邻域"
    assert all(n["reasons"] for n in r["nodes"]), "每个节点必须带关联解释"
    assert all(e["reason"] for e in r["edges"]), "每条边必须带 reason"
    by_kind = {n["id"][:2] for n in r["nodes"]}
    assert by_kind == {"e:", "c:"}  # 挂接条目 + 父分类
    parent = next(n for n in r["nodes"] if n["id"] == f"c:{seeded['cat'].id}")
    assert "parent" in parent["reasons"]
    attached = next(n for n in r["nodes"] if n["id"] == f"e:{seeded['entries'][0].id}")
    assert any(x.startswith("attach:") for x in attached["reasons"])


def test_radiate_child_channel_has_edge(dl, seeded):
    """焦点=技术开发（有子分类）：子分类必须以 child 边连到焦点。

    第四十八批修复：child 通道原来只 add_node 不 add_edge——子分类成孤立
    节点漂在画布中央冒充主要内容，tooltip 也无从解释（截图实锤）。
    """
    r = dl.radiate(f"c:{seeded['cat'].id}")
    assert r is not None
    sub_node = next(n for n in r["nodes"] if n["id"] == f"c:{seeded['sub'].id}")
    assert "child" in sub_node["reasons"]
    edge = next(e for e in r["edges"] if e["target"] == f"c:{seeded['sub'].id}")
    assert edge["source"] == f"c:{seeded['cat'].id}" and edge["reason"] == "child"


def test_radiate_entry_focus_channels(dl, seeded):
    r = dl.radiate(f"e:{seeded['entries'][0].id}")
    assert r is not None and r["focus"]["kind"] == "entry"
    assert all(n["reasons"] for n in r["nodes"])
    assert all(e["reason"] for e in r["edges"])
    reasons = {x for n in r["nodes"] for x in n["reasons"]}
    assert any(x.startswith("attach:") for x in reasons)   # 直挂分类
    assert any(x.startswith("same_host:") for x in reasons)  # 同域名（条目1）
    assert any(x.startswith("thread:") for x in reasons)   # 同线索（条目2）
    thread_node = next(n for n in r["nodes"]
                       if n["id"] == f"e:{seeded['entries'][2].id}")
    assert any(x.startswith("thread:Python 线") for x in thread_node["reasons"])
    # 直挂分类节点带派生 path
    cat_node = next(n for n in r["nodes"] if n["id"] == f"c:{seeded['sub'].id}")
    assert cat_node["path"] == "技术开发/编程语言"
    # 焦点带 locator（tooltip 可开原文）
    assert r["focus"]["locator"].startswith("https://")


def test_radiate_domain_focus(dl, seeded):
    r = dl.radiate("d:docs.example.org")
    assert r is not None and r["focus"]["kind"] == "domain"
    ids = {n["id"] for n in r["nodes"]}
    assert ids == {f"e:{seeded['entries'][0].id}", f"e:{seeded['entries'][1].id}"}
    assert all(n["reasons"] == [f"host_member:docs.example.org"] for n in r["nodes"])


def test_radiate_per_channel_truncation(dl, seeded):
    full = dl.radiate(f"c:{seeded['sub'].id}")
    assert full["truncated"] == {}
    tight = dl.radiate(f"c:{seeded['sub'].id}", per_channel=1)
    assert tight["truncated"].get("attach") == 1          # 2 条挂接只出 1 条
    assert len([n for n in tight["nodes"] if n["id"].startswith("e:")]) == 1
    # 上限不为 0 时通道仍产出——per_channel=40 封顶由 API 层约束
    wide = dl.radiate(f"c:{seeded['sub'].id}", per_channel=40)
    assert wide["truncated"] == {}


def test_radiate_empty_category_degrades(dl, seeded):
    empty = dl.create_category("空壳类", [], "manual")
    r = dl.radiate(f"c:{empty.id}")
    assert r is not None and r["nodes"] == [] and r["edges"] == []
    assert r["truncated"] == {}


def test_radiate_unknown_node_returns_none(dl):
    assert dl.radiate("c:nope") is None
    assert dl.radiate("e:nope") is None
    assert dl.radiate("x:bogus") is None
    assert dl.radiate("c:") is None


def test_radiate_focus_not_in_neighborhood(dl, seeded):
    """焦点自身不作为邻域节点重复出现（条目焦点同 host 含自身时被剔）。"""
    r = dl.radiate(f"e:{seeded['entries'][0].id}")
    assert f"e:{seeded['entries'][0].id}" not in {n["id"] for n in r["nodes"]}


# ---- 数据层：reverse_reach ----

def test_reverse_entry_focus(dl, seeded):
    r = dl.reverse_reach(f"e:{seeded['entries'][0].id}")
    assert r is not None
    kinds = {i["kind"] for i in r["items"]}
    assert kinds == {"category", "domain", "thread"}
    cat = next(i for i in r["items"] if i["kind"] == "category")
    assert cat["path"] == "技术开发/编程语言"
    assert cat["reason"].startswith("attach:")
    thread = next(i for i in r["items"] if i["kind"] == "thread")
    assert thread["name"] == "Python 线"
    assert thread["url"] == f"/thread.html?id={seeded['thread'].id}"


def test_reverse_category_focus(dl, seeded):
    r = dl.reverse_reach(f"c:{seeded['sub'].id}")
    assert r is not None
    kinds = {i["kind"] for i in r["items"]}
    assert kinds == {"category", "entry"}
    parent = next(i for i in r["items"] if i["id"] == f"c:{seeded['cat'].id}")
    assert parent["reason"] == "parent"


def test_reverse_domain_and_unknown_unsupported(dl, seeded):
    assert dl.reverse_reach("d:docs.example.org") is None
    assert dl.reverse_reach("c:nope") is None
    assert dl.reverse_reach("x:bogus") is None


# ---- Web API ----

@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")),
                       "test-token-123")
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def test_api_radiate_and_reverse_read_without_token(client, seeded):
    r = client.get(f"/api/graph/radiate?node_id=c:{seeded['sub'].id}")
    assert r.status_code == 200
    assert all(n["reasons"] for n in r.json()["nodes"])
    r2 = client.get(f"/api/graph/reverse?node_id=e:{seeded['entries'][0].id}")
    assert r2.status_code == 200
    assert {i["kind"] for i in r2.json()["items"]} == {"category", "domain", "thread"}


def test_api_radiate_unknown_404(client):
    assert client.get("/api/graph/radiate?node_id=c:nope").status_code == 404
    assert client.get("/api/graph/reverse?node_id=c:nope").status_code == 404
    assert client.get("/api/graph/reverse?node_id=d:some.host").status_code == 404


def test_api_per_channel_clamped(client, seeded):
    r = client.get(f"/api/graph/radiate?node_id=c:{seeded['sub'].id}&per_channel=1")
    assert r.json()["truncated"].get("attach") == 1
    # 超界值被夹紧（负数/过大）
    r2 = client.get(f"/api/graph/radiate?node_id=c:{seeded['sub'].id}&per_channel=999")
    assert r2.status_code == 200


def test_api_write_still_guarded(client, seeded):
    """读免令牌，写（固化为线索）无令牌必须 403——既有 H5 守卫不因新端点松动。"""
    entry_ids = [e.id for e in seeded["entries"][:2]]
    r = client.post("/api/threads", json={"name": "固化", "entry_ids": entry_ids},
                    headers={})
    assert r.status_code == 403
    auth = {"X-KnowAtlas-Token": "test-token-123", "Origin": "http://127.0.0.1:8420"}
    r2 = client.post("/api/threads", json={"name": "固化", "entry_ids": entry_ids},
                     headers=auth)
    assert r2.status_code == 200
    assert len(r2.json()["added"]) == 2


# ---- 批次 72：子树稀疏折叠（compact）+ 分类深度（前端分层铺开原料） ----

@pytest.fixture
def dense_seeded(dl):
    """根 A：子 B（稀疏支，直挂 1 条）、子 C（稠密支，直挂 3 条）；根 A 直挂 1 条。"""
    es = [Entry.build(source_type="bookmark", source_key=f"d{i}",
                      title=f"条目{i}", locator=f"https://x.example.org/{i}",
                      locator_canonical=f"https://x.example.org/{i}")
          for i in range(5)]
    dl.upsert_entries(es)
    a = dl.create_category("根类", [], "manual")
    b = dl.create_category("稀疏支", [a.id], "manual")
    c = dl.create_category("稠密支", [a.id], "manual")
    dl.attach_category(es[0].id, b.id, 1.0, "manual", "t72")     # B 直挂 1 条
    for e in es[1:4]:
        dl.attach_category(e.id, c.id, 1.0, "manual", "t72")     # C 直挂 3 条
    dl.attach_category(es[4].id, a.id, 1.0, "manual", "t72")     # 根直挂 1 条
    return {"a": a, "b": b, "c": c, "es": es}


def test_subtree_classic_depth_fields(dl, dense_seeded):
    """经典视图分类节点带 depth（root=0，子类=1），供前端分层铺开。"""
    d = dl.get_graph_subtree(dense_seeded["a"].id)
    nodes = {n["id"]: n for n in d["nodes"]}
    assert nodes[f"c:{dense_seeded['a'].id}"]["depth"] == 0
    assert nodes[f"c:{dense_seeded['b'].id}"]["depth"] == 1
    assert nodes[f"c:{dense_seeded['c'].id}"]["depth"] == 1
    assert len([n for n in d["nodes"] if n["kind"] == "entry"]) == 5


def test_subtree_depth_multi_parent_takes_shortest(dl, dense_seeded):
    """多父 DAG 深度取最短链：B 经 A 直连=1，经深层链=3，取 1。"""
    a, b = dense_seeded["a"], dense_seeded["b"]
    deep = dl.create_category("深层", [a.id], "manual")
    deeper = dl.create_category("更深", [deep.id], "manual")
    dl.attach_parent(b.id, deeper.id)
    d = dl.get_graph_subtree(a.id)
    nodes = {n["id"]: n for n in d["nodes"]}
    assert nodes[f"c:{b.id}"]["depth"] == 1


def test_subtree_compact_folds_sparse_branches(dl, dense_seeded):
    """compact：直挂 ≤2 条的子分类藏条目（folded 计数），稠密支与根直挂不受影响。"""
    d = dl.get_graph_subtree(dense_seeded["a"].id, compact=True)
    nodes = {n["id"]: n for n in d["nodes"]}
    assert nodes[f"c:{dense_seeded['b'].id}"]["folded"] == 1
    assert "folded" not in nodes[f"c:{dense_seeded['c'].id}"]
    e_ids = {n["id"] for n in d["nodes"] if n["kind"] == "entry"}
    assert f"e:{dense_seeded['es'][0].id}" not in e_ids          # 稀疏支条目隐去
    assert {f"e:{dense_seeded['es'][i].id}" for i in (1, 2, 3, 4)} <= e_ids
    assert not any(l["target"] == f"c:{dense_seeded['b'].id}" for l in d["links"])
    assert d["compact"] is True


def test_subtree_compact_default_off(dl, dense_seeded):
    """默认（compact=False）行为不变：无 folded、全条目可见。"""
    d = dl.get_graph_subtree(dense_seeded["a"].id)
    assert all("folded" not in n for n in d["nodes"])
    assert len([n for n in d["nodes"] if n["kind"] == "entry"]) == 5


def test_subtree_compact_keeps_shared_entries(dl, dense_seeded):
    """条目同时挂稀疏支与稠密支：折叠只藏稀疏支的边，条目经稠密支仍可见。"""
    shared = dense_seeded["es"][0]
    dl.attach_category(shared.id, dense_seeded["c"].id, 1.0, "manual", "t72")
    d = dl.get_graph_subtree(dense_seeded["a"].id, compact=True)
    e_ids = {n["id"] for n in d["nodes"] if n["kind"] == "entry"}
    assert f"e:{shared.id}" in e_ids
    assert any(l["source"] == f"e:{shared.id}" and l["target"] == f"c:{dense_seeded['c'].id}"
               for l in d["links"])
    assert not any(l["target"] == f"c:{dense_seeded['b'].id}" for l in d["links"])


def test_subtree_hierarchy_ignores_compact(dl, dense_seeded):
    """层级模式不受 compact 影响：仍只出子分类、无 depth/folded/compact。"""
    d = dl.get_graph_subtree(dense_seeded["a"].id, hierarchy=True, compact=True)
    assert all(n["kind"] == "category" for n in d["nodes"])
    assert all("depth" not in n and "folded" not in n for n in d["nodes"])
    assert "compact" not in d


def test_api_graph_subtree_compact_param(client, dense_seeded):
    """API 层 compact=1 透传；默认不带 folded（前端按需开启）。"""
    r = client.get(f"/api/graph/subtree?category_id={dense_seeded['a'].id}&compact=1")
    assert r.status_code == 200
    assert any(n.get("folded") for n in r.json()["nodes"])
    r2 = client.get(f"/api/graph/subtree?category_id={dense_seeded['a'].id}")
    assert r2.status_code == 200
    assert all("folded" not in n for n in r2.json()["nodes"])
