"""向量索引与混合检索编排（0.2.0 第五十六批，M4 本地 embedding）。

三件（全部可独立关闭：embedder=None 时各函数按降级纪律返回空/降级路径）：
- embed_entries：对有正文的条目算向量入库（增量：已有同模型向量跳过；
  --embed-force 重算）。正文取 inline_content（邮件条目即 quote_strip 产物）
  优先，缺则 content_store；文本截断 4000 字（bge-m3 8192 token 上限内的保守值）。
- hybrid_search：FTS top + 向量余弦 top → RRF 融合，每条带 reasons
  （fts / sim:<余弦>）——TODO 探针「结果可解释排序理由」。
- cluster_report：暂存区条目贪心聚类 + LLM 为簇命名（§6.2 步骤 3），
  产出候选报告（task_log + 返回值），**不自动建类**——人工确认后用既有
  改类 UI 生效；LLM 不可用时簇名退化为「簇N（m 条）」。

向量是正文的压缩表示：原始层永在，本表可随时重建。
"""

from __future__ import annotations

from typing import Any

from ..semantic.embed import blob_to_vec, normalize, top_similar, vec_to_blob

_TEXT_CAP = 4000          # 单条目送编码的正文截断（字符）
_FTS_POOL = 30            # 混合检索 FTS 侧候选池
_VEC_POOL = 30            # 混合检索向量侧候选池
_RRF_K = 60               # RRF 常数（论文默认）
_SIM_THRESHOLD = 0.5      # 混合检索向量侧入选阈值
_CLUSTER_THRESHOLD = 0.72 # 聚类归簇阈值（bge-m3 余弦经验值；fake 向量另测）


def _entry_text(dl: Any, e: Any) -> str:
    text = (e.inline_content or "").strip()
    if not text and e.content_hash:
        text = (dl.get_content(e.content_hash) or "").strip()
    return text[:_TEXT_CAP]


def embed_entries(dl: Any, embedder: Any, force: bool = False) -> dict[str, Any]:
    """增量构建向量索引；返回 {embedded, skipped, no_text, model}。"""
    if embedder is None:
        return {"embedded": 0, "skipped": 0, "no_text": 0, "model": "",
                "disabled": True}
    model = embedder.name
    already = set(dl.all_vectors(model)) if not force else set()
    embedded = skipped = no_text = 0
    batch: list[dict[str, Any]] = []
    for e in dl.list_entries(limit=50000):
        if e.status != "active":
            continue
        if e.id in already:
            skipped += 1
            continue
        text = _entry_text(dl, e)
        if not text:
            no_text += 1
            continue
        batch.append({"entry": e, "text": text})
        if len(batch) >= 32:  # 分批编码控内存（bge-m3 单卡批 32 稳）
            embedded += _flush(dl, embedder, batch)
            batch = []
    embedded += _flush(dl, embedder, batch)
    return {"embedded": embedded, "skipped": skipped, "no_text": no_text,
            "model": model}


def _flush(dl: Any, embedder: Any, batch: list[dict[str, Any]]) -> int:
    if not batch:
        return 0
    vecs = embedder.encode([b["text"] for b in batch])
    dl.put_vectors([
        {"entry_id": b["entry"].id, "dim": len(v), "model": embedder.name,
         "vector": vec_to_blob(normalize(v))}
        for b, v in zip(batch, vecs)
    ])
    return len(batch)


