"""web/routers/graph.py——图谱（树/总览/子图/检索/径向/反查/主题）（拆分自 web/api.py，URL/响应结构不变）。

本域端点：
- /tree
- /graph/topics
- /graph
- /graph/overview
- /graph/subtree
- /graph/search
- /graph/radiate
- /graph/reverse
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..ctx import AppCtx

# R14：主题聚合进程内缓存。真库 4507 点域一次归簇+合并+命名 3–7 s，而分类页
# 「按主题看」是来回切换的浏览动作——同参数重复访问必须为 0 s。失效靠两点：
# ① 点域指纹（db.points_fingerprint：点数/向量数 + 最新时间，kpoints/ksync 一变即失效）；
# ② 点域签名（本次涉及的 point_id 集合 sha1，改分类/换检索词即换键）。
# TTL 只兜「同数据重复看」这一层，故不必很短；单条响应约 140 KB，8 条 ≈ 1.1 MB。
_TOPICS_TTL = 300.0
_TOPICS_MAX = 8


def register(ctx: AppCtx) -> APIRouter:
    """注册 8 个端点；cfg/dl 等取自 ctx，闭包名与原 api.py 一致。"""
    router = APIRouter()
    cfg, dl, locators, semantics = ctx.cfg, ctx.dl, ctx.locators, ctx.semantics

    @router.get("/tree")
    def tree() -> dict:
        return {"tree": dl.get_tree(), "uncategorized": len(dl.get_uncategorized(limit=1000))}

    # R14 主题聚合缓存：只缓存纯计算结果（返回给调用方的仍是同一份 dict，
    # 序列化不改动它）。并发重复计算不做 single-flight——多算一次只是慢一点，
    # 加锁等别人算完反而会把两类请求串成一条队。
    _topics_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    _topics_lock = threading.Lock()

    def _topics_cached(key: str, compute) -> dict[str, Any]:
        now = time.monotonic()
        with _topics_lock:
            hit = _topics_cache.get(key)
            if hit is not None and now - hit[0] <= _TOPICS_TTL:
                return hit[1]
        result = compute()
        with _topics_lock:
            _topics_cache[key] = (time.monotonic(), result)
            if len(_topics_cache) > _TOPICS_MAX:   # 按写入时间淘汰最旧的
                for stale in sorted(_topics_cache,
                                    key=lambda k: _topics_cache[k][0])[:len(_topics_cache) - _TOPICS_MAX]:
                    _topics_cache.pop(stale, None)
        return result

    @router.get("/graph/topics")
    def graph_topics(limit: int = 80, merge: bool = True,
                     merge_threshold: float = 0.85,
                     q: str = "", category_id: str = "",
                     points_limit: int = 300):
        """知识主题聚合（批次 88，方案 §9：点聚类主题节点，条目退溯源层）。

        全库点向量贪心归簇（阈值 0.72），簇 ≥2 点成主题；主题名=成员共享词
        （禁发明性命名）。零费用零写库，纯查询期计算；点向量未建时返回
        note 提示。试点口径：先看聚合效果再定铺开与下钻交互。

        R11（2026-10-26，工单 变更工单-2026-10-26-R11知识主题top-N.md）：
        真库 4,552 点下全量聚类 + 逐主题命名 378.7 s，故 `limit` 截断（默认
        80、上限 MAX_LIMIT，按点数降序），且只对返回的主题算名字；响应加
        `total`/`limit`/`truncated`——前端据此说明「显示前 N / 共 M 个」。

        R12（2026-10-27，工单 变更工单-2026-10-27-知识主题二次合并与命名去重.md）：
        归簇后按质心再做一遍贪心合并（`merge`，默认开；`merge_threshold`
        默认 0.85、夹到 0.5–0.99），消掉「同一主题被切成多块」造成的重名；
        响应加 `merge_threshold`/`merged_from` 与每主题 `merged`。

        R13（2026-10-27，工单 变更工单-2026-10-27-主题命名补词与检索聚合.md）：
        加检索/分类过滤——`q` 走点 FTS（`points_limit` 条召回）、`category_id`
        走分类子树（条目 → 点），两者给定时取交集；只在点域内聚类（`point_ids`）。
        响应加 `scope`（本次点域），前端检索工作台据此出「主题」tab。

        R14（2026-10-27，工单 变更工单-2026-10-27-分类浏览按主题与主题聚合缓存.md）：
        分类页「按主题看」复用本端点（`category_id`）。真库「人工智能」子树 4507 点
        实测 3–7 s，故加进程内 TTL 缓存（`_TOPICS_TTL`=300 s、`_TOPICS_MAX`=8 条 /
        按写入时间淘汰）。键 = 库路径 + 点域指纹 + 点域签名 + limit/merge/阈值 + scope
        文本；**响应 JSON 不变、无新增 query 参数**。口径代价：同数据同范围最多
        陈旧 300 s，数据一变（kpoints/ksync --embed）立即换键。
        """
        from ...pipeline.graph_topics import MAX_LIMIT, topic_clusters
        mt = max(0.5, min(float(merge_threshold), 0.99))
        cap = max(1, min(int(limit), MAX_LIMIT))
        scope = {"q": q.strip(), "category_id": category_id.strip(),
                 "mode": "all", "points": 0}
        pids: set[str] | None = None
        if scope["category_id"]:
            eids = [e.id for e in dl.get_entries_for_categories(
                dl.subtree_category_ids(scope["category_id"]), limit=2000)]
            by_entry = dl.points_of_entries(eids, text_cap=1)
            pids = {p["id"] for lst in by_entry.values() for p in lst}
            scope["mode"] = "category"
        if scope["q"]:
            n = max(20, min(int(points_limit), 2000))
            qids = {h.point_id for h in dl.search_points(scope["q"], limit=n)}
            pids = qids if pids is None else (pids & qids)
            scope["mode"] = "category+q" if scope["category_id"] else "q"
        # 点域先算（分类口径 25 条目 / 4507 点实测 53 ms），再查缓存：改分类、
        # 换检索词都直接换键，不会拿到别的范围的结果。
        pid_sig = ("-" if pids is None
                   else hashlib.sha1("\n".join(sorted(pids)).encode("utf-8")).hexdigest()[:16])
        ckey = "|".join((str(getattr(dl, "db_path", "")), dl.points_fingerprint(),
                         scope["mode"], scope["q"], scope["category_id"], pid_sig,
                         str(cap), str(int(bool(merge))), f"{mt:.4f}"))
        result = _topics_cached(ckey, lambda: topic_clusters(
            dl, limit=cap, merge=bool(merge), merge_threshold=mt, point_ids=pids))
        scope["points"] = int(result.get("vectors") or 0)
        result["scope"] = scope
        return result

    @router.get("/graph")
    def graph(max_entries: int = 400):
        """关系图数据（结构关系 v0：分类挂接 + 同域名）。保留兼容；新视图见下。"""
        return dl.get_graph_data(max_entries=max_entries)

    @router.get("/graph/overview")
    def graph_overview():
        """大纲图（初始视图）：只含一级大类，value = 子树 active 条目数。"""
        return dl.get_graph_overview()

    @router.get("/graph/subtree")
    def graph_subtree(category_id: str, limit: int = 120, hierarchy: bool = False,
                      compact: bool = False, layer: str = "entries",
                      point_limit: int = 200):
        """下钻图：某分类的子孙分类 + 挂接条目（近 limit 条）+ 祖先链上下文；
        hierarchy=true 纯层级模式（批次 63）：只出下一级子分类，条目在叶子层出现；
        compact=true 稀疏折叠（批次 72）：直挂 ≤2 条的子分类藏条目（folded 徽标），
        分类节点带 depth 供前端分层铺开。
        layer=points（P4，2026-10-26）：第三层由条目卡换成点卡（p:<point_id>，
        可消费点，point_limit 夹紧 1–600）；无点范围自动回退条目层并带 note。"""
        if layer not in ("entries", "points"):
            return JSONResponse(
                {"error": {"code": "BAD_REQUEST",
                           "message": "layer 必须是 entries（条目层）或 points（点层）"}},
                status_code=400)
        data = dl.get_graph_subtree(category_id, limit=limit, hierarchy=hierarchy,
                                    compact=compact, layer=layer,
                                    point_limit=max(1, min(point_limit, 600)))
        if data is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "分类不存在"}},
                                status_code=404)
        return data

    @router.get("/graph/search")
    def graph_search(q: str = "", limit: int = 80):
        """搜索驱动子图：条目标题 / 分类名命中 + 各自分类链与挂接边（按需加载）。"""
        q = q.strip()
        if not q:
            return {"query": q, "nodes": [], "links": []}
        return dl.search_graph(q, limit=limit)

    @router.get("/graph/radiate")
    def graph_radiate(node_id: str, per_channel: int = 8):
        """放射邻域：焦点一跳关联，每节点带 reasons[]、每边带 reason（第三十三批）。"""
        data = dl.radiate(node_id, per_channel=max(1, min(per_channel, 40)))
        if data is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "节点不存在"}},
                                status_code=404)
        return data

    @router.get("/graph/reverse")
    def graph_reverse(node_id: str, limit: int = 20):
        """双向反查：哪些焦点能到达该节点（分类带 path、线索带 thread.html url、
        知识点带溯源条目与分类链——P4 后置项）。"""
        data = dl.reverse_reach(node_id, limit=max(1, min(limit, 50)))
        if data is None:
            return JSONResponse({"error": {"code": "NOT_FOUND",
                                           "message": "节点不存在或不支持反查"}},
                                status_code=404)
        return data

    return router
