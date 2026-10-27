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


# ---- R11（2026-10-26 工单 变更工单-2026-10-26-R11知识主题top-N.md） ----

def _seed_three_topics(dl: DataLayer) -> dict[str, list[str]]:
    """三个互不相似的主题（各 2 点）+ 一个落单点，向量 8 维（正交基近邻）。"""
    es = [Entry.build(source_type="manual", source_key=f"tl:{i}",
                      title=f"条目{i}", locator=f"https://e.example/l{i}",
                      locator_canonical=None, inline_content=f"正文{i}",
                      native_path=None, meta={})
          for i in range(7)]
    dl.upsert_entries(es)
    texts = {
        "git": ["git 提交规范与分支策略", "git 命令行常用操作"],
        "py": ["python 装饰器原理", "python 生成器用法"],
        "docker": ["docker 镜像构建", "docker 容器编排"],
        "lonely": ["完全无关的落单知识点"],
    }
    pids: dict[str, list[str]] = {}
    vec_by_text = {
        "git 提交规范与分支策略": [1.0, 0, 0, 0, 0, 0, 0, 0],
        "git 命令行常用操作": [0.98, 0.1, 0, 0, 0, 0, 0, 0],
        "python 装饰器原理": [0, 1.0, 0, 0, 0, 0, 0, 0],
        "python 生成器用法": [0.1, 0.98, 0, 0, 0, 0, 0, 0],
        "docker 镜像构建": [0, 0, 1.0, 0, 0, 0, 0, 0],
        "docker 容器编排": [0, 0.05, 0.99, 0, 0, 0, 0, 0],
        "完全无关的落单知识点": [0, 0, 0, 1.0, 0, 0, 0, 0],
    }
    i = 0
    for key, group in texts.items():
        for text in group:
            from knowatlas.pipeline.points import point_hash
            pid = point_hash(text)[:16]     # 与 put_point 的确定性 id 同源
            dl.put_point({"content_hash": point_hash(text), "text": text,
                          "summary": "", "source_type": "manual",
                          "judge": "integral", "meta": {}},
                         {"entry_id": es[i].id, "char_offset": 0,
                          "anchor": text[:120]})
            i += 1
            dl.put_point_vectors([{"point_id": pid, "dim": 8, "model": "fake:test",
                                   "vector": vec_to_blob(
                                       normalize(vec_by_text[text]))}])
            pids.setdefault(key, []).append(pid)
    return pids


def test_topic_clusters_limit_truncates(dl):
    """limit 截断：total 报全量、truncated=True、topics 只留按点数降序的前 N。"""
    _seed_three_topics(dl)
    r = topic_clusters(dl, limit=2)
    assert r["total"] == 3 and len(r["topics"]) == 2
    assert r["truncated"] is True and r["limit"] == 2
    assert all(t["size"] == 2 for t in r["topics"])


def test_topic_clusters_limit_none_returns_all(dl):
    """limit=None → 不截断（全量口径），truncated=False。"""
    _seed_three_topics(dl)
    r = topic_clusters(dl, limit=None)
    assert r["total"] == 3 and len(r["topics"]) == 3
    assert r["truncated"] is False


def test_api_graph_topics_limit_param(cfg, dl, registries):
    """端点 limit 查询参数生效（默认 80，显式传值回声到响应）。"""
    _seed_three_topics(dl)
    from knowatlas.web.app import create_app as _ca
    app = _ca(cfg, dl, *registries)
    client = TestClient(app, headers={"Host": "127.0.0.1:8420"})
    body = client.get("/api/graph/topics?limit=1").json()
    assert body["limit"] == 1 and len(body["topics"]) == 1
    assert body["total"] == 3 and body["truncated"] is True
    # R12：合并口径回声（三簇互不相似 → 不合并，merged_from = total）
    assert body["merge_threshold"] == 0.85 and body["merged_from"] == body["total"]
    assert all(t["merged"] == 1 for t in body["topics"])
    assert client.get("/api/graph/topics").json()["limit"] == 80


