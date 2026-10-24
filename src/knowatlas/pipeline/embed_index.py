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


# ---- 点向量（批次 87：点升格检索主体后，语义通道同步点级化） ----

def embed_points(dl: Any, embedder: Any, force: bool = False) -> dict[str, Any]:
    """增量构建点向量索引（与 embed_entries 同纪律）；返回统计 dict。

    点文本 = points.text（截 _TEXT_CAP）；一点多溯源只编码一次（向量挂在
    point_id 上）。force=False 时已有同模型向量的点跳过。
    """
    if embedder is None:
        return {"embedded": 0, "skipped": 0, "no_text": 0, "model": "",
                "disabled": True}
    model = embedder.name
    already = set(dl.all_point_vectors(model)) if not force else set()
    texts = dl.all_points_text()
    embedded = skipped = no_text = 0
    batch: list[dict[str, Any]] = []
    for pid, text in texts.items():
        if pid in already:
            skipped += 1
            continue
        text = text.strip()[:_TEXT_CAP]
        if not text:
            no_text += 1
            continue
        batch.append({"point_id": pid, "text": text})
        if len(batch) >= 32:
            embedded += _flush_points(dl, embedder, batch)
            batch = []
    embedded += _flush_points(dl, embedder, batch)
    return {"embedded": embedded, "skipped": skipped, "no_text": no_text,
            "model": model}


def _flush_points(dl: Any, embedder: Any, batch: list[dict[str, Any]]) -> int:
    if not batch:
        return 0
    vecs = embedder.encode([b["text"] for b in batch])
    dl.put_point_vectors([
        {"point_id": b["point_id"], "dim": len(v), "model": embedder.name,
         "vector": vec_to_blob(normalize(v))}
        for b, v in zip(batch, vecs)
    ])
    return len(batch)


# ---- 点级语义去重（批次 94，用户截图指认「Agent = LLM+上下文+工具」同知识两点） ----

# 同知识判定阈值（余弦）。真库校准（批次 94，114 点全对实测）：真重复对
# 0.9369/0.9426（同书双源各产一点），最近的异知识点 0.8813/0.8932/0.8990
# ——0.92 分界恰好只并真重复；宁漏勿误（漏并下轮可调，误并丢观点）。
_DEDUP_THRESHOLD = 0.92


def dedup_points(dl: Any, threshold: float = _DEDUP_THRESHOLD) -> dict[str, Any]:
    """点级语义去重：点向量余弦 ≥threshold 归同组，组内留最优，副点标 dupe_of。

    content_hash 精确去重（规范化文本相同才合并）拦不住改写措辞的同知识——
    语义向量近似兜底。最优 = 溯源数最多（可信度信号）→ 更早 created_at（知识
    形成顺序）→ id 小（确定性）；副点 merge_meta dupe_of=<保留点 id> 退出消费
    面（search_points/get_point_hit/词云点面 SQL 守卫，批次 94）。**可逆**：
    清 meta.dupe_of 即恢复；溯源指针永不移动/删除，反悔零损失。幂等：已标
    dupe 与 stale 点不参与聚类，重跑结果稳定。
    """
    vecs_raw = dl.all_point_vectors()
    if len(vecs_raw) < 2:
        return {"groups": 0, "dupes": 0, "vectors": len(vecs_raw),
                "threshold": threshold, "note": "点向量不足 2 条"}
    info: dict[str, dict[str, Any]] = {}
    for p in dl.list_points(limit=100000):
        if (p.get("meta") or {}).get("dupe_of"):
            continue                     # 已是副点：幂等重跑不重复处理
        if p.get("aging_flag") == "stale":
            continue                     # 已老化退出消费面：不参与
        info[p["id"]] = p
    vecs = {pid: blob_to_vec(b) for pid, b in vecs_raw.items() if pid in info}
    groups = dupes = 0
    for c in _greedy_clusters(vecs, threshold):
        if len(c["ids"]) < 2:
            continue
        groups += 1
        members = c["ids"]
        best = sorted(members, key=lambda pid: (
            -int(info[pid].get("source_count") or 0),
            str(info[pid].get("created_at") or ""), pid))[0]
        for pid in members:
            if pid == best:
                continue
            dl.merge_meta_of_point(pid, {
                "dupe_of": best,
                "dupe_reason": f"点向量余弦≥{threshold} 同知识组（保留 {best}）"})
            dupes += 1
    if dupes:
        from datetime import datetime
        dl.log_task(datetime.now().astimezone().isoformat(timespec="seconds"),
                    "dedup_points", "run", "points",
                    {"groups": groups, "dupes": dupes, "threshold": threshold})
    return {"groups": groups, "dupes": dupes, "vectors": len(vecs),
            "threshold": threshold}


