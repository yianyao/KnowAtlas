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
    cluster_report, embed_entries, embed_points, group_hits, hybrid_search,
    search_points_hybrid,
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


# ---- 知识集聚合 group_hits（第六十批，方案 §7.2a 组头信号化） ----

def test_group_hits_semantic_shared_word_verifiable(dl):
    """语义路径：相似向量聚组；组头共享词在**每个成员**文本中可验证（探针）。"""
    es = [
        Entry.build(source_type="manual", source_key="set:a", title="容器部署指南",
                    locator="https://docs.dev.example/dep", locator_canonical=None,
                    inline_content="容器部署前先准备镜像仓库与编排清单文件", native_path=None,
                    meta={}),
        Entry.build(source_type="manual", source_key="set:b", title="容器网络排错",
                    locator="https://docs.dev.example/net", locator_canonical=None,
                    inline_content="容器网络排错先检查桥接模式与端口映射规则", native_path=None,
                    meta={}),
        Entry.build(source_type="manual", source_key="set:c", title="周末菜谱",
                    locator="https://life.example/menu", locator_canonical=None,
                    inline_content="红烧肉做法：焯水后小火慢炖一个小时", native_path=None,
                    meta={}),
    ]
    dl.upsert_entries(es)
    dl.put_vectors([
        {"entry_id": es[0].id, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([1.0, 0, 0, 0, 0, 0, 0, 0]))},
        {"entry_id": es[1].id, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([0.99, 0.05, 0, 0, 0, 0, 0, 0]))},  # 近 a
    ])
    r = group_hits(dl, [e.id for e in es])
    assert r["mode"] == "semantic" and r["threshold"] == 0.72
    assert len(r["groups"]) == 1
    g = r["groups"][0]
    assert g["size"] == 2
    assert {e["id"] for e in g["entries"]} == {es[0].id, es[1].id}
    # 探针：组头词可在组内任一条目验证（子串出现在每条成员标题+正文）
    words = [s["value"] for s in g["signals"] if s["kind"] == "word"]
    assert words, "两条相似成员必有共享词"
    for w in words:
        for e in (es[0], es[1]):
            assert w.lower() in f"{e.title}{e.inline_content}".lower(), w
    assert "excerpt" in g and g["excerpt_title"] in (es[0].title, es[1].title)
    assert {s["id"] for s in r["singles"]} == {es[2].id}


def test_group_hits_structural_fallback_without_vectors(dl):
    """结构路径（v0.1）：无向量按「主分类+同 host」聚合，信号可验证。"""
    dev = dl.create_category("技术开发", [], "manual")
    fe = dl.create_category("前端", [dev.id], "manual")
    es = [
        Entry.build(source_type="manual", source_key="st:1", title="JS 闭包详解",
                    locator="https://blog.dev.example/closure", locator_canonical=None,
                    inline_content="闭包是函数与其词法环境的组合", native_path=None, meta={}),
        Entry.build(source_type="manual", source_key="st:2", title="JS 原型链图解",
                    locator="https://blog.dev.example/proto", locator_canonical=None,
                    inline_content="原型链是对象查找属性的路径", native_path=None, meta={}),
        Entry.build(source_type="manual", source_key="st:3", title="周末爬山记",
                    locator="https://life.example/hill", locator_canonical=None,
                    inline_content="山路六十公里，秋色正好", native_path=None, meta={}),
    ]
    dl.upsert_entries(es)
    dl.attach_category(es[0].id, fe.id, 1.0, "manual", "t")
    dl.attach_category(es[1].id, fe.id, 1.0, "manual", "t")
    r = group_hits(dl, [e.id for e in es])
    assert r["mode"] == "structural" and r["threshold"] is None
    assert len(r["groups"]) == 1 and r["groups"][0]["size"] == 2
    g = r["groups"][0]
    sig = {s["kind"]: s["value"] for s in g["signals"]}
    assert sig["category"] == "技术开发/前端"
    assert g["host"] == "blog.dev.example"       # 批次 96：host 降级为注记字段，不入 signals
    assert {e["id"] for e in g["entries"]} == {es[0].id, es[1].id}
    assert {s["id"] for s in r["singles"]} == {es[2].id}
    # 主分类+同 host 是合取：同分类不同 host 不并入该组
    e4 = Entry.build(source_type="manual", source_key="st:4", title="JS 模块化简史",
                     locator="https://wiki.example/modules", locator_canonical=None,
                     inline_content="模块化演进从命名空间到 ES Module", native_path=None, meta={})
    dl.upsert_entries([e4])
    dl.attach_category(e4.id, fe.id, 1.0, "manual", "t")
    r2 = group_hits(dl, [e.id for e in es] + [e4.id])
    assert {tuple(sorted(e["id"] for e in g["entries"])) for g in r2["groups"]} == {
        tuple(sorted((es[0].id, es[1].id)))}
    assert len(r2["singles"]) == 2


