"""向量数学快路径测试（2026-10-28 工单「检索热路径提速」）。

钉住三件事：
1. numpy 快路径与纯 Python 结果**同序同分**（不因提速改变检索序）；
2. numpy 缺失 / 候选维度不齐 → 回落纯 Python，不抛、不丢结果；
3. BLOB 直连版（`top_similar_blobs`）与 list 版等价；`qvec` 传入后不再重复 encode。
"""

from __future__ import annotations

import sys

import pytest

from knowatlas.datalayer.db import DataLayer
from knowatlas.models import Entry
from knowatlas.pipeline.embed_index import hybrid_search, search_points_hybrid
from knowatlas.semantic.embed import (
    blob_to_vec, cosine, normalize, top_similar, top_similar_blobs, vec_to_blob,
)


# ---- 测试替身 ----

class _CountingEmbedder:
    """记录 encode 调用次数与入参（钉住「qvec 已给就不 encode」）。"""

    def __init__(self, vec: list[float] | None = None):
        self.name = "fake:count"
        self.dim = 8
        self.calls: list[str] = []
        self._vec = vec or _hash_vec("默认")

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.extend(texts)
        return [list(self._vec) for _ in texts]


def _hash_vec(text: str) -> list[float]:
    v = [0.0] * 8
    for ch in text[:24]:
        v[ord(ch) % 8] += 1.0
    return normalize(v)


