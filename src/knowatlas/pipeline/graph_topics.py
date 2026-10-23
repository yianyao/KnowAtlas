"""关系图知识聚合（批次 88，方案 §9：点聚类主题节点，条目退溯源层）。

用户裁决：图聚合是**通用规则**——所有数据源的点都参与，不是 Git 专属；
先 1-2 主题试点看效果再谈铺开口径。试点实现即全量点聚类（库内点量小，
贪心 O(n²) 毫秒级），前端按需展示。

机制（零费用零写库，纯查询期计算）：
- 点向量（批次 87 point_vectors）→ _greedy_clusters（56 批同款阈值 0.72）
  贪心归簇，簇 ≥2 点成「知识主题」，落单点不聚合（宁缺毋滥）；
- 主题名 = 组内点文本共享词（keywords.shared_words，逐词在每成员验证，
  **禁发明性命名**——与 60 批 group_hits 组头信号化同纪律），取 top 2
  拼接；无共享词退化「主题N」，不编造；
- 每主题带成员点（text/summary）+ 溯源条目（display_name 覆盖层），前端
  主题节点下钻看点、点反查条目——条目退为溯源层（裁决 #12 闭环）。
"""

from __future__ import annotations

from typing import Any

from .embed_index import _greedy_clusters
from ..semantic.embed import blob_to_vec

_THRESHOLD = 0.72          # 贪心归簇阈值（56/60/88 批统一口径）
_NAME_WORDS = 2            # 主题名共享词上限


def topic_clusters(dl: Any, threshold: float = _THRESHOLD) -> dict[str, Any]:
    """全库点聚类 → 知识主题列表（关系图聚合视图数据源）。

    返回 {"topics": [{name, size, points, sources_count}],
          "singles": N, "vectors": N, "threshold": t}；
    点向量未建 → {"topics": [], "note": ...}（前端提示先 ksync --embed）。
    """
    vecs_raw = dl.all_point_vectors()
    if len(vecs_raw) < 2:
        return {"topics": [], "singles": 0, "vectors": len(vecs_raw),
                "threshold": threshold,
                "note": "点向量不足 2 条——先 ksync --embed 构建点向量索引"}
    vecs = {pid: blob_to_vec(b) for pid, b in vecs_raw.items()}
    hits = {p["point_id"]: p for p in _all_point_hits(dl)}
    singles = 0
    topics: list[dict[str, Any]] = []
    for c in _greedy_clusters(vecs, threshold):
        if len(c["ids"]) < 2:
            singles += 1
            continue
        members = [hits[pid] for pid in c["ids"] if pid in hits]
        if len(members) < 2:            # 向量在但溯源已不可消费的点剔除后不足成簇
            singles += 1
            continue
        name = _topic_name([m["text"] for m in members])
        src_eids = {s["entry_id"] for m in members for s in m["sources"]}
        topics.append({
            "name": name,
            "size": len(members),
            "sources_count": len(src_eids),
            "points": [{"point_id": m["point_id"], "text": m["text"],
                        "summary": m["summary"], "sources": m["sources"]}
                       for m in members],
        })
    topics.sort(key=lambda t: -t["size"])
    return {"topics": topics, "singles": singles, "vectors": len(vecs),
            "threshold": threshold}


def _all_point_hits(dl: Any) -> list[dict[str, Any]]:
    """全点检索视图（可消费溯源过滤 + display_name 标题，search_points 同口径）。

    用 search_points 的空查询 LIKE 兜底太绕，直接组合既有单点接口；
    点量千级内 O(n) 查询可接受（真库 ~114 点）。
    """
    out: list[dict[str, Any]] = []
    for pid in dl.all_points_text():
        h = dl.get_point_hit(pid)
        if h is not None:
            out.append({"point_id": h.point_id, "text": h.text,
                        "summary": h.summary, "sources": [dict(s) for s in h.sources]})
    return out


def _topic_name(texts: list[str]) -> str:
    """主题名 = 成员点文本共享词 top2（逐词验证，禁发明）；无共享词退化「主题N」。"""
    from ..semantic.keywords import shared_words
    words = shared_words(texts)[:_NAME_WORDS]
    if words:
        return "·".join(words)
    return f"主题（{len(texts)} 点）"
