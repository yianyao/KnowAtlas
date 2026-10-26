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

R12（2026-10-27，工单 变更工单-2026-10-27-知识主题二次合并与命名去重.md）：
真库 1,003 主题里 35 个重名（`智能`×14），同名簇质心余弦 66/182 对 ≥0.8
——0.72 单遍贪心把同一主题切成多块，命名只取共享词又放大了观感。故：
① 归簇后加一遍**按规模降序的质心贪心合并**（默认 0.85，`merge=False` 可关，
不用 union-find 以免链式粘连）；② 命名在只有 1 个共享词时补规模后缀
`（N 点）`，同一响应内重名再加圈号 ②③——名字仍只由成员文本里的词构成。
"""

from __future__ import annotations

from typing import Any

from .embed_index import _greedy_clusters
from ..semantic.embed import blob_to_vec

_THRESHOLD = 0.72          # 贪心归簇阈值（56/60/88 批统一口径）
_MERGE_THRESHOLD = 0.85    # R12 二次合并阈值：真库实测 0.85 是拐点（见工单）
_NAME_WORDS = 2            # 主题名共享词上限
_DEFAULT_LIMIT = 80        # 默认返回主题数（按点数降序取前 N；R11 口径 A）
MAX_LIMIT = 500            # 端点夹取上限（再大就退回「慢且不可读」）


def topic_clusters(dl: Any, threshold: float = _THRESHOLD,
                   limit: int | None = _DEFAULT_LIMIT,
                   merge: bool = True,
                   merge_threshold: float = _MERGE_THRESHOLD) -> dict[str, Any]:
    """全库点聚类 → 知识主题列表（关系图聚合视图数据源）。

    返回 {"topics": [{name, size, merged, points, sources_count}],
          "singles": N, "vectors": N, "threshold": t,
          "total": 主题总数, "limit": 生效上限, "truncated": 是否截断,
          "merge_threshold": 合并阈值, "merged_from": 合并前成簇数}；
    点向量未建 → {"topics": [], "note": ...}（前端提示先 ksync --embed）。

    limit=None 或 ≤0 → 不截断（返回全部，慢：真库约 30 s 起）；
    主题名只对**截断后返回的**主题计算（命名是第二热点，29 ms/主题）。
    merge=False → 退回 R11 口径（不做二次合并）。
    """
    vecs_raw = dl.all_point_vectors()
    if len(vecs_raw) < 2:
        return {"topics": [], "singles": 0, "vectors": len(vecs_raw),
                "threshold": threshold, "total": 0, "limit": limit,
                "truncated": False, "merge_threshold": merge_threshold,
                "merged_from": 0,
                "note": "点向量不足 2 条——先 ksync --embed 构建点向量索引"}
    vecs = {pid: blob_to_vec(b) for pid, b in vecs_raw.items()}
    hits = {p["point_id"]: p for p in _all_point_hits(dl)}
    singles = 0
    clusters: list[dict[str, Any]] = []
    for c in _greedy_clusters(vecs, threshold):
        ids = [pid for pid in c["ids"] if pid in hits]
        if len(ids) < 2:                # 向量在但溯源已不可消费的点剔除后不足成簇
            singles += 1
            continue
        clusters.append({"ids": ids, "centroid": c["centroid"]})
    clusters.sort(key=lambda c: -len(c["ids"]))   # 稳定排序：同大小保持簇序
    merged_from = len(clusters)
    if merge and merged_from > 1:       # R12：同一主题被切成多块时并回去
        clusters = _merge_clusters(clusters, merge_threshold)
    total = len(clusters)
    cap = total if not limit or limit <= 0 else min(int(limit), total)
    topics: list[dict[str, Any]] = []
    used: set[str] = set()              # 同一响应内主题名唯一（R12）
    for c in clusters[:cap]:            # 命名只对返回的这批算（R11）
        members = [hits[pid] for pid in c["ids"]]
        src_eids = {s["entry_id"] for m in members for s in m["sources"]}
        # 命名用「种子簇」（合并前最大的那一簇）：合并后成员变多，全成员共享词
        # 会更稀（真库实测 26 簇并成 1 个 113 点主题后只剩泛名），而种子簇才是
        # 该主题的原型；规模后缀仍报合并后的总点数。
        seed = [hits[pid] for pid in c.get("seed") or c["ids"]]
        topics.append({
            "name": _topic_name([m["text"] for m in seed], len(members), used),
            "size": len(members),
            "merged": int(c.get("merged") or 1),
            "sources_count": len(src_eids),
            "points": [{"point_id": m["point_id"], "text": m["text"],
                        "summary": m["summary"], "sources": m["sources"]}
                       for m in members],
        })
    return {"topics": topics, "singles": singles, "vectors": len(vecs),
            "threshold": threshold, "total": total, "limit": limit,
            "truncated": cap < total, "merge_threshold": merge_threshold,
            "merged_from": merged_from}


def _merge_clusters(clusters: list[dict[str, Any]], threshold: float
                    ) -> list[dict[str, Any]]:
    """R12 二次合并：按规模降序的质心贪心合并（非 union-find，避免链式粘连）。

    调用方保证 clusters 已按点数降序：大主题先立，小块并过去，簇心按点数加权
    更新（= 成员均值，与 _greedy_clusters 的簇心口径一致）。任一环节不满足
    （numpy 缺失 / 维度不齐）就原样返回——宁可不合并，也不做跨维比较或慢循环。
    """
    try:
        import numpy as np  # noqa: PLC0415 numpy 是主依赖，缺失时降级不合并
    except ImportError:
        return clusters
    if len({len(c["centroid"]) for c in clusters}) != 1:
        return clusters                 # 多模型混排维度不齐 → 不做跨维比较
    merged: list[dict[str, Any]] = []
    for c in clusters:
        raw = np.asarray(c["centroid"], dtype=np.float64)
        norm = float(np.linalg.norm(raw))
        # 簇心是成员均值，模长普遍 <1：直接点积会系统性低估相似度（真库实测
        # 0.85 阈值下零合并），故统一投影到单位球再比（= 余弦，与归簇口径一致）
        unit = raw / norm if norm else raw
        if merged:
            sims = np.array([float(unit @ m["unit"]) for m in merged])
            best = int(sims.argmax())
            if sims[best] >= threshold:
                m = merged[best]
                n0, n1 = len(m["ids"]), len(c["ids"])
                m["raw"] = (m["raw"] * n0 + raw * n1) / (n0 + n1)
                rn = float(np.linalg.norm(m["raw"]))
                m["unit"] = m["raw"] / rn if rn else m["unit"]
                m["ids"] = m["ids"] + c["ids"]
                m["merged"] = int(m.get("merged") or 1) + int(c.get("merged") or 1)
                continue
        merged.append({"ids": list(c["ids"]), "raw": raw, "unit": unit,
                       "seed": list(c["ids"]),
                       "merged": int(c.get("merged") or 1)})
    return merged


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


_CIRCLED = "①②③④⑤⑥⑦⑧⑨"


def _topic_name(texts: list[str], size: int | None = None,
                used: set[str] | None = None) -> str:
    """主题名 = 成员点文本共享词 top2（逐词验证，禁发明）；无共享词退化「主题N」。

    R12（2026-10-27）：只命中 1 个共享词时单词名没有区分度（真库 `智能`×14），
    补规模后缀 `（N 点）`；传入 used 时再做同响应内去重（②③…）。
    """
    from ..semantic.keywords import shared_words
    words = shared_words(texts)[:_NAME_WORDS]
    n = len(texts) if size is None else size
    if len(words) >= 2:
        base = "·".join(words[:2])
    elif words:
        base = f"{words[0]}（{n} 点）"
    else:
        base = f"主题（{n} 点）"
    return _dedupe_name(base, used)


def _dedupe_name(base: str, used: set[str] | None) -> str:
    """把 base 写进 used 并保证唯一：重复时依次加 ②③…（超 9 用 `(k)`）。"""
    if used is None:
        used = set()
    name, k = base, 1
    while name in used:
        k += 1
        suffix = _CIRCLED[k - 1] if 2 <= k <= len(_CIRCLED) else f"({k})"
        name = f"{base}{suffix}"
    used.add(name)
    return name