def _no_numpy(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `import numpy` 变成 ImportError（模拟 optional 依赖缺失的机器）。"""
    monkeypatch.setitem(sys.modules, "numpy", None)


def _pure_python_reference(query: list[float], cands: dict[str, list[float]],
                           k: int, threshold: float) -> list[tuple[str, float]]:
    pairs = [(eid, cosine(query, v)) for eid, v in cands.items()]
    pairs = [(eid, s) for eid, s in pairs if s >= threshold]
    pairs.sort(key=lambda x: -x[1])
    return pairs[:k]


# ---- 1. numpy 快路径与纯 Python 同序同分 ----

def test_top_similar_numpy_matches_python_reference():
    q = normalize([0.7, 0.2, -0.1, 0.5, 0.0, 0.3, -0.4, 0.1])
    cands = {f"p{i}": normalize([float((i * 7) % 5 + 1), float((i * 3) % 4),
                                 -0.5, float(i % 3), 0.2, 0.1, float((i % 2)), -0.3])
             for i in range(40)}
    got = top_similar(q, cands, k=10, threshold=0.0)
    want = _pure_python_reference(q, cands, k=10, threshold=0.0)
    assert [e for e, _ in got] == [e for e, _ in want]
    for (_, a), (_, b) in zip(got, want):
        assert abs(a - b) < 1e-5              # float32 精度内


def test_top_similar_single_candidate_and_threshold():
    """单条候选（asarray 退化成 1-D 的边角）+ 阈值过滤。"""
    q = normalize([1.0, 2.0, 3.0, 4.0])
    one = {"only": [0.0, 0.0, 1.0, 0.0]}
    hits = top_similar(q, one, k=5, threshold=0.0)
    assert len(hits) == 1 and hits[0][0] == "only"
    assert top_similar(q, one, k=5, threshold=0.99) == []


# ---- 2. 回落路径 ----

def test_top_similar_falls_back_without_numpy(monkeypatch):
    _no_numpy(monkeypatch)
    q = normalize([1.0, 0.0, 0.0, 0.0])
    cands = {"a": [0.9, 0.1, 0.0, 0.0], "b": [0.0, 1.0, 0.0, 0.0],
             "c": [0.95, 0.0, 0.3, 0.0]}
    hits = top_similar(q, cands, k=3, threshold=0.5)
    assert [e for e, _ in hits] == \
        [e for e, _ in _pure_python_reference(q, cands, 3, 0.5)]
    # BLOB 版同样回落且与 list 版同序
    blobs = {k: vec_to_blob(v) for k, v in cands.items()}
    assert [e for e, _ in top_similar_blobs(q, blobs, k=3, threshold=0.5)] == \
        [e for e, _ in hits]


def test_top_similar_ragged_candidates_fall_back(monkeypatch):
    """候选维度不齐：numpy 建矩阵会抛 ValueError → 回落纯 Python（不崩）。"""
    q = [1.0, 0.0, 0.0, 0.0]
    cands = {"ok": [1.0, 0.0, 0.0, 0.0], "short": [1.0, 0.0]}
    hits = top_similar(q, cands, k=5, threshold=0.0)
    # 与纯 Python 同口径：长度不齐 cosine=0.0，阈值 0 时仍入选
    assert [e for e, _ in hits] == [e for e, _ in _pure_python_reference(q, cands, 5, 0.0)]
    assert dict(hits)["short"] == 0.0


def test_top_similar_empty_candidates():
    assert top_similar([1.0, 0.0], {}, k=3, threshold=0.0) == []
    assert top_similar_blobs([1.0, 0.0], {}, k=3, threshold=0.0) == []
    # 空 query：历史口径是「长度不齐 → cosine 0.0」，阈值 0 时仍入选（与 list 版一致）
    assert top_similar([], {"a": [1.0, 0.0]}, k=3, threshold=0.0) == [("a", 0.0)]
    assert top_similar_blobs([], {"a": vec_to_blob([1.0, 0.0])},
                             k=3, threshold=0.0) == [("a", 0.0)]


# ---- 3. BLOB 直连版等价性 ----

def test_top_similar_blobs_matches_list_version():
    q = normalize([0.3, -0.2, 0.9, 0.1, 0.4, 0.0, -0.5, 0.2])
    lists = {f"e{i}": normalize([float(i % 4) - 1.0, 0.5, float((i + 1) % 3),
                                 0.2, -0.3, float(i % 2), 0.6, -0.1])
             for i in range(25)}
    blobs = {k: vec_to_blob(v) for k, v in lists.items()}
    a = top_similar(q, lists, k=8, threshold=0.0)
    b = top_similar_blobs(q, blobs, k=8, threshold=0.0)
    assert [e for e, _ in a] == [e for e, _ in b]
    for (_, x), (_, y) in zip(a, b):
        assert abs(x - y) < 1e-5
    # 往返一致性抽检
    k0 = next(iter(blobs))
    assert blob_to_vec(blobs[k0]) == pytest.approx(lists[k0], abs=1e-6)


def test_top_similar_blobs_ragged_blobs_fall_back():
    """BLOB 行长不一致（坏数据）→ 回落 blob_to_vec（不吞掉正确的那条）。"""
    q = [1.0, 0.0, 0.0, 0.0]
    blobs = {"good": vec_to_blob([1.0, 0.0, 0.0, 0.0]),
             "bad": vec_to_blob([1.0, 0.0])}
    hits = top_similar_blobs(q, blobs, k=5, threshold=0.0)
    assert [e for e, _ in hits][0] == "good"
    assert dict(hits)["bad"] == 0.0


# ---- 4. qvec 复用：不再重复 encode ----

def _seed_entry(dl: DataLayer, key: str, title: str) -> Entry:
    e = Entry.build(source_type="manual", source_key=key, title=title,
                    locator=f"https://example.com/{key}", locator_canonical=None,
                    inline_content=f"{title}的正文内容", native_path=None,
                    meta={"source_type": "manual"})
    dl.upsert_entries([e])
    return e


def test_hybrid_search_uses_given_qvec(dl):
    _seed_entry(dl, "hv:1", "部署流程")
    emb = _CountingEmbedder(normalize([1.0, 0, 0, 0, 0, 0, 0, 0]))
    qvec = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    r = hybrid_search(dl, emb, "部署", qvec=qvec)
    assert r is not None and emb.calls == []      # 传了 qvec → 零 encode
    r2 = hybrid_search(dl, emb, "部署")            # 不传 → 自己 encode 一次
    assert r2 is not None and emb.calls == ["部署"]


def test_search_points_hybrid_uses_given_qvec(dl):
    from knowatlas.pipeline.points import point_hash

    e = _seed_entry(dl, "pv:1", "进销存")
    text = "进销存以销售单为核心驱动采购与库存"
    dl.put_point({"content_hash": point_hash(text), "text": text, "summary": "",
                  "source_type": "manual", "judge": "integral", "meta": {}},
                 {"entry_id": e.id, "char_offset": 0, "anchor": text[:120]})
    pid = dl.search_points("进销存")[0].point_id
    dl.put_point_vectors([{"point_id": pid, "dim": 8, "model": "fake:test",
                           "vector": vec_to_blob(normalize([1.0, 0, 0, 0, 0, 0, 0, 0]))}])
    emb = _CountingEmbedder()
    qvec = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    assert search_points_hybrid(dl, emb, "库存管理", qvec=qvec) is not None
    assert emb.calls == []                       # 传了 qvec → 零 encode