def search_points_hybrid(dl: Any, embedder: Any, q: str
                         ) -> list[dict[str, Any]] | None:
    """点检索融合（批次 87）：FTS 点命中 + 点向量余弦 → RRF 重排。

    返回 search_points 同构列表（point_id/text/summary/sources/rank，rank 换为
    RRF 分——数值越小越靠前的 bm25 语义不再成立，前端按数组序渲染，rank 仅
    作分数展示）；embedder=None 或查询空 → None（调用方沿用纯 FTS 结果）。
    向量独有点（FTS 零命中但语义相关）同样返回——语义词检索的关键增量。
    """
    if embedder is None or not (q or "").strip():
        return None
    fts_hits = dl.search_points(q.strip())
    fts_rank = {p.point_id: i + 1 for i, p in enumerate(fts_hits)}
    by_id = {p.point_id: p for p in fts_hits}

    qvec = normalize(embedder.encode([q.strip()])[0])
    cands = {pid: blob_to_vec(b) for pid, b in dl.all_point_vectors().items()}
    sim_hits = top_similar(qvec, cands, k=_VEC_POOL, threshold=_SIM_THRESHOLD)

    rrf: dict[str, float] = {}
    for pid, rank in fts_rank.items():
        rrf[pid] = rrf.get(pid, 0.0) + 1.0 / (_RRF_K + rank)
    for i, (pid, _score) in enumerate(sim_hits, 1):
        rrf[pid] = rrf.get(pid, 0.0) + 1.0 / (_RRF_K + i)
        if pid not in by_id:               # 向量独有点：补全溯源信息
            full = dl.get_point_hit(pid)
            if full is not None:
                by_id[pid] = full
    if not rrf:
        return []
    ranked = sorted(rrf, key=lambda pid: -rrf[pid])
    out: list[dict[str, Any]] = []
    for pid in ranked:
        p = by_id.get(pid)
        if p is None:
            continue                       # 溯源全不可消费的点不露面（search_points 同口径）
        src = p if isinstance(p, dict) else {
            "point_id": p.point_id, "text": p.text, "summary": p.summary,
            "sources": p.sources}
        out.append({"point_id": src["point_id"], "text": src["text"],
                    "summary": src["summary"], "sources": src["sources"],
                    "rank": round(rrf[pid], 6), "via_sim": pid not in fts_rank})
    return out


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


def _greedy_clusters(vecs: dict[str, list[float]], threshold: float
                     ) -> list[dict[str, Any]]:
    """贪心归簇（56 批口径，cluster_report 与 60 批 group_hits 共用）：
    按给定顺序遍历，与已有簇心（成员均值向量）比相似度，≥threshold 归入
    最高者，否则自立新簇。返回 [{"ids": [...], "centroid": [...]}, ...]，
    簇序与簇内序 = 输入序（确定性）。"""
    clusters: list[dict[str, Any]] = []
    for eid, vec in vecs.items():
        best, best_score = None, threshold
        for c in clusters:
            score = _dot(vec, c["centroid"])
            if score >= best_score:
                best, best_score = c, score
        if best is None:
            clusters.append({"ids": [eid], "centroid": list(vec)})
        else:
            best["ids"].append(eid)
            n = len(best["ids"])
            best["centroid"] = [
                (x * (n - 1) + y) / n
                for x, y in zip(best["centroid"], vec)]
    return clusters


def cluster_report(dl: Any, embedder: Any, llm: Any,
                   threshold: float = _CLUSTER_THRESHOLD) -> dict[str, Any]:
    """暂存区条目聚类 + LLM 命名候选报告（不建类，人工确认后生效）。

    贪心核心见 _greedy_clusters。LLM 可用时对每簇取成员标题+摘要生成
    「建议分类路径」；不可用退化为「簇N（m 条）」。
    """
    if embedder is None:
        return {"disabled": True, "clusters": [], "unclustered": 0}
    entries = [e for e in dl.get_uncategorized(limit=500)
               if dl.get_vector(e.id) is not None]
    if not entries:
        return {"clusters": [], "unclustered": 0,
                "note": "暂存区无可聚类条目（需先 ksync --embed 建向量）"}

    by_id = {e.id: e for e in entries}
    vecs = {e.id: blob_to_vec(dl.get_vector(e.id)["vector"]) for e in entries}
    clusters = [[by_id[i] for i in c["ids"]]
                for c in _greedy_clusters(vecs, threshold)]

    named: list[dict[str, Any]] = []
    for i, c in enumerate(clusters, 1):
        members = c
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


# ---- 知识集聚合（第六十批，方案 §7.2a：查询期聚合，零数据风险） ----

_EXCERPT_CAP = 120   # 组头代表条目摘句长度


def _row(e: Any) -> dict[str, Any]:
    return {"id": e.id, "title": e.title, "locator": e.locator,
            "source_type": e.source_type}


def _entry_host(locator: str) -> str:
    """URL 条目的 host 信号；非 http(s) 返回空串（文件/会话条目无此信号）。"""
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(locator or "")
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    return parts.hostname or ""


def _excerpt(entries: dict[str, Any], texts: dict[str, str], rep: str) -> str:
    src = texts.get(rep) or entries[rep].title or ""
    return " ".join(src.split())[:_EXCERPT_CAP]


