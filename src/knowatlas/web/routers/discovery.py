"""web/routers/discovery.py——发现（统计/词云/时间线/检索/集合）（拆分自 web/api.py，URL/响应结构不变）。

本域端点：
- /stats
- /cloud
- /timeline
- /search
- /sets/group
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...semantic.keywords import word_ok as _cloud_word_ok
from ..ctx import AppCtx


def register(ctx: AppCtx) -> APIRouter:
    """注册 5 个端点；cfg/dl 等取自 ctx，闭包名与原 api.py 一致。"""
    router = APIRouter()
    cfg, dl, locators, semantics = ctx.cfg, ctx.dl, ctx.locators, ctx.semantics

    @router.get("/stats")
    def stats() -> dict:
        return dl.get_stats()

    _CLOUD_PALETTE = ("#d1495b", "#e07a3c", "#c9a227", "#5f9e4e", "#2e9e83",
                      "#2b8fb3", "#3f6fb5", "#63599e", "#8d5aa8", "#b5497e",
                      "#a4485f", "#5f6b7a")

    # 词元噪音表与准入规则已移 semantic/keywords.py（第六十批知识集组头共用），
    # 本文件以 _cloud_word_ok 别名引用，行为不变。

    @router.get("/cloud")
    def cloud(category_id: str | None = None, limit: int = 60, word: str | None = None):
        """词云（第四十三批）：focus 分类子树的分类词元 + 内容词元（scoped cloud）。

        - 范围：category_id 指定的分类子树；缺省 = 全库；
        - 分类词元：focus 直接子分类（点击进入子分类并联动分类树）；
        - 内容词元：子树内可消费条目的标题+内联正文关键词（jieba tf-idf top8/条
          聚合计数，单字/纯数字过滤），带主导顶层分类与 12 色板配色（按词元总量
          降序分配），前端按 √权重折算字号；
        - word=xxx（facet 模式）：追加 entries=当前范围内可消费且含该词的条目列表
          （内容词元点击 = facet 过滤当前范围）。
        """
        data = dl.cloud_data(category_id)
        cat_names = dl.category_names()
        word_counts: dict[str, int] = {}
        word_tops: dict[str, dict[str, int]] = {}
        try:
            import jieba.analyse  # noqa: PLC0415 惰性导入（jieba 是 main 依赖）
        except ImportError:
            jieba = None
        if jieba is not None:
            for _eid, title, body, top in data["entries"]:
                text = f"{title}\n{body[:4000]}"
                for kw, _w in jieba.analyse.extract_tags(text, topK=8, withWeight=True):
                    if not _cloud_word_ok(kw):
                        continue
                    word_counts[kw] = word_counts.get(kw, 0) + 1
                    if top:
                        word_tops.setdefault(kw, {})
                        word_tops[kw][top] = word_tops[kw].get(top, 0) + 1
            # 点词元同池（批次 89，词云点化：点层是知识主体后词云反映知识分布）
            # ——点 text 是提炼后的知识陈述，词频即知识分布；条目词元保留作兜底
            # （未抽点的条目仍出词）。点文本短，topK 6。
            point_rows = dl.cloud_point_data(category_id)
            for ptext, ptop in point_rows:
                for kw, _w in jieba.analyse.extract_tags(ptext, topK=6, withWeight=True):
                    if not _cloud_word_ok(kw):
                        continue
                    word_counts[kw] = word_counts.get(kw, 0) + 1
                    if ptop:
                        word_tops.setdefault(kw, {})
                        word_tops[kw][ptop] = word_tops[kw].get(ptop, 0) + 1
        # 主导顶层分类：该词出现条目中最多的顶层分类；按词元总量降序分配色板槽位
        top_total: dict[str, int] = {}
        for kw, tops in word_tops.items():
            for cid, n in tops.items():
                top_total[cid] = top_total.get(cid, 0) + n
        palette_slot = {cid: i for i, (cid, _n) in enumerate(
            sorted(top_total.items(), key=lambda kv: (-kv[1], kv[0])))}
        words = []
        for kw, n in sorted(word_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
            tops = word_tops.get(kw, {})
            # 主导顶层分类：计数优先，并列取 id 小者（确定性）
            top_cid = (sorted(tops.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                       if tops else None)
            color = (_CLOUD_PALETTE[palette_slot[top_cid] % len(_CLOUD_PALETTE)]
                     if top_cid else "#888")
            words.append({"word": kw, "count": n,
                          "top": {"id": top_cid, "name": cat_names.get(top_cid, "?")} if top_cid else None,
                          "color": color})
        payload: dict[str, Any] = {
            "focus": data["focus"], "categories": data["categories"],
            "words": words, "sampled_entries": len(data["entries"]),
        }
        if word and word.strip():
            payload["word"] = word.strip()
            # 点 facet 优先（批次 89：词云点化——点击词元出知识点而非条目，
            # 裁决 #13 检索漏斗同构）；条目 facet 保留作兜底（未抽点条目）。
            payload["points"] = dl.cloud_facet_points(category_id, word.strip())
            payload["entries"] = [
                {"id": e.id, "title": e.title, "locator": e.locator,
                 "source_type": e.source_type,
                 "snippet": " ".join((e.inline_content or "").split())[:120]}
                for e in dl.cloud_facet(category_id, word.strip(), limit=50)]
        return payload

    @router.get("/timeline")
    def timeline(category_id: str | None = None, granularity: str | None = None,
                 bucket: str | None = None, stale_years: int = 2):
        """时间线（第四十四批）：focus 分类子树按 created_at（内容时间：书签
        收藏/文件创建时间）分桶 + 陈旧叶子分支提醒（长期无新内容，只提醒不改数据）。

        - 范围：category_id 指定的分类子树；缺省 = 全库；
        - 分桶：granularity=year|month|缺省自适应（跨度 >24 个月→year）；
          连续区间补齐空桶；created_at 缺失只进 unknown_count（不编造时间）；
        - bucket=key（如 "2020" / "2020-07"）：追加 entries=该桶可消费条目
          （柱点击下钻；按 exported_at 近序 limit 100）；
        - stale_branches：子树内叶子分类最新条目超 stale_years 年 → 提醒
          清理/归档（age_years 降序）；unknown_branches=时间未知不判陈旧。
        """
        data = dl.timeline_data(category_id, granularity=granularity,
                                bucket=bucket, stale_years=stale_years)
        if bucket:
            data["entries"] = [
                {"id": e.id, "title": e.title, "locator": e.locator,
                 "source_type": e.source_type,
                 "snippet": " ".join((e.inline_content or "").split())[:120]}
                for e in data.get("entries", [])]
        return data

    @router.get("/search")
    def search(q: str = "", mode: str = "fts"):
        # 知识点主通道（批次 86）+ 条目区从点反查（批次 92，裁决 #13：搜概念
        # 词应出该概念论述点非全文概要；条目区=命中点的溯源条目去重为主 +
        # 标题/路径直击保留——词越精确条目越少，正文级全文命中不再单独出条目卡）
        # 批次 87：点向量语义通道——embedder 可用时 FTS 点 + 点向量余弦 RRF
        # 融合重排（语义词如「进销存」零字面命中也能召回），via_sim 标向量独有点
        pts_raw = dl.search_points(q)
        embedder = None
        try:
            from ...pipeline.embed_index import search_points_hybrid
            from ...semantic.embed import from_config as embedder_from_config
            embedder = embedder_from_config(cfg)
            fused = search_points_hybrid(dl, embedder, q) if embedder else None
            pts = fused if fused is not None else [
                {"point_id": p.point_id, "text": p.text, "summary": p.summary,
                 "sources": p.sources, "rank": p.rank}
                for p in pts_raw]
        except ImportError:
            pts = [{"point_id": p.point_id, "text": p.text, "summary": p.summary,
                    "sources": p.sources, "rank": p.rank}
                   for p in pts_raw]

        def _hits_from_points_then_direct() -> list[dict]:
            hits: list[dict] = []
            seen: set[str] = set()
            for p in pts:
                for s in p["sources"]:
                    eid = s["entry_id"]
                    if eid in seen:
                        continue
                    seen.add(eid)
                    hits.append({"entry_id": eid, "title": s["title"],
                                 "locator": s["locator"], "snippet": "",
                                 "via": "point"})
            for h in dl.search_entries_direct(q):
                if h.entry_id in seen:
                    continue
                seen.add(h.entry_id)
                hits.append({"entry_id": h.entry_id, "title": h.title,
                             "locator": h.locator, "snippet": h.snippet,
                             "via": "title"})
            return hits

        if mode == "hybrid":
            # 混合检索（第五十六批，M4）：FTS + 向量余弦 RRF 融合，reasons 可解释；
            # embedder 未启用（配置关/依赖缺）→ 降级 fts + note（探针钉住）
            from ...pipeline.embed_index import hybrid_search
            from ...semantic.embed import from_config as embedder_from_config

            result = hybrid_search(dl, embedder_from_config(cfg), q)
            if result is not None:
                result["points"] = pts
                # 批次 92：条目区与 fts 同口径（点反查+直击为主），hybrid 的
                # sim reasons 挂回对应条目（前端通道合并），语义独有条目殿后
                by_id = {h["entry_id"]: h for h in result.get("hits", [])}
                merged = _hits_from_points_then_direct()
                for h in merged:
                    src = by_id.get(h["entry_id"])
                    if src:
                        h["reasons"] = src.get("reasons", [])
                merged_ids = {m["entry_id"] for m in merged}
                merged += [h for h in result.get("hits", [])
                           if h["entry_id"] not in merged_ids]
                result["hits"] = merged
                return result
            return {"mode": mode, "effective_mode": "fts", "note":
                    "hybrid 依赖向量索引（ksync --embed，需 [embedding] enabled"
                    " + requirements-optional），本次已降级 fts",
                    "points": pts,
                    "hits": _hits_from_points_then_direct()}
        return {"mode": mode, "effective_mode": "fts", "points": pts,
                "hits": _hits_from_points_then_direct()}

    @router.get("/sets/group")
    def sets_group(ids: str = ""):
        """知识集聚合（第六十批，方案 §7.2a 组头信号化；只读查询期聚合，零数据风险）。

        ids=逗号分隔条目 id（≤200，检索工作台合并结果集）。组头 = 成员内容
        自身信号（共享词/分类/host/代表条目摘句），**禁发明性命名**——共享词
        逐词验证在每个成员文本中出现（探针：组头词可在组内任一条目验证）。
        聚合策略自动选择：≥2 条有向量 → 语义贪心聚类（56 批 --cluster-report
        同款，阈值 0.72）；否则 → 「主分类+同 host」结构聚合（v0.1 零费用）。
        同步 def：批量向量/挂接查询走线程池，不占事件循环。
        """
        id_list = [s.strip() for s in ids.split(",") if s.strip()][:200]
        from ...pipeline.embed_index import group_hits
        return group_hits(dl, id_list)

    return router