def hybrid_search(dl: Any, embedder: Any, q: str, limit: int = 20
                  ) -> dict[str, Any] | None:
    """FTS + 向量 RRF 融合检索；embedder=None 返回 None（调用方降级 fts）。

    reasons 可解释：fts 命中记 "fts"，向量命中记 "sim:<余弦>"；最终序 =
    RRF 分（两路排名倒数和，常数 60）。纯 fts 命中条目 reasons=["fts"]。
    """
    if embedder is None or not (q or "").strip():
        return None
    fts_hits = dl.search_fts(q.strip(), limit=_FTS_POOL)
    fts_rank = {h.entry_id: i + 1 for i, h in enumerate(fts_hits)}
    snippets = {h.entry_id: (h.snippet or "") for h in fts_hits}

    qvec = normalize(embedder.encode([q.strip()])[0])
    cands = {eid: blob_to_vec(b) for eid, b in dl.all_vectors().items()}
    sim_hits = top_similar(qvec, cands, k=_VEC_POOL, threshold=_SIM_THRESHOLD)

    rrf: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    for eid, rank in fts_rank.items():
        rrf[eid] = rrf.get(eid, 0.0) + 1.0 / (_RRF_K + rank)
        reasons.setdefault(eid, []).append("fts")
    for i, (eid, score) in enumerate(sim_hits, 1):
        rrf[eid] = rrf.get(eid, 0.0) + 1.0 / (_RRF_K + i)
        reasons.setdefault(eid, []).append(f"sim:{score:.2f}")
    if not rrf:
        return {"query": q, "hits": [], "mode": "hybrid", "vectors": len(cands)}

    entries = {e.id: e for e in dl.get_entries_by_ids(list(rrf))}
    hits: list[dict[str, Any]] = []
    for eid, score in rrf.items():
        e = entries.get(eid)
        if e is None or e.status != "active":
            continue
        hits.append({"entry_id": eid, "title": e.title, "locator": e.locator,
                     "source_type": e.source_type, "score": round(score, 6),
                     "snippet": snippets.get(eid, ""),
                     "reasons": reasons.get(eid, [])})
    hits.sort(key=lambda h: -h["score"])
    return {"query": q, "hits": hits[:limit], "mode": "hybrid",
            "vectors": len(cands)}


def cluster_report(dl: Any, embedder: Any, llm: Any,
                   threshold: float = _CLUSTER_THRESHOLD) -> dict[str, Any]:
    """暂存区条目聚类 + LLM 命名候选报告（不建类，人工确认后生效）。

    贪心：条目按向量序遍历，与已有簇心（成员均值向量）比相似度，
    ≥threshold 归入最高者，否则自立新簇。LLM 可用时对每簇取成员标题+
    摘要生成「建议分类路径」；不可用退化为「簇N（m 条）」。
    """
    if embedder is None:
        return {"disabled": True, "clusters": [], "unclustered": 0}
    entries = [e for e in dl.get_uncategorized(limit=500)
               if dl.get_vector(e.id) is not None]
    if not entries:
        return {"clusters": [], "unclustered": 0,
                "note": "暂存区无可聚类条目（需先 ksync --embed 建向量）"}

    clusters: list[dict[str, Any]] = []  # {members:[entry], centroid:[float]}
    for e in entries:
        vec = blob_to_vec(dl.get_vector(e.id)["vector"])
        best, best_score = None, threshold
        for c in clusters:
            score = _dot(vec, c["centroid"])
            if score >= best_score:
                best, best_score = c, score
        if best is None:
            clusters.append({"members": [e], "centroid": list(vec)})
        else:
            best["members"].append(e)
            n = len(best["members"])
            best["centroid"] = [
                (x * (n - 1) + y) / n
                for x, y in zip(best["centroid"], vec)]

    named: list[dict[str, Any]] = []
    for i, c in enumerate(clusters, 1):
        members = c["members"]
        name = f"簇{i}（{len(members)} 条）"
        if llm is not None and len(members) >= 2:
            lines = "\n".join(
                f"- {m.title}（{(_entry_text(dl, m) or '')[:80]}）"
                for m in members[:12])
            try:
                suggested = (llm.chat(
                    "你是知识库整理助手。给定一组未分类条目的标题与正文片段，"
                    "给这一组起一个 2-8 字的中文分类名，只输出名称本身，"
                    "不要解释、不要标点。", lines) or "").strip().splitlines()
                if suggested and suggested[0].strip():
                    name = suggested[0].strip()[:20]
            except Exception:
                pass  # LLM 故障 → 簇号命名，不阻断报告
        named.append({"name": name, "size": len(members),
                      "entries": [{"id": m.id, "title": m.title,
                                   "locator": m.locator} for m in members]})
    named.sort(key=lambda c: -c["size"])
    from datetime import datetime
    dl.log_task(datetime.now().astimezone().isoformat(timespec="seconds"),
                "cluster_report", "run", "uncategorized",
                {"clusters": len(named), "threshold": threshold})
    return {"clusters": named, "unclustered": 0, "threshold": threshold}


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