def test_greedy_clusters_numpy_matches_pure():
    """R11 数值等价：numpy 快路径的簇划分/簇内序必须与纯 Python 逐簇相同。"""
    import random

    from knowatlas.pipeline.embed_index import _greedy_clusters, _greedy_pure

    rnd = random.Random(20261026)
    centers = [[rnd.gauss(0, 1) for _ in range(64)] for _ in range(8)]
    vecs: dict[str, list[float]] = {}
    for i in range(300):
        c = centers[i % len(centers)]
        vecs[f"p{i:03d}"] = normalize(
            [x + rnd.gauss(0, 0.15) for x in c])
    fast = _greedy_clusters(vecs, 0.72)      # 300 ≥ _NUMPY_MIN → numpy 路径
    pure = _greedy_pure(vecs, 0.72)
    assert [c["ids"] for c in fast] == [c["ids"] for c in pure]


def test_greedy_clusters_dim_mismatch_falls_back():
    """向量维度不一致（多模型混排）→ 退回纯 Python，不抛异常。"""
    from knowatlas.pipeline.embed_index import _greedy_clusters

    vecs = {f"p{i}": [1.0, 0.0, 0.0] for i in range(70)}
    vecs["p70"] = [1.0, 0.0]                 # 维度不齐
    out = _greedy_clusters(vecs, 0.72)
    assert sum(len(c["ids"]) for c in out) == 71


# ---- R12（2026-10-27 工单 变更工单-2026-10-27-知识主题二次合并与命名去重.md） ----

def test_merge_clusters_joins_near_duplicates():
    """质心余弦 ≥ 阈值就合并（并记录 merged）；正交簇不受影响。"""
    from knowatlas.pipeline.graph_topics import _merge_clusters

    cs = [
        {"ids": ["a1", "a2"], "centroid": normalize([1.0, 0.10, 0, 0, 0, 0, 0, 0])},
        {"ids": ["b1", "b2"], "centroid": normalize([0.98, 0.20, 0, 0, 0, 0, 0, 0])},
        {"ids": ["c1", "c2"], "centroid": normalize([0, 1.0, 0, 0, 0, 0, 0, 0])},
    ]
    out = _merge_clusters(cs, 0.85)
    assert len(out) == 2
    big = max(out, key=lambda c: len(c["ids"]))
    assert big["ids"] == ["a1", "a2", "b1", "b2"] and big["merged"] == 2
    assert min(out, key=lambda c: len(c["ids"]))["ids"] == ["c1", "c2"]


def test_merge_clusters_dim_mismatch_keeps_as_is():
    """维度不齐（多模型混排）→ 原样返回，不做跨维比较。"""
    from knowatlas.pipeline.graph_topics import _merge_clusters

    cs = [{"ids": ["a1", "a2"], "centroid": [1.0, 0.0]},
          {"ids": ["b1", "b2"], "centroid": [1.0, 0.0, 0.0]}]
    assert _merge_clusters(cs, 0.85) is cs


def test_topic_name_unique_and_single_word_has_size():
    """同一响应内重名加②③；只有 1 个共享词时带规模后缀。"""
    from knowatlas.pipeline.graph_topics import _dedupe_name, _topic_name

    used: set[str] = set()
    texts = ["git 提交规范与分支策略", "git 命令行常用操作"]
    n1 = _topic_name(texts, 2, used)
    n2 = _topic_name(texts, 2, used)
    assert n1 != n2 and {n1, n2} <= used
    assert n1.startswith("git") and "2 点" in n1
    assert [_dedupe_name("智能（3 点）", used) for _ in range(3)][1:] == \
        ["智能（3 点）②", "智能（3 点）③"]


def test_topic_clusters_merges_and_reports(monkeypatch):
    """簇被切成两块时：默认合并（total 降、merged 记账），merge=False 退回。"""
    from knowatlas.pipeline import graph_topics as gt

    vecs = {
        "a1": normalize([1.0, 0.10, 0, 0, 0, 0, 0, 0]),
        "a2": normalize([0.99, 0.12, 0, 0, 0, 0, 0, 0]),
        "b1": normalize([0.98, 0.20, 0, 0, 0, 0, 0, 0]),
        "b2": normalize([0.97, 0.22, 0, 0, 0, 0, 0, 0]),
    }

    class FakeDL:
        def all_point_vectors(self):
            return {pid: vec_to_blob(v) for pid, v in vecs.items()}

    hits = [{"point_id": pid, "text": f"git 提交规范与分支管理 {pid}",
             "summary": "", "sources": []} for pid in vecs]
    clusters = [{"ids": ["a1", "a2"], "centroid": vecs["a1"]},
                {"ids": ["b1", "b2"], "centroid": vecs["b1"]}]
    monkeypatch.setattr(gt, "_greedy_clusters", lambda v, t: clusters)
    monkeypatch.setattr(gt, "_all_point_hits", lambda dl: hits)

    r = gt.topic_clusters(FakeDL(), limit=10)
    assert r["total"] == 1 and r["merged_from"] == 2 and r["merge_threshold"] == 0.85
    assert r["topics"][0]["size"] == 4 and r["topics"][0]["merged"] == 2
    assert r["topics"][0]["name"]                      # 名字仍由成员共享词构成

    r2 = gt.topic_clusters(FakeDL(), limit=10, merge=False)
    assert r2["total"] == 2
    assert all(t["merged"] == 1 for t in r2["topics"])


