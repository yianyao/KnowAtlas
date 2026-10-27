"""web/routers/knowledge.py——知识点（解释/合成/新鲜度/勘误/回忆）（拆分自 web/api.py，URL/响应结构不变）。

本域端点：
- /points/{point_id}/explain
- /synthesize/preview
- /synthesize/commit
- /freshness
- /entries/{entry_id}/unflag-freshness
- /errata
- /errata/points
- /entries/{entry_id}/errata
- /entries/{entry_id}/errata/dismiss
- /points/{point_id}/fact-check/dismiss
- /recall
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi import APIRouter
from fastapi import Body, Request
from fastapi.responses import JSONResponse

from ...models import Entry, FetchResult
from ..ctx import AppCtx, _now_iso


def register(ctx: AppCtx) -> APIRouter:
    """注册 11 个端点；cfg/dl 等取自 ctx，闭包名与原 api.py 一致。"""
    router = APIRouter()
    cfg, dl, locators, semantics = ctx.cfg, ctx.dl, ctx.locators, ctx.semantics
    # 安全/令牌助手仍归 api.py（函数内导入，避免 api↔routers 循环）
    from ..api import check_write_access

    @router.post("/points/{point_id}/explain")
    async def point_explain(point_id: str, request: Request,
                            refresh: int = 0):
        """大白话释疑（批次 90，方案 §9）：点卡片 → LLM 解释+示例。

        结果缓存在点 meta.explain（explanation/examples/explained_at）——重复
        释疑零费用；?refresh=1 强制重释（覆盖缓存）。LLM 调用产生费用，走写
        访问守卫；LLM 未启用返回 503（前端隐藏按钮的兜底提示）。释疑只基于
        点文本（模型自身知识，不联网不编造出处）。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        row = dl._conn.execute(
            "SELECT id, text, summary, meta FROM points WHERE id=?",
            (point_id,)).fetchone()
        if row is None:
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "知识点不存在"}},
                status_code=404)
        meta = json.loads(row["meta"] or "{}")
        if not refresh and meta.get("explain", {}).get("explanation"):
            return {"point_id": point_id, "cached": True, **meta["explain"]}
        from ...semantic.llm import LlmClient
        llm = LlmClient.from_config(cfg)
        if llm is None:
            return JSONResponse(
                {"error": {"code": "LLM_DISABLED",
                           "message": "LLM 未启用——释疑是增强层（[llm] enabled=true）"}},
                status_code=503)
        from ...semantic.base import TaskContext
        from ...semantic.tasks import point_explain as explain_task
        res = explain_task.run({"point_id": point_id, "text": row["text"],
                                "summary": row["summary"]},
                               TaskContext(run_id="web-explain", llm=llm))
        if not res.get("llm_used"):
            return JSONResponse(
                {"error": {"code": "EXPLAIN_FAILED",
                           "message": res.get("error", "释疑失败")}},
                status_code=502)
        payload = {"explanation": res["explanation"], "examples": res["examples"],
                   "explained_at": _now_iso()}
        dl.merge_meta_of_point(point_id, {"explain": payload})
        dl.log_task(_now_iso(), "web", "point_explain", point_id, {})
        return {"point_id": point_id, "cached": False, **payload}

    # ---- 知识梳理合成层（批次 69，§7.9：勾点 → LLM 方案 → 预览 → 人确认落库） ----

    def _synth_items(point_ids: list[str]):
        """取所选点（消费面口径：stale/不可消费点视为不存在——防幻觉闸门不放过期料）。"""
        items, missing = [], []
        for pid in point_ids:
            hit = dl.get_point_hit(pid)
            if hit is None:
                missing.append(pid)
                continue
            src_title = ""
            if hit.sources:
                src_title = hit.sources[0].get("title", "") if isinstance(
                    hit.sources[0], dict) else str(getattr(hit.sources[0], "title", ""))
            items.append({"point_id": hit.point_id, "text": hit.text,
                          "summary": hit.summary or "", "source_title": src_title})
        return items, missing

    @router.post("/synthesize/preview")
    async def synthesize_preview(request: Request):
        """梳理预览：勾选点 + 提示词 → LLM 生成 Markdown（不落库，人确认前零副作用）。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        point_ids = [str(p) for p in (body.get("point_ids") or [])][:30]
        if not point_ids:
            return JSONResponse(
                {"error": {"code": "NO_SOURCES",
                           "message": "未勾选知识点——合成必须溯源（防幻觉闸门）"}},
                status_code=400)
        items, missing = _synth_items(point_ids)
        if not items:
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "所选点不存在或已退出消费面",
                           "missing": missing}},
                status_code=404)
        from ...semantic.llm import LlmClient
        llm = LlmClient.from_config(cfg)
        if llm is None:
            return JSONResponse(
                {"error": {"code": "LLM_DISABLED",
                           "message": "LLM 未启用——合成是增强层（[llm] enabled=true）"}},
                status_code=503)
        from ...semantic.base import TaskContext
        from ...semantic.tasks import synthesize as synth_task
        res = synth_task.run(items, TaskContext(run_id="web-synth", llm=llm),
                             instruction=str(body.get("instruction") or ""))
        if not res.get("llm_used"):
            return JSONResponse(
                {"error": {"code": "SYNTHESIZE_FAILED",
                           "message": res.get("error", "合成失败")}},
                status_code=502)
        dl.log_task(_now_iso(), "web", "synthesize_preview", "preview",
                    {"points": len(items)})
        return {"markdown": res["markdown"], "points": items, "missing": missing}

    @router.post("/synthesize/commit")
    async def synthesize_commit(request: Request):
        """确认落库：预览确认后的 Markdown → source_type=synthesized 独立条目。

        强制溯源（§7.9 设计 2）：meta.sources=[point_id...] 必非空；条目 active
        可检索（回灌），与原始层隔离（source_type 独立标识，前端合成徽标）。
        内容寻址：同一 Markdown 重复确认幂等（upsert unchanged，不产生重复条目）。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        point_ids = [str(p) for p in (body.get("point_ids") or [])][:30]
        markdown = str(body.get("markdown") or "").strip()
        if not point_ids or not markdown:
            return JSONResponse(
                {"error": {"code": "NO_SOURCES",
                           "message": "缺知识点或文档内容——合成必须溯源（防幻觉闸门）"}},
                status_code=400)
        items, missing = _synth_items(point_ids)
        if not items:
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "所选点不存在或已退出消费面",
                           "missing": missing}},
                status_code=404)
        content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        title = str(body.get("title") or "").strip()
        if not title:
            for ln in markdown.splitlines():
                ln = ln.strip()
                if ln.startswith("#"):
                    title = ln.lstrip("#").strip()
                    break
        title = (title or f"合成方案 {datetime.now():%Y-%m-%d %H:%M}")[:120]
        source_key = content_hash[:16]
        entry = Entry.build(
            source_type="synthesized", source_key=source_key, title=title,
            locator=f"synth://{source_key}", locator_canonical=None,
            native_path=None,
            inline_content=markdown if len(markdown) <= 4000 else markdown[:4000],
            content_hash=content_hash if len(markdown) > 4000 else None,
            meta={"sources": [it["point_id"] for it in items],
                  "source_titles": sorted({it["source_title"] for it in items
                                           if it["source_title"]}),
                  "synthesized_at": _now_iso(),
                  "instruction": str(body.get("instruction") or "")[:2000]},
        )
        if entry.content_hash:
            dl.put_content(FetchResult(text=markdown, content_hash=content_hash,
                                       fetcher="synthesize",
                                       fetched_at=_now_iso()))
        dl.upsert_entries([entry])
        dl.log_task(_now_iso(), "web", "synthesize_commit", entry.id,
                    {"points": len(items), "chars": len(markdown)})
        return {"entry_id": entry.id, "title": title, "points": len(items),
                "missing": missing}

    @router.get("/freshness")
    def freshness():
        """时效候选：规则判为「过期/疑似过旧」的条目（第四十一批时效守卫）。

        stale=明确过期（废弃关键词，已退出消费面）；suspect=疑似过旧
        （正文日期过旧 / 同主题已有更新版本，保留可见）。仅标记不自动删——
        保留决定权在用户（否决后 freshness_flag=ok，规则不再标记）。
        """
        def _row(e):
            return {"id": e.id, "title": e.title, "locator": e.locator,
                    "source_type": e.source_type,
                    "reason": e.meta.get("freshness_reason"),
                    "checked_at": e.meta.get("freshness_checked_at")}
        return {"stale": [_row(e) for e in dl.list_by_freshness_flag("stale")],
                "suspect": [_row(e) for e in dl.list_by_freshness_flag("suspect")]}

    @router.post("/entries/{entry_id}/unflag-freshness")
    async def unflag_freshness(entry_id: str, request: Request):
        """用户否决时效判定：置 freshness_flag=ok，之后规则不再标记它。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        if dl.get_entry(entry_id) is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        dl.merge_meta(entry_id, {"freshness_flag": "ok"})
        dl.log_task(_now_iso(), "web", "unflag_freshness", entry_id, {})
        return {"entry_id": entry_id, "freshness_flag": "ok"}

    # ---- 勘误三级 L3（0.2.0 第六十四批，方案 §7.6：附注层不篡改原文） ----

    @router.get("/errata")
    def errata_queue(limit: int = 500):
        """勘误裁决队列：**只出确认级**（meta.errata_flag=error）。

        来源两路：L1 确定性错误（完整代码块语法验证/已移除 API，kerrata --scan
        或 ksync --errata-scan，零费用）与 L2 带依据核查（errata_check，error
        必附 evidence）。疑似（suspect）不到确认级不出裁决队列（方案 §7.6
        防幻觉纪律——防 LLM 幻觉直接废掉正确知识）；errata 附注层条目并显返回。
        """
        out = []
        for e in dl.list_by_errata_flag("error", limit=limit):
            out.append({"id": e.id, "title": e.title, "locator": e.locator,
                        "source_type": e.source_type,
                        "kind": e.meta.get("errata_kind"),
                        "reason": e.meta.get("errata_reason"),
                        "evidence": e.meta.get("errata_evidence"),
                        "errata": e.meta.get("errata") or []})
        return {"entries": out}

    @router.get("/errata/points")
    def errata_points_queue(limit: int = 500):
        """点级勘误裁决队列（P1，2026-10-25）：**只出确认级** wrong。

        只含 `kind=hard` 且 `meta.fact_check.verdict=wrong`、人裁未否决的点；
        suspect 不到确认级不出队（§7.6 防幻觉纪律）。每条附 reason/evidence/
        reason_code 与**溯源**（point_sources → 条目），供人裁时回溯原文。
        只读接口；正确的入口仍是条目级勘误附注（原文永不改写）。
        """
        out = []
        for p in dl.points_wrong_queue(limit=limit):
            fact = (p["meta"].get("fact_check") or {})
            sources = [{"entry_id": s["entry_id"], "title": s.get("title"),
                        "locator": s.get("locator")}
                       for s in dl.point_sources_of(p["id"])]
            out.append({"id": p["id"], "text": p["text"],
                        "reason": fact.get("reason"),
                        "evidence": fact.get("evidence"),
                        "reason_code": fact.get("reason_code"),
                        "at": fact.get("at"), "model": fact.get("model"),
                        "stage": fact.get("stage"), "sources": sources})
        return {"points": out, "count": len(out)}

    @router.post("/entries/{entry_id}/errata")
    async def add_errata(entry_id: str, request: Request):
        """人裁「改正」= 勘误附注层：修正文字挂 meta.errata 追加，**原文永不改写**
        （inline_content/content_store 一字不动，溯源链保住）；附注后清 errata_flag
        （裁决完成，退出裁决队列）。展示时原文+勘误并显（方案 §7.6 定稿口径）。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        body = await request.json()
        text = str(body.get("text", "")).strip()
        if not text:
            return JSONResponse({"error": {"code": "VALIDATION",
                                           "message": "勘误文字不能为空"}},
                                status_code=400)
        note = {"text": text, "evidence": str(body.get("evidence", "")).strip(),
                "at": _now_iso(), "source": "user"}
        notes = list(entry.meta.get("errata") or []) + [note]
        old_flag = entry.meta.get("errata_flag")
        dl.merge_meta(entry_id, {"errata": notes, "errata_flag": None,
                                 "errata_kind": None, "errata_reason": None,
                                 "errata_evidence": None})
        dl.log_task(_now_iso(), "web", "errata_add", entry_id,
                    {"old_flag": old_flag, "note_chars": len(text)})
        return {"entry_id": entry_id, "errata_count": len(notes),
                "original_untouched": True}

    @router.post("/entries/{entry_id}/errata/dismiss")
    async def dismiss_errata(entry_id: str, request: Request):
        """人裁否决（误报）：置 errata_flag=ok，L1/L2 之后不再标记它
        （freshness/unflag 同口径）；裁决动作 task_log 留痕。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        if dl.get_entry(entry_id) is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        dl.merge_meta(entry_id, {"errata_flag": "ok"})
        dl.log_task(_now_iso(), "web", "errata_dismiss", entry_id, {})
        return {"entry_id": entry_id, "errata_flag": "ok"}

    @router.post("/points/{point_id}/fact-check/dismiss")
    async def dismiss_point_fact_check(point_id: str, request: Request):
        """人裁否决（误报）：点级勘误出队（P1b）。

        与条目级 `/api/entries/{id}/errata/dismiss` 同口径：**只让人裁结论出队**，
        点本身、正文、溯源零改动。`verdict`/`reason`/`evidence`/`at` 原样保留，
        便于追溯「为什么曾被判错」；队列 SQL（`points_wrong_queue` 的 dismissed
        过滤）自动出队，不改查询。裁决动作 task_log 留痕。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        point = dl.get_point_meta(point_id)
        if point is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "点不存在"}},
                                status_code=404)
        # 坑：merge_meta_of_point 是**浅**合并，直接写 {"fact_check": {"dismissed": true}}
        # 会把 verdict/reason/evidence 整块抹掉——必须读出整块改完再写回。
        fact = dict(point["meta"].get("fact_check") or {})
        fact["dismissed"] = True
        fact["dismissed_at"] = _now_iso()
        dl.merge_meta_of_point(point_id, {"fact_check": fact})
        dl.log_task(_now_iso(), "web", "point_fact_check_dismiss", point_id,
                    {"verdict": fact.get("verdict", "")})
        return {"point_id": point_id, "dismissed": True,
                "verdict": fact.get("verdict", "")}

    @router.post("/recall")
    def recall(payload: dict = Body(default={})):
        """topic_recall 多路召回（只读，无需写令牌）。

        同步 def（第五十八批）：重计算走 anyio 线程池。曾为 async def 且在
        事件循环上同步执行多路召回查询——一个慢查询即冻结整个 serve（包括
        /api/session），前端表现为「聚合中…」永转圈；事件循环上永远不跑
        重 DB/网络/LLM 调用，是本文件的纪律。
        """
        topic = str(payload.get("topic", "")).strip()
        try:
            limit = max(1, min(int(payload.get("limit", 60)), 200))
        except (TypeError, ValueError):
            limit = 60
        from ...semantic.base import TaskContext

        _, recall_task = semantics.resolve_task("topic_recall")
        return recall_task(topic, TaskContext(run_id="web-recall", datalayer=dl), limit=limit)

    return router
