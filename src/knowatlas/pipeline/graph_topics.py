"""关系图知识聚合（批次 88，方案 §9：点聚类主题节点，条目退溯源层）。

用户裁决：图聚合是**通用规则**——所有数据源的点都参与，不是 Git 专属；
先 1-2 主题试点看效果再谈铺开口径。试点实现即全量点聚类，前端按需展示。

R11（2026-10-26）：真库 4,552 点下全量聚类 + 逐主题命名 378.7 s，故改为
「numpy 聚类（见 embed_index._greedy_clusters）+ 只对返回的 top-N 主题算名字」；
主题全量仍数千个（1,003 个、平均 2.4 点/簇），整图不可读，故响应默认截断，
并回 `total`/`limit`/`truncated` 让前端说清「显示出多少、总共有多少」。
计算仍是查询期、零费用、零写库。

机制：
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
_DEFAULT_LIMIT = 80        # 默认返回主题数（按点数降序取前 N；R11 口径 A）
MAX_LIMIT = 500            # 端点夹取上限（再大就退回「慢且不可读」）


def topic_clusters(dl: Any, threshold: float = _THRESHOLD,
                   limit: int | None = _DEFAULT_LIMIT) -> dict[str, Any]:
    """全库点聚类 → 知识主题列表（关系图聚合视图数据源）。

    返回 {"topics": [{name, size, points, sources_count}],
          "singles": N, "vectors": N, "threshold": t,
          "total": 主题总数, "limit": 生效上限, "truncated": 是否截断}；
    点向量未建 → {"topics": [], "note": ...}（前端提示先 ksync --embed）。

    limit=None 或 ≤0 → 不截断（返回全部，慢：真库约 30 s 起）；
    主题名只对**截断后返回的**主题计算（命名是第二热点，29 ms/主题）。
    """
    vecs_raw = dl.all_point_vectors()
    if len(vecs_raw) < 2:
        return {"topics": [], "singles": 0, "vectors": len(vecs_raw),
                "threshold": threshold, "total": 0, "limit": limit,
                "truncated": False,
                "note": "点向量不足 2 条——先 ksync --embed 构建点向量索引"}
    vecs = {pid: blob_to_vec(b) for pid, b in vecs_raw.items()}
    hits = {p["point_id"]: p for p in _all_point_hits(dl)}
    singles = 0
    groups: list[list[dict[str, Any]]] = []
    for c in _greedy_clusters(vecs, threshold):
        if len(c["ids"]) < 2:
            singles += 1
            continue
        members = [hits[pid] for pid in c["ids"] if pid in hits]
        if len(members) < 2:            # 向量在但溯源已不可消费的点剔除后不足成簇
            singles += 1
            continue
        groups.append(members)
    groups.sort(key=lambda m: -len(m))  # 稳定排序：同大小保持簇序
    total = len(groups)
    cap = total if not limit or limit <= 0 else min(int(limit), total)
    topics: list[dict[str, Any]] = []
    for members in groups[:cap]:        # 命名只对返回的这批算（R11）
        src_eids = {s["entry_id"] for m in members for s in m["sources"]}
        topics.append({
            "name": _topic_name([m["text"] for m in members]),
            "size": len(members),
            "sources_count": len(src_eids),
            "points": [{"point_id": m["point_id"], "text": m["text"],
                        "summary": m["summary"], "sources": m["sources"]}
                       for m in members],
        })
    return {"topics": topics, "singles": singles, "vectors": len(vecs),
            "threshold": threshold, "total": total, "limit": limit,
            "truncated": cap < total}


def _all_point_hits(dl: Any) -> list[dict[str, Any]]:
    """全点检索视图（可消费溯源过滤 + display_name 标题，search_points 同口径）。

    用 search_points 的空查询 LIKE 兜底太绕，直接组合既有单点接口；
    R11 实测 0.07 ms/点（真库 4,552 点 ≈ 0.3 s），不是热点——不必改批量接口。
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