# ---- R13（2026-10-27 工单 变更工单-2026-10-27-主题命名补词与检索聚合.md） ----

def test_merge_clusters_reaches_fixed_point():
    """迭代到不动点：输出里任意两簇的质心余弦都 < 阈值（修「先比后漂」）。"""
    import random

    import numpy as np

    from knowatlas.pipeline.graph_topics import _merge_clusters

    rnd = random.Random(20261027)

    def unit(v):
        a = np.asarray(v, dtype=np.float64)
        return a / np.linalg.norm(a)

    base = unit([rnd.gauss(0, 1) for _ in range(16)])
    centers = [base,
               unit(base + 0.25 * np.asarray([rnd.gauss(0, 1) for _ in range(16)])),
               unit(-base + 0.25 * np.asarray([rnd.gauss(0, 1) for _ in range(16)])),
               unit([rnd.gauss(0, 1) for _ in range(16)])]
    clusters = []
    for i, c in enumerate(centers):
        ids, acc = [], np.zeros(16)
        for j in range(3 + i):
            v = unit(np.asarray(c) + 0.20 * np.asarray(
                [rnd.gauss(0, 1) for _ in range(16)]))
            ids.append(f"c{i}p{j}")
            acc += v
        clusters.append({"ids": ids, "centroid": (acc / len(ids)).tolist()})

    out = _merge_clusters(clusters, 0.85)
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            a, b = out[i]["raw"], out[j]["raw"]
            cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
            assert cos < 0.85, (i, j, cos)


def test_topic_name_uses_second_word_for_single_word_clusters():
    """只共享一个词时补 ≥60% 覆盖的第二词：`grpo·优势` 而不是两个 `grpo（N 点）`。"""
    from knowatlas.pipeline.graph_topics import _topic_name

    texts = ["GRPO 使用组内 reward 归一化计算优势，advantage 除以标准差",
             "GRPO 的 advantage 按组内 reward 归一化，优势对尺度敏感",
             "GRPO 训练时组内奖励归一化决定优势方向"]
    name = _topic_name(texts, 3)
    assert name.startswith("grpo") and "·" in name, name


def test_topic_name_rejects_cross_boundary_pseudo_word():
    """跨词边界的伪词（`智能体应…` → `体应`）不得进名字（jieba token 校验）。"""
    from knowatlas.pipeline.graph_topics import _topic_name

    texts = ["智能体应具备可观测性与回放能力",
             "智能体应按步骤记录决策与工具调用"]
    name = _topic_name(texts, 2)
    assert "体应" not in name, name


def test_topic_clusters_point_ids_filter(dl):
    """point_ids 点域过滤：只在给定点里聚类（检索/分类聚合的底座）。"""
    pids = _seed_three_topics(dl)
    r = topic_clusters(dl, limit=10, point_ids=set(pids["git"]))
    assert r["total"] == 1 and r["topics"][0]["size"] == 2
    assert r["vectors"] == 2
    r2 = topic_clusters(dl, limit=10, point_ids={pids["git"][0]})
    assert r2["topics"] == [] and "note" in r2


def test_api_graph_topics_q_scope(cfg, dl, registries):
    """端点 `?q=`：只聚命中点，响应带 scope（前端「主题」tab 用）。"""
    _seed_three_topics(dl)
    from knowatlas.web.app import create_app as _ca
    app = _ca(cfg, dl, *registries)
    client = TestClient(app, headers={"Host": "127.0.0.1:8420"})
    body = client.get("/api/graph/topics?q=git&limit=10").json()
    assert body["scope"]["q"] == "git" and body["scope"]["mode"] == "q"
    assert body["total"] >= 1 and body["scope"]["points"] >= 2
    assert all("git" in t["name"].lower() or "分支" in t["name"] for t in body["topics"])
    assert client.get("/api/graph/topics").json()["scope"]["mode"] == "all"
