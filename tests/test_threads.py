"""Thread 串联工作区测试（完整方案 §9.4，0.2.0 第三十二批）。

覆盖：迁移机制（新库直建 / 旧库升级）、线索 CRUD 与持久化（重开不丢）、条目增删移、
topic_recall 四通道与 relation_reason、thread_suggest 降级与 LLM 应用、Web API
端点与写守卫。会红的探针对应 CHANGELOG 第三十二批「复检探针」清单。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from knowatlas.datalayer.db import DataLayer
from knowatlas.datalayer.schema import latest_version, load_initial_schema
from knowatlas.models import Entry
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import thread_suggest, topic_recall
from knowatlas.web.app import create_app


# ----  fixtures ----

@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_TEST_TOKEN")), "test-token-123")
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def _auth():
    return {"X-KnowAtlas-Token": "test-token-123", "Origin": "http://127.0.0.1:8420"}


def _seed_entries(dl: DataLayer) -> list[Entry]:
    """三源 + 同 host + 同分类 + 同线索的种子数据（召回四通道各有着落）。"""
    es = [
        Entry.build(source_type="bookmark", source_key="th:b1", title="Python 异步入门",
                    locator="https://docs.example.org/async",
                    locator_canonical="https://docs.example.org/async",
                    native_path="书签栏/技术"),
        Entry.build(source_type="folder", source_key="th:f1", title="Python 异步笔记",
                    locator="file:///D/Data/notes/async.md", native_path="D:/Data/notes"),
        Entry.build(source_type="emmx", source_key="th:m1", title="Python 异步脑图",
                    locator="emmx://demo/1", native_path="脑图/编程"),
        Entry.build(source_type="bookmark", source_key="th:b2", title="同站点另一篇",
                    locator="https://docs.example.org/other",
                    locator_canonical="https://docs.example.org/other"),
        Entry.build(source_type="bookmark", source_key="th:b3", title="无关烹饪页",
                    locator="https://cook.example.net/c",
                    locator_canonical="https://cook.example.net/c"),
    ]
    dl.upsert_entries(es)
    cat = dl.create_category("技术开发", [], "rule")
    sub = dl.create_category("编程语言", [cat.id], "rule")
    for e in es[:3]:
        dl.attach_category(e.id, sub.id, 1.0, "rule", "r1")
    return es


# ---- 迁移机制 ----

def test_fresh_db_gets_latest_schema(tmp_path):
    dl = DataLayer(tmp_path / "fresh.db")
    try:
        assert dl.init_schema() == latest_version() == 6
        conn = sqlite3.connect(tmp_path / "fresh.db")
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"threads", "thread_items", "conv_messages", "regress_cases",
                    "entry_vectors"} <= tables
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        finally:
            conn.close()
    finally:
        dl.close()


def test_old_db_upgrades_without_data_loss(tmp_path):
    """旧库（user_version=1，只有 001）再次打开自动应用 002..005，既有条目无损。"""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(load_initial_schema())
    conn.execute("PRAGMA user_version = 1")
    conn.execute(
        "INSERT INTO entries (id, source_type, title, locator, meta, exported_at, status)"
        " VALUES ('aabbccddeeff0011','manual','旧条目','https://old.example/x','{}',"
        "'2026-10-19T00:00:00+08:00','active')")
    conn.commit()
    conn.close()

    dl = DataLayer(db)
    try:
        assert dl.init_schema() == 6
        e = dl.get_entry("aabbccddeeff0011")
        assert e is not None and e.title == "旧条目"
        # 迁移幂等：再初始化不报错不重复建表
        assert dl.init_schema() == 6
    finally:
        dl.close()


def test_db_newer_than_code_rejected(tmp_path):
    """库版本高于代码 → 明确报错（旧代码不许静默写新库）。"""
    db = tmp_path / "future.db"
    dl = DataLayer(db)
    dl.init_schema()
    dl._conn.execute("PRAGMA user_version = 99")
    dl._conn.commit()
    dl.close()
    dl2 = DataLayer(db)
    try:
        with pytest.raises(Exception) as exc_info:
            dl2.init_schema()
        assert "user_version=99" in str(exc_info.value)
    finally:
        dl2.close()


# ---- 线索 CRUD 与持久化 ----

def test_thread_crud_persists_across_reopen(tmp_path):
    db = tmp_path / "persist.db"
    dl = DataLayer(db)
    dl.init_schema()
    e = Entry.build(source_type="manual", source_key="th:p1", title="持久化条目",
                    locator="https://p.example/x", locator_canonical="https://p.example/x")
    dl.upsert_entries([e])
    t = dl.create_thread("学习线", note="先看概念")
    item = dl.add_thread_item(t.id, e.id, relation_type="prereq", note="从这开始")
    dl.close()

    dl2 = DataLayer(db)
    dl2.init_schema()
    try:
        loaded = dl2.get_thread(t.id)
        assert loaded is not None
        assert loaded.name == "学习线" and loaded.note == "先看概念"
        assert loaded.thread_type == "curated"
        assert len(loaded.items) == 1
        it = loaded.items[0]
        assert it.entry_id == e.id and it.position == 0
        assert it.relation_type == "prereq" and it.note == "从这开始"
        assert dl2.list_threads()[0]["item_count"] == 1
        assert dl2.threads_for_entry(e.id)[0]["id"] == t.id
    finally:
        dl2.close()


def test_thread_item_rules(dl):
    es = _seed_entries(dl)
    t = dl.create_thread("规则线")
    i1 = dl.add_thread_item(t.id, es[0].id)
    i2 = dl.add_thread_item(t.id, es[1].id)
    i3 = dl.add_thread_item(t.id, es[2].id)
    # 同线索重复条目被拒
    with pytest.raises(Exception):
        dl.add_thread_item(t.id, es[0].id)
    # 不存在条目被拒
    with pytest.raises(Exception):
        dl.add_thread_item(t.id, "ffffffffffffffff")
    # 不存在线索被拒
    with pytest.raises(Exception):
        dl.add_thread_item("ffffffffffffffff", es[0].id)
    # 移动：i3 到最前；越界夹紧
    dl.move_thread_item(t.id, i3.id, 0)
    order = [it.entry_id for it in dl.get_thread(t.id).items]
    assert order == [es[2].id, es[0].id, es[1].id]
    dl.move_thread_item(t.id, i3.id, 99)
    order = [it.entry_id for it in dl.get_thread(t.id).items]
    assert order == [es[0].id, es[1].id, es[2].id]
    # 删除后序号紧凑（无空洞）
    dl.remove_thread_item(t.id, i1.id)
    positions = [it.position for it in dl.get_thread(t.id).items]
    assert positions == [0, 1]
    # 属性更新
    dl.update_thread_item(t.id, i2.id, relation_type="because", note="因果")
    it = next(x for x in dl.get_thread(t.id).items if x.id == i2.id)
    assert it.relation_type == "because" and it.note == "因果"
    # 删线索级联清 items
    dl.delete_thread(t.id)
    assert dl.get_thread(t.id) is None
    assert dl.threads_for_entry(es[0].id) == []
    # 空名/超长名被拒
    with pytest.raises(Exception):
        dl.create_thread("  ")
    with pytest.raises(Exception):
        dl.create_thread("x" * 201)
    # thread_type 白名单
    with pytest.raises(Exception):
        dl.create_thread("非法类型", thread_type="bogus")


def test_reorder_requires_exact_set(dl):
    es = _seed_entries(dl)
    t = dl.create_thread("重排线")
    for e in es[:3]:
        dl.add_thread_item(t.id, e.id)
    # 少给一个 → 拒（防静默丢条目）
    with pytest.raises(Exception):
        dl.reorder_thread_items(t.id, [es[0].id, es[1].id])
    dl.reorder_thread_items(t.id, [es[1].id, es[2].id, es[0].id])
    assert [it.entry_id for it in dl.get_thread(t.id).items] == [es[1].id, es[2].id, es[0].id]


# ---- topic_recall ----

def test_topic_recall_channels_and_reasons(dl):
    es = _seed_entries(dl)
    t = dl.create_thread("Python 学习线")
    dl.add_thread_item(t.id, es[0].id)
    dl.add_thread_item(t.id, es[2].id)
    ctx = TaskContext(run_id="r1", datalayer=dl)

    res = topic_recall.run("Python", ctx)
    assert res["resolved_as"] == "topic" and res["seeds"] >= 3
    by_id = {h["entry_id"]: h for h in res["hits"]}
    # 跨源聚合：bookmark / folder / emmx 都到场
    assert set(res["groups"]) >= {"bookmark", "folder", "emmx"}
    # 每条都带关联解释（§9.4：没有解释的关联不展示）
    assert all(h["channels"] for h in res["hits"])
    # 种子带 fts；folder 条目经 cocategory 到场；emmx 与书签种子同线索
    assert "fts" in by_id[es[0].id]["channels"]
    assert any(c.startswith("cocategory:") for c in by_id[es[1].id]["channels"])
    assert any(c.startswith("same_host:") for c in by_id[es[3].id]["channels"])
    assert any(c.startswith("thread:") for c in by_id[es[2].id]["channels"])
    # 无关站点条目不因主题词进来（无通道即不进结果）
    assert es[4].id not in by_id
    # 无解释的空结果
    empty = topic_recall.run("绝不存在的词zzz", ctx)
    assert empty["resolved_as"] == "empty" and empty["hits"] == []


def test_topic_recall_node_inputs(dl):
    es = _seed_entries(dl)
    ctx = TaskContext(run_id="r1", datalayer=dl)
    sub = dl.get_category_by_path("技术开发/编程语言")
    res_cat = topic_recall.run(f"c:{sub.id}", ctx)
    assert res_cat["resolved_as"] == "category"
    assert {h["entry_id"] for h in res_cat["hits"]} >= {es[0].id, es[1].id, es[2].id}
    # 种子的首个关联解释 = 焦点分类本身
    assert all(h["channels"][0].startswith("focus_category:")
               for h in res_cat["hits"] if h["is_seed"])
    res_entry = topic_recall.run(f"e:{es[0].id}", ctx)
    assert res_entry["resolved_as"] == "entry"
    assert res_entry["hits"][0]["entry_id"] == es[0].id
    assert res_entry["hits"][0]["is_seed"] is True
    # 不存在的节点 id → 空结果不抛错
    assert topic_recall.run("c:ffffffffffffffff", ctx)["hits"] == []
    assert topic_recall.run("e:ffffffffffffffff", ctx)["hits"] == []
    # datalayer 缺失（非 Web 上下文）→ 空结果不抛错
    assert topic_recall.run("Python", TaskContext(run_id="r1"))["hits"] == []


# ---- thread_suggest ----

def test_thread_suggest_degrades_without_llm(dl):
    es = _seed_entries(dl)
    items = [{"entry_id": e.id, "title": e.title} for e in es[:3]]
    res = thread_suggest.run(items, "线", TaskContext(run_id="r1"))
    assert res["llm_used"] is False
    assert res["order"] == [e.id for e in es[:3]]  # 原序


def test_thread_suggest_applies_llm_order(dl):
    es = _seed_entries(dl)
    items = [{"entry_id": e.id, "title": e.title} for e in es[:3]]

    class FakeLlm:
        def chat(self, system, user):
            return ('[{"i":2,"why":"先看脑图概览"},{"i":1,"why":"再读教程"},{"i":3,"why":"最后笔记"}]')

    res = thread_suggest.run(items, "线", TaskContext(run_id="r1", llm=FakeLlm()))
    assert res["llm_used"] is True
    assert res["order"] == [es[1].id, es[0].id, es[2].id]
    assert "先看脑图概览" in res["rationale"]

    # LLM 漏号 → 原序补齐不丢条目
    class PartialLlm:
        def chat(self, system, user):
            return '[{"i":2,"why":"只要第二条"}]'

    res2 = thread_suggest.run(items, "线", TaskContext(run_id="r1", llm=PartialLlm()))
    assert sorted(res2["order"]) == sorted(e.id for e in es[:3])
    assert res2["order"][0] == es[1].id


def test_thread_suggest_llm_failure_degrades(dl):
    es = _seed_entries(dl)
    items = [{"entry_id": e.id, "title": e.title} for e in es[:3]]

    class BadLlm:
        def chat(self, system, user):
            raise LlmError("boom")

    res = thread_suggest.run(items, "线", TaskContext(run_id="r1", llm=BadLlm()))
    assert res["llm_used"] is False and res.get("error")
    assert res["order"] == [e.id for e in es[:3]]  # 原序，不阻塞


# ---- Web API ----

def test_thread_api_crud_flow(client, dl):
    es = _seed_entries(dl)
    # 无令牌写 → 403（守卫不因新端点放松）
    assert client.post("/api/threads", json={"name": "x"}).status_code == 403
    # 新建 + 路径固化（entry_ids 一并入库）
    r = client.post("/api/threads",
                    json={"name": "固化线", "note": "n",
                          "entry_ids": [es[0].id, es[1].id, "ffffffffffffffff"]},
                    headers=_auth())
    assert r.status_code == 200
    tid = r.json()["id"]
    assert r.json()["added"] == [es[0].id, es[1].id]
    assert r.json()["skipped"] == ["ffffffffffffffff"]
    assert [i["entry_id"] for i in r.json()["items"]] == [es[0].id, es[1].id]
    # 列表 / 详情
    assert any(t["id"] == tid for t in client.get("/api/threads").json()["threads"])
    detail = client.get(f"/api/threads/{tid}").json()
    assert detail["name"] == "固化线" and len(detail["items"]) == 2
    assert client.get("/api/threads/ffffffffffffffff").status_code == 404
    # 改名 / 备注
    assert client.post(f"/api/threads/{tid}/update",
                       json={"name": "改名线"}, headers=_auth()).status_code == 200
    assert client.get(f"/api/threads/{tid}").json()["name"] == "改名线"
    # 条目：加 / 改关系 / 移 / 删
    r = client.post(f"/api/threads/{tid}/items", json={"entry_id": es[2].id}, headers=_auth())
    assert r.status_code == 200 and r.json()["position"] == 2
    item_id = r.json()["item_id"]
    assert client.post(f"/api/threads/{tid}/items/{item_id}/update",
                       json={"relation_type": "because"}, headers=_auth()).status_code == 200
    moved = client.post(f"/api/threads/{tid}/items/{item_id}/move",
                        json={"position": 0}, headers=_auth())
    assert moved.status_code == 200
    order = [i["entry_id"] for i in client.get(f"/api/threads/{tid}").json()["items"]]
    assert order == [es[2].id, es[0].id, es[1].id]
    assert client.post(f"/api/threads/{tid}/items/{item_id}/remove", json={},
                       headers=_auth()).status_code == 200
    # 重复加同条目 → 400
    r = client.post(f"/api/threads/{tid}/items", json={"entry_id": es[0].id}, headers=_auth())
    assert r.status_code == 400
    # 建议排序：无 LLM 配置 → 原序降级、不写库
    r = client.post(f"/api/threads/{tid}/suggest", json={}, headers=_auth())
    assert r.status_code == 200 and r.json()["llm_used"] is False and r.json()["applied"] is False
    # 删除
    assert client.post(f"/api/threads/{tid}/delete", json={}, headers=_auth()).status_code == 200
    assert client.get(f"/api/threads/{tid}").status_code == 404


def test_recall_endpoint_needs_no_token(client, dl):
    es = _seed_entries(dl)
    r = client.post("/api/recall", json={"topic": "Python"})
    assert r.status_code == 200
    assert r.json()["resolved_as"] == "topic"
    assert any(h["entry_id"] == es[0].id for h in r.json()["hits"])
    assert client.post("/api/recall", json={"topic": "  "}).json()["hits"] == []


def test_entry_threads_endpoint(client, dl):
    es = _seed_entries(dl)
    r = client.post("/api/threads", json={"name": "徽标线", "entry_ids": [es[0].id]},
                    headers=_auth())
    tid = r.json()["id"]
    threads = client.get(f"/api/entries/{es[0].id}/threads").json()["threads"]
    assert [t["id"] for t in threads] == [tid]
    assert client.get(f"/api/entries/{es[1].id}/threads").json()["threads"] == []


def test_threads_lookup_batch(client, dl):
    """工作台「线索」视图聚合用的批量端点：有线索/无线索/不存在 混合查询。"""
    es = _seed_entries(dl)
    t = dl.create_thread("查线")
    dl.add_thread_item(t.id, es[0].id)
    r = client.get(f"/api/threads-lookup?ids={es[0].id},{es[1].id},nope12345678")
    assert r.status_code == 200
    m = r.json()["map"]
    assert [x["id"] for x in m[es[0].id]] == [t.id]
    assert m[es[1].id] == [] and m["nope12345678"] == []
    assert client.get("/api/threads-lookup?ids=").json() == {"map": {}}


def test_threads_lookup_batch(client, dl):
    """工作台「线索」视图聚合用的批量端点：有线索/无线索/不存在 混合查询。"""
    es = _seed_entries(dl)
    t = dl.create_thread("查线")
    dl.add_thread_item(t.id, es[0].id)
    r = client.get(f"/api/threads-lookup?ids={es[0].id},{es[1].id},nope12345678")
    assert r.status_code == 200
    m = r.json()["map"]
    assert [x["id"] for x in m[es[0].id]] == [t.id]
    assert m[es[1].id] == [] and m["nope12345678"] == []
    assert client.get("/api/threads-lookup?ids=").json() == {"map": {}}
