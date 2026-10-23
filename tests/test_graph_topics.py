"""关系图知识聚合测试（批次 88）：点向量聚类主题节点 + /api/graph/topics。

点向量与点数据构造复用 test_embed.py 模式（FakeEmbedder hash 向量 +
put_point 直落，绕过 LLM 提炼管线——本批只测聚合层）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from knowatlas.datalayer.db import DataLayer
from knowatlas.models import Entry
from knowatlas.pipeline.embed_index import normalize
from knowatlas.pipeline.graph_topics import topic_clusters
from knowatlas.semantic.embed import vec_to_blob
from knowatlas.web.app import create_app


def _seed_point(dl: DataLayer, entry: Entry, text: str) -> str:
    from knowatlas.pipeline.points import point_hash
    dl.put_point({"content_hash": point_hash(text), "text": text,
                  "summary": "", "source_type": "manual", "judge": "integral",
                  "meta": {}}, {"entry_id": entry.id, "char_offset": 0,
                                "anchor": text[:120]})
    return dl.search_points(text[:4])[0].point_id


def test_topic_clusters_groups_and_names(dl):
    es = [Entry.build(source_type="manual", source_key=f"tp:{i}",
                      title=f"条目{i}", locator=f"https://e.example/{i}",
                      locator_canonical=None, inline_content=f"正文{i}",
                      native_path=None, meta={})
          for i in range(4)]
    dl.upsert_entries(es)
    # 两个语义簇 + 一个落单（正交向量）
    v_git = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    v_py = normalize([0, 1.0, 0, 0, 0, 0, 0, 0])
    v_lonely = normalize([0, 0, 1.0, 0, 0, 0, 0, 0])
    p1 = _seed_point(dl, es[0], "git 提交规范与分支管理策略")
    p2 = _seed_point(dl, es[1], "git 命令行常用操作整理")
    p3 = _seed_point(dl, es[2], "python 装饰器原理与应用")
    p4 = _seed_point(dl, es[3], "完全无关的落单知识点")
    dl.put_point_vectors([
        {"point_id": p1, "dim": 8, "model": "fake:test", "vector": vec_to_blob(v_git)},
        {"point_id": p2, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([0.97, 0.1, 0, 0, 0, 0, 0, 0]))},
        {"point_id": p3, "dim": 8, "model": "fake:test", "vector": vec_to_blob(v_py)},
        {"point_id": p4, "dim": 8, "model": "fake:test", "vector": vec_to_blob(v_lonely)},
    ])
    r = topic_clusters(dl)
    assert r["vectors"] == 4 and r["singles"] == 2 and r["threshold"] == 0.72
    # p1/p2 聚成主题（size 2），p3/p4 落单不成簇（宁缺毋滥）
    assert len(r["topics"]) == 1 and r["topics"][0]["size"] == 2
    t = r["topics"][0]
    assert {p["point_id"] for p in t["points"]} == {p1, p2}
    assert t["sources_count"] == 2
    # 共享词「git」在两个成员文本中可验证（禁发明性命名）
    assert "git" in t["name"]


def test_topic_clusters_insufficient_vectors(dl):
    es = [Entry.build(source_type="manual", source_key="tp:0", title="条目",
                      locator="https://e.example/0", locator_canonical=None,
                      inline_content="正文", native_path=None, meta={})]
    dl.upsert_entries(es)
    _seed_point(dl, es[0], "唯一一个点")
    r = topic_clusters(dl)          # 0 向量
    assert r["topics"] == [] and "note" in r


def test_topic_clusters_unconsumable_source_drops(dl):
    """溯源条目 archived → 点不可消费 → 从主题中剔除。"""
    es = [Entry.build(source_type="manual", source_key=f"tu:{i}",
                      title=f"条目{i}", locator=f"https://e.example/{i}",
                      locator_canonical=None, inline_content="正文",
                      native_path=None, meta={})
          for i in range(3)]
    dl.upsert_entries(es)
    p1 = _seed_point(dl, es[0], "git 提交规范整理")
    p2 = _seed_point(dl, es[1], "git 分支管理策略")
    v = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    dl.put_point_vectors([
        {"point_id": p1, "dim": 8, "model": "fake:test", "vector": vec_to_blob(v)},
        {"point_id": p2, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([0.98, 0.05, 0, 0, 0, 0, 0, 0]))},
    ])
    dl.set_status([es[0].id], "archived")     # p1 溯源不可消费
    r = topic_clusters(dl)
    # p1 剔除后簇内只剩 p1 向量但 hits 无 p1 → 成员 <2 不成簇
    assert all(p2 not in {q["point_id"] for q in t["points"]} or t["size"] >= 2
               for t in r["topics"])
    assert len(r["topics"]) == 0


def test_api_graph_topics_endpoint(cfg, dl, registries, monkeypatch):
    from knowatlas.web.app import create_app as _ca
    app = _ca(cfg, dl, *registries)
    r = TestClient(app, headers={"Host": "127.0.0.1:8420"}).get("/api/graph/topics")
    assert r.status_code == 200
    body = r.json()
    assert "topics" in body and "threshold" in body    # 空库也 200（note 提示）
