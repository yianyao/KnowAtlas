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
