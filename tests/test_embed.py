"""M4 本地 embedding 测试（0.2.0 第五十六批）：向量索引 + 混合检索 + 语义边 + 聚类。

FakeEmbedder：显式注册表（text → 向量）+ hash 兜底，确定性可控；
不依赖 sentence-transformers（optional 依赖缺失不影响测试与主链路）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knowatlas.datalayer.db import DataLayer
from knowatlas.models import Entry
from knowatlas.pipeline.embed_index import (
    cluster_report, embed_entries, hybrid_search,
)
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.embed import (
    blob_to_vec, cosine, normalize, top_similar, vec_to_blob,
)
from knowatlas.semantic.tasks import topic_recall
from knowatlas.web.app import create_app


# ---- 测试替身 ----

def _hash_vec(text: str) -> list[float]:
    v = [0.0] * 8
    for ch in text[:24]:
        v[ord(ch) % 8] += 1.0
    return normalize(v)


class FakeEmbedder:
    """table 精确匹配 → 指定向量；否则按字符 hash。name 带 fake: 前缀。"""

    def __init__(self, table: dict[str, list[float]] | None = None):
        self.table = table or {}
        self.name = "fake:test"
        self.dim = 8
        self.calls: list[str] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.extend(texts)
        return [list(self.table.get(t, _hash_vec(t))) for t in texts]


class FakeLlm:
    def __init__(self, reply: str):
        self.reply = reply

    def chat(self, system: str, user: str) -> str:
        return self.reply


def _seed(dl: DataLayer, n: int = 3) -> list[Entry]:
    es = [
        Entry.build(source_type="manual", source_key=f"emb:m{i}", title=f"条目{i}",
                    locator=f"https://example.com/{i}", locator_canonical=None,
                    inline_content=f"这是第{i}篇正文内容", native_path=None,
                    meta={"source_type": "manual"})
        for i in range(1, n + 1)
    ]
    dl.upsert_entries(es)
    return es


# ---- embed.py 数学基元 ----

def test_blob_roundtrip_and_cosine():
    v = normalize([1.0, 2.0, -3.0, 0.5, 0.0, 0.0, 0.0, 0.0])
    blob = vec_to_blob(v)
    assert len(blob) == 32  # 8 × float32
    back = blob_to_vec(blob)
    assert abs(cosine(v, back) - 1.0) < 1e-5          # 往返无损（float32 精度内）
    assert abs(cosine([1.0, 0.0, 0, 0, 0, 0, 0, 0],
                      [0.0, 1.0, 0, 0, 0, 0, 0, 0])) < 1e-9  # 正交
    assert cosine([], []) == 0.0 and cosine([1.0], [1.0, 2.0]) == 0.0


def test_top_similar_threshold_and_order():
    q = [1.0, 0.0, 0, 0, 0, 0, 0, 0]
    cands = {"a": [0.99, 0.1, 0, 0, 0, 0, 0, 0], "b": [0.0, 1.0, 0, 0, 0, 0, 0, 0],
             "c": [1.0, 0.0, 0, 0, 0, 0, 0, 0]}
    hits = top_similar(q, cands, k=2, threshold=0.5)
    assert [eid for eid, _ in hits] == ["c", "a"]      # b 被阈值挡掉
    assert hits[0][1] > 0.99


# ---- 数据层：entry_vectors（迁移 006） ----

def test_vectors_crud_and_cascade(dl):
    es = _seed(dl, 2)
    assert dl.count_vectors() == 0
    dl.put_vectors([{"entry_id": es[0].id, "dim": 8,
                     "vector": vec_to_blob(_hash_vec(es[0].inline_content)),
                     "model": "fake:test"}])
    got = dl.get_vector(es[0].id)
    assert got is not None and got["dim"] == 8 and got["model"] == "fake:test"
    # upsert 覆盖
    dl.put_vectors([{"entry_id": es[0].id, "dim": 8,
                     "vector": vec_to_blob(_hash_vec("新文本")), "model": "fake:test"}])
    assert dl.count_vectors() == 1
    assert blob_to_vec(dl.get_vector(es[0].id)["vector"]) != blob_to_vec(
        vec_to_blob(_hash_vec(es[0].inline_content)))
    assert list(dl.all_vectors()) == [es[0].id]
    dl.delete_vectors([es[0].id])
    assert dl.count_vectors() == 0


# ---- embed_entries 索引 ----

def test_embed_entries_incremental_and_force(dl):
    es = _seed(dl, 3)
    dl.upsert_entries([Entry.build(
        source_type="manual", source_key="emb:no-text", title="无正文",
        locator="https://example.com/nt", locator_canonical=None,
        inline_content=None, native_path=None, meta={})])
    emb = FakeEmbedder()
    stats = embed_entries(dl, emb)
    assert stats["embedded"] == 3 and stats["no_text"] == 1  # 3 有正文 + 1 无正文
    assert dl.count_vectors() == 3
    # 增量：已有同模型向量跳过
    stats2 = embed_entries(dl, emb)
    assert stats2["embedded"] == 0 and stats2["skipped"] == 3
    # force 重算
    stats3 = embed_entries(dl, emb, force=True)
    assert stats3["embedded"] == 3
    # 禁用降级
    assert embed_entries(dl, None)["disabled"] is True


def test_embed_entries_skips_inactive(dl):
    es = _seed(dl, 2)
    dl.set_status([es[0].id], "archived")
    stats = embed_entries(dl, FakeEmbedder())
    assert stats["embedded"] == 1            # 仅 active 的 es[1] 入库
    assert dl.get_vector(es[0].id) is None   # archived 不产生向量


# ---- hybrid_search ----

def test_hybrid_search_none_embedder_returns_none(dl):
    assert hybrid_search(dl, None, "任意") is None


def test_hybrid_search_fusion_and_reasons(dl):
    es = [
        Entry.build(source_type="manual", source_key="emb:dep", title="部署纪要",
                    locator="https://e.com/dep", locator_canonical=None,
                    inline_content="项目部署安排在周五上午开会", native_path=None,
                    meta={}),
        Entry.build(source_type="manual", source_key="emb:cost", title="费用说明",
                    locator="https://e.com/cost", locator_canonical=None,
                    inline_content="云资源费用分摊比例表", native_path=None,
                    meta={}),
    ]
    dl.upsert_entries(es)
    v_deploy = [1.0, 0.0, 0, 0, 0, 0, 0, 0]
    dl.put_vectors([
        {"entry_id": es[0].id, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(v_deploy)},   # 部署纪要：语义也是部署
        {"entry_id": es[1].id, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([0.6, 0.8, 0, 0, 0, 0, 0, 0]))},  # 与 query 弱相似
    ])
    emb = FakeEmbedder(table={"部署": list(v_deploy)})
    r = hybrid_search(dl, emb, "部署")
    assert r is not None and r["mode"] == "hybrid" and r["vectors"] == 2
    ids = [h["entry_id"] for h in r["hits"]]
    assert ids == [es[0].id, es[1].id]              # 双命中在前
    hit_deploy = next(h for h in r["hits"] if h["entry_id"] == es[0].id)
    assert "fts" in hit_deploy["reasons"] and any(
        x.startswith("sim:") for x in hit_deploy["reasons"])
    # 纯 sim 条目（费用说明 fts 无「部署」字样）
    hit_cost = next(h for h in r["hits"] if h["entry_id"] == es[1].id)
    assert hit_cost["reasons"] == [x for x in hit_cost["reasons"]
                                   if x.startswith("sim:")]


def test_hybrid_search_typo_tolerant_pure_sim(dl):
    """错字 query：fts 零命中，纯语义命中照样返回（sim reason 可解释）。"""
    es = _seed(dl, 1)
    v = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    dl.put_vectors([{"entry_id": es[0].id, "dim": 8, "model": "fake:test",
                     "vector": vec_to_blob(v)}])
    emb = FakeEmbedder(table={"部暑安排": list(v)})  # 「部署」错写成「部暑」
    r = hybrid_search(dl, emb, "部暑安排")
    assert r is not None and len(r["hits"]) == 1
    assert r["hits"][0]["entry_id"] == es[0].id
    assert r["hits"][0]["reasons"][0].startswith("sim:")
    assert r["hits"][0]["reasons"] == [r["hits"][0]["reasons"][0]]  # 无 fts


# ---- radiate sim 通道 ----

def test_radiate_sim_channel(dl):
    es = _seed(dl, 3)
    dl.put_vectors([
        {"entry_id": es[0].id, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([1.0, 0, 0, 0, 0, 0, 0, 0]))},
        {"entry_id": es[1].id, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([0.95, 0.3, 0, 0, 0, 0, 0, 0]))},  # 近邻
        {"entry_id": es[2].id, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([0.0, 0.0, 1.0, 0, 0, 0, 0, 0]))},  # 正交
    ])
    r = dl.radiate(f"e:{es[0].id}")
    sim_nodes = [n for n in r["nodes"] if any(s.startswith("sim:") for s in n["reasons"])]
    assert len(sim_nodes) == 1 and sim_nodes[0]["id"] == f"e:{es[1].id}"
    # 同条目另有 same_host 通道 → edge reason 拼接两段（sim 段在尾部）
    edge = next(e for e in r["edges"] if e["target"] == f"e:{es[1].id}")
    assert "sim:0.95" in edge["reason"]


def test_radiate_no_vector_no_sim_channel(dl):
    es = _seed(dl, 2)  # 无向量
    r = dl.radiate(f"e:{es[0].id}")
    assert all(not any(s.startswith("sim:") for s in n["reasons"])
               for n in r["nodes"])


# ---- topic_recall sim 通道 ----

def test_topic_recall_sim_channel_optional(dl):
    es = _seed(dl, 2)   # 正文均含「正文」二字 → fts 命中产生种子
    v = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    dl.put_vectors([{"entry_id": es[1].id, "dim": 8, "model": "fake:test",
                     "vector": vec_to_blob(v)}])
    # embedder=None：无 sim 通道（现状回归；同 host 通道与本题无关只查 sim）
    r0 = topic_recall.recall("正文", TaskContext(run_id="r", datalayer=dl))
    hit1 = next(h for h in r0["hits"] if h["entry_id"] == es[1].id)
    assert all(not c.startswith("sim:") for c in hit1["channels"])
    # 有 embedder：query 注册向量 → 同一条目追加 sim 通道
    emb = FakeEmbedder(table={"正文": list(v)})
    r1 = topic_recall.recall("正文", TaskContext(run_id="r", datalayer=dl, embedder=emb))
    hit1b = next(h for h in r1["hits"] if h["entry_id"] == es[1].id)
    assert any(c.startswith("sim:") for c in hit1b["channels"])
    # es[0] 无向量：不追加 sim 通道
    hit0 = next(h for h in r1["hits"] if h["entry_id"] == es[0].id)
    assert all(not c.startswith("sim:") for c in hit0["channels"])


# ---- cluster_report ----

def test_cluster_report_llm_naming_and_no_autocreate(dl):
    es = _seed(dl, 4)
    v_a = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    v_b = normalize([0.0, 1.0, 0, 0, 0, 0, 0, 0])
    dl.put_vectors([
        {"entry_id": es[0].id, "dim": 8, "model": "fake:test", "vector": vec_to_blob(v_a)},
        {"entry_id": es[1].id, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([0.98, 0.05, 0, 0, 0, 0, 0, 0]))},  # 近 a
        {"entry_id": es[2].id, "dim": 8, "model": "fake:test", "vector": vec_to_blob(v_b)},
        {"entry_id": es[3].id, "dim": 8, "model": "fake:test", "vector": vec_to_blob(v_b)},
    ])
    llm = FakeLlm("云费用管理")
    report = cluster_report(dl, FakeEmbedder(), llm)
    assert "disabled" not in report and len(report["clusters"]) == 2
    top = report["clusters"][0]
    assert top["size"] == 2 and top["name"] == "云费用管理"   # LLM 命名
    got_ids = {e["id"] for e in top["entries"]}
    assert got_ids in ({es[0].id, es[1].id}, {es[2].id, es[3].id})
    # 不建类：条目仍全部未分类
    assert len(dl.get_uncategorized(limit=100)) >= 4


def test_cluster_report_llm_none_fallback_names(dl):
    es = _seed(dl, 2)
    v = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    dl.put_vectors([
        {"entry_id": es[0].id, "dim": 8, "model": "fake:test", "vector": vec_to_blob(v)},
        {"entry_id": es[1].id, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([0.99, 0.02, 0, 0, 0, 0, 0, 0]))},
    ])
    report = cluster_report(dl, FakeEmbedder(), llm=None)
    assert report["clusters"][0]["name"].startswith("簇")   # 退化簇号命名


def test_cluster_report_disabled_and_empty(dl):
    assert cluster_report(dl, None, None)["disabled"] is True
    es = _seed(dl, 1)  # 有条目但无向量
    report = cluster_report(dl, FakeEmbedder(), None)
    assert report["clusters"] == [] and "note" in report


# ---- Web API：/api/search?mode=hybrid ----

@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def test_search_hybrid_endpoint_degrades_without_embedder(client, cfg, dl):
    es = _seed(dl, 1)
    r = client.get("/api/search", params={"q": "正文", "mode": "hybrid"})
    assert r.status_code == 200
    body = r.json()
    assert body["effective_mode"] == "fts" and "note" in body
    assert any(h["entry_id"] == es[0].id for h in body["hits"])


def test_search_hybrid_endpoint_with_embedder(cfg, dl, registries, monkeypatch):
    import knowatlas.web.api as wapi

    es = _seed(dl, 1)
    v = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    dl.put_vectors([{"entry_id": es[0].id, "dim": 8, "model": "fake:test",
                     "vector": vec_to_blob(v)}])
    emb = FakeEmbedder(table={"正文": list(v)})
    monkeypatch.setattr("knowatlas.semantic.embed.from_config", lambda cfg: emb)
    app = create_app(cfg, dl, *registries)
    r = TestClient(app, headers={"Host": "127.0.0.1:8420"}).get(
        "/api/search", params={"q": "正文", "mode": "hybrid"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "hybrid" and "note" not in body
    assert any(h["entry_id"] == es[0].id and "fts" in h["reasons"]
               for h in body["hits"])