def _word_signals(texts_by_id: dict[str, str], ids: list[str]
                  ) -> list[dict[str, str]]:
    from ..semantic.keywords import shared_words
    return [{"kind": "word", "value": w} for w in
            shared_words([texts_by_id.get(i, "") for i in ids])]


def _path_sets(dl: Any, ids: list[str]) -> list[set[str]]:
    """各成员的挂接路径集合（主分类信号原料；未挂接 = 空集，不造「未分类」）。"""
    out = []
    for i in ids:
        links = dl.get_entry_categories(i)
        out.append({(l["path"] or l["name"]) for l in links})
    return out


def _header(signals: list[dict[str, str]], entries: dict[str, Any],
            texts: dict[str, str], rep: str, ids: list[str]) -> dict[str, Any]:
    return {"size": len(ids), "signals": signals,
            "excerpt": _excerpt(entries, texts, rep),
            "excerpt_title": entries[rep].title,
            "entries": [_row(entries[i]) for i in ids]}


def _semantic_group(dl: Any, cluster: dict[str, Any],
                    entries: dict[str, Any], texts: dict[str, str],
                    vecs: dict[str, list[float]]) -> dict[str, Any]:
    ids = cluster["ids"]
    signals = _word_signals(texts, ids)
    common = set.intersection(*_path_sets(dl, ids))
    if common:  # 组内每条都挂着的最短公共路径（确定性：深度升序、同深字典序）
        signals.append({"kind": "category",
                        "value": min(common, key=lambda p: (p.count("/"), p))})
    hosts = [_entry_host(entries[i].locator) for i in ids]
    if hosts[0] and all(h == hosts[0] for h in hosts):
        signals.append({"kind": "host", "value": hosts[0]})
    rep = max(ids, key=lambda i: _dot(vecs[i], cluster["centroid"]))
    return _header(signals, entries, texts, rep, ids)


def _structural_group(cat: str, host: str, ids: list[str],
                      entries: dict[str, Any], texts: dict[str, str]
                      ) -> dict[str, Any]:
    signals = _word_signals(texts, ids)
    if cat:
        signals.append({"kind": "category", "value": cat})
    if host:
        signals.append({"kind": "host", "value": host})
    return _header(signals, entries, texts, ids[0], ids)


def group_hits(dl: Any, entry_ids: list[str],
               threshold: float = _CLUSTER_THRESHOLD) -> dict[str, Any]:
    """检索命中查询期聚合成「知识集」（第六十批，方案 §7.2a 组头信号化）。

    策略自动选择：≥2 条有向量 → 语义贪心聚类（_greedy_clusters，56 批
    --cluster-report 同款阈值 0.72）；否则 → 「主分类+同 host」结构聚合
    （v0.1 零费用口径——bge-m3 未装机/未 --embed 时检索视图仍有分组）。
    组头 = 成员内容自身信号（共享词/分类/host/代表条目摘句），**禁发明性
    命名**：共享词逐词验证在每个成员文本中出现（keywords.shared_words）。
    纯查询期计算，不写任何表。不成组的条目（无向量/落单/分类 host 均无
    共性）以 singles 平铺，供前端降级渲染。
    """
    seen: list[str] = []
    for i in entry_ids:
        if i and i not in seen:
            seen.append(i)
    entries = {e.id: e for e in dl.get_entries_by_ids(seen)
               if e.status == "active"}
    order = [i for i in seen if i in entries]
    singles = [_row(entries[i]) for i in order]
    if len(order) < 2:
        return {"mode": "none", "groups": [], "singles": singles}
    texts = {i: _entry_text(dl, entries[i]) for i in order}

    vecs: dict[str, list[float]] = {}
    for i in order:
        v = dl.get_vector(i)
        if v is not None:
            vecs[i] = blob_to_vec(v["vector"])

    grouped: set[str] = set()
    groups: list[dict[str, Any]] = []
    mode = "semantic"
    if len(vecs) >= 2:
        for c in _greedy_clusters(vecs, threshold):
            if len(c["ids"]) < 2:
                continue
            grouped.update(c["ids"])
            groups.append(_semantic_group(dl, c, entries, texts, vecs))
    else:
        mode = "structural"
        keys: dict[tuple[str, str], list[str]] = {}
        for i in order:
            links = dl.get_entry_categories(i)
            main = next((l for l in links if l["origin"] == "manual"),
                        links[0] if links else None)
            cat = (main["path"] or main["name"]) if main else ""
            host = _entry_host(entries[i].locator)
            if not cat and not host:
                continue
            keys.setdefault((cat, host), []).append(i)
        for (cat, host), ids in keys.items():
            if len(ids) < 2:
                continue
            grouped.update(ids)
            groups.append(
                _structural_group(cat, host, ids, entries, texts))

    groups.sort(key=lambda g: -g["size"])  # 稳定排序：同大小保持命中序
    singles = [_row(entries[i]) for i in order if i not in grouped]
    return {"mode": mode,
            "threshold": threshold if mode == "semantic" else None,
            "groups": groups, "singles": singles}


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