def test_group_hits_no_commonality_all_singles(dl):
    """无共性（分类/host/向量皆无）→ 全部平铺，不发明任何分组。"""
    es = [
        Entry.build(source_type="manual", source_key=f"sg:{i}", title=f"条目{i}",
                    locator=f"https://h{i}.example/{i}", locator_canonical=None,
                    inline_content=f"第{i}篇各不相关的正文", native_path=None, meta={})
        for i in range(3)
    ]
    dl.upsert_entries(es)
    r = group_hits(dl, [e.id for e in es])
    assert r["groups"] == []
    assert [s["id"] for s in r["singles"]] == [e.id for e in es]


def test_sets_group_endpoint(client, dl):
    """端点形状：结构聚合返回组+平铺；空 ids → mode=none。"""
    es = [
        Entry.build(source_type="manual", source_key="ep:1", title="K8s 部署",
                    locator="https://k8s.example/deploy", locator_canonical=None,
                    inline_content="部署清单与滚动更新策略", native_path=None, meta={}),
        Entry.build(source_type="manual", source_key="ep:2", title="K8s 网络",
                    locator="https://k8s.example/net", locator_canonical=None,
                    inline_content="容器网络插件与端口暴露", native_path=None, meta={}),
    ]
    dl.upsert_entries(es)
    r = client.get("/api/sets/group", params={"ids": f"{es[0].id},{es[1].id}"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "structural" and len(body["groups"]) == 1
    sig = {s["kind"]: s["value"] for s in body["groups"][0]["signals"]}
    assert body["groups"][0].get("host") == "k8s.example"  # 无分类无共享词时仍给 host 注记（批次 96 独立字段）
    empty = client.get("/api/sets/group", params={"ids": ""})
    assert empty.json()["mode"] == "none" and empty.json()["groups"] == []


# ---- Web API：/api/search?mode=hybrid ----

def _seed_point(dl: DataLayer, entry: Entry, text: str, summary: str = "") -> None:
    """直接落一个点（绕过 LLM 提炼管线——点向量测试只关心检索层）。"""
    from knowatlas.pipeline.points import point_hash
    dl.put_point({"content_hash": point_hash(text), "text": text,
                  "summary": summary, "source_type": "manual", "judge": "integral",
                  "meta": {}}, {"entry_id": entry.id, "char_offset": 0,
                                "anchor": text[:120]})


# ---- 点向量（批次 87：迁移 009 + embed_points + search_points_hybrid） ----

def test_point_vectors_crud_and_cascade(dl):
    es = _seed(dl, 1)
    _seed_point(dl, es[0], "进销存管理以销售单为核心")
    pid = dl.search_points("进销存")[0].point_id
    assert dl.count_point_vectors() == 0
    dl.put_point_vectors([{"point_id": pid, "dim": 8, "model": "fake:test",
                           "vector": vec_to_blob(_hash_vec(pid))}])
    assert dl.count_point_vectors() == 1
    assert list(dl.all_point_vectors()) == [pid]
    assert list(dl.all_point_vectors("fake:test")) == [pid]
    assert dl.all_point_vectors("other:model") == {}
    # 点删除 → 向量级联（FK ON DELETE CASCADE）
    dl._conn.execute("DELETE FROM points WHERE id=?", (pid,))
    assert dl.count_point_vectors() == 0


def test_embed_points_incremental_force_and_disabled(dl):
    es = _seed(dl, 2)
    _seed_point(dl, es[0], "容器部署先准备镜像仓库")
    _seed_point(dl, es[1], "  ")           # 规范化空文本点
    emb = FakeEmbedder()
    stats = embed_points(dl, emb)
    assert stats["embedded"] == 1 and stats["no_text"] == 1
    assert dl.count_point_vectors() == 1
    # 增量跳过 / force 重算 / 禁用降级
    assert embed_points(dl, emb)["skipped"] == 1
    assert embed_points(dl, emb, force=True)["embedded"] == 1
    assert embed_points(dl, None)["disabled"] is True


def test_search_points_hybrid_fusion_and_pure_sim(dl):
    es = _seed(dl, 2)
    _seed_point(dl, es[0], "进销存以销售单为核心驱动采购与库存",
                summary="进销存概念论述")
    _seed_point(dl, es[1], "周末爬山记，山路六十公里")
    v_jxc = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    dl.put_point_vectors([
        {"point_id": dl.search_points("进销存")[0].point_id, "dim": 8,
         "model": "fake:test", "vector": vec_to_blob(v_jxc)},
    ])
    emb = FakeEmbedder(table={"库存管理": list(v_jxc)})
    # 语义词 query：FTS 零字面命中 → 纯向量召回该点，via_sim=True 且溯源补全
    r = search_points_hybrid(dl, emb, "库存管理")
    assert r is not None and len(r) == 1
    assert r[0]["point_id"] == dl.search_points("进销存")[0].point_id
    assert r[0]["via_sim"] is True
    assert r[0]["sources"] and r[0]["sources"][0]["entry_id"] == es[0].id
    # 字面词 query：FTS + 向量双命中 → RRF 分高于纯 sim，via_sim=False
    r2 = search_points_hybrid(dl, emb, "进销存")
    assert r2[0]["via_sim"] is False and r2[0]["rank"] > 0
    # 不可消费溯源的点（archived）不露面
    dl.set_status([es[0].id], "archived")
    r3 = search_points_hybrid(dl, emb, "库存管理")
    assert r3 == []


def test_search_points_hybrid_none_cases(dl):
    es = _seed(dl, 1)
    _seed_point(dl, es[0], "某知识点")
    assert search_points_hybrid(dl, None, "知识") is None     # 无 embedder
    emb = FakeEmbedder()
    assert search_points_hybrid(dl, emb, "  ") is None        # 空查询
    assert search_points_hybrid(dl, emb, "完全无关词") == []   # 无向量无 FTS


def test_api_search_fuses_point_vectors(cfg, dl, registries, monkeypatch):
    """/api/search：embedder 可用时点区走融合（语义词召回 + via_sim 透出）。"""
    es = _seed(dl, 1)
    _seed_point(dl, es[0], "进销存以销售单为核心驱动采购与库存")
    v = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    dl.put_point_vectors([{"point_id": dl.search_points("进销存")[0].point_id,
                           "dim": 8, "model": "fake:test",
                           "vector": vec_to_blob(v)}])
    emb = FakeEmbedder(table={"库存管理": list(v)})
    monkeypatch.setattr("knowatlas.semantic.embed.from_config", lambda cfg: emb)
    app = create_app(cfg, dl, *registries)
    r = TestClient(app, headers={"Host": "127.0.0.1:8420"}).get(
        "/api/search", params={"q": "库存管理"})
    assert r.status_code == 200
    body = r.json()
    assert any(p["via_sim"] and p["point_id"] == dl.search_points("进销存")[0].point_id
               for p in body["points"])
    # 点反查条目区同步出该条目（via=point）
    assert any(h["entry_id"] == es[0].id and h["via"] == "point"
               for h in body["hits"])



@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def test_search_hybrid_endpoint_degrades_without_embedder(client, cfg, dl):
    es = _seed(dl, 1)
    # 批次 92（裁决 #13）：fts 条目区=点反查+标题直击，正文级命中不再出条目卡——
    # 降级路径用标题直击验证条目区仍可用
    r = client.get("/api/search", params={"q": "条目1", "mode": "hybrid"})
    assert r.status_code == 200
    body = r.json()
    assert body["effective_mode"] == "fts" and "note" in body
    assert any(h["entry_id"] == es[0].id and h["via"] == "title"
               for h in body["hits"])


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
