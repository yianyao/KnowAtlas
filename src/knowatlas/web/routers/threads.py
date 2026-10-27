"""web/routers/threads.py——线程（列表/详情/建议/摘要/条目归属）（拆分自 web/api.py，URL/响应结构不变）。

本域端点：
- /threads
- /threads-lookup
- /threads
- /threads/{thread_id}
- /threads/{thread_id}/update
- /threads/{thread_id}/delete
- /threads/{thread_id}/items
- /threads/{thread_id}/items/{item_id}/remove
- /threads/{thread_id}/items/{item_id}/update
- /threads/{thread_id}/items/{item_id}/move
- /threads/{thread_id}/suggest
- /threads/{thread_id}/digest
- /entries/{entry_id}/threads
- /entries/{entry_id}/summary
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import JSONResponse

from ..ctx import AppCtx


def register(ctx: AppCtx) -> APIRouter:
    """注册 14 个端点；cfg/dl 等取自 ctx，闭包名与原 api.py 一致。"""
    router = APIRouter()
    cfg, dl, locators, semantics = ctx.cfg, ctx.dl, ctx.locators, ctx.semantics
    # 安全/令牌助手仍归 api.py（函数内导入，避免 api↔routers 循环）
    from ..api import check_write_access

    # ---- Thread 串联工作区（完整方案 §9.4，0.2.0 第三十二批） ----

    def _thread_payload(thread) -> dict:
        """线索详情：items 展开为条目信息（标题/来源/状态），position 即阅读序；
        digest 与各轮 delta_summary 为 LLM 摘要产物（第五十五批，可空）。"""
        items: list[dict[str, Any]] = []
        if thread.items:
            entries = {e.id: e for e in
                       dl.get_entries_by_ids([i.entry_id for i in thread.items])}
            for it in thread.items:
                e = entries.get(it.entry_id)
                items.append({
                    "item_id": it.id, "entry_id": it.entry_id, "position": it.position,
                    "relation_type": it.relation_type, "note": it.note,
                    "title": e.title if e else "（条目已不存在）",
                    "locator": e.locator if e else "",
                    "source_type": e.source_type if e else "",
                    "status": e.status if e else "",
                    "delta_summary": (e.meta.get("delta_summary") or "") if e else "",
                })
        return {"id": thread.id, "name": thread.name, "note": thread.note,
                "thread_type": thread.thread_type, "created_at": thread.created_at,
                "updated_at": thread.updated_at, "digest": thread.digest,
                "items": items}

    @router.get("/threads")
    def list_threads(thread_type: str | None = None):
        return {"threads": dl.list_threads(thread_type=thread_type)}

    @router.get("/threads-lookup")
    def threads_lookup(ids: str = ""):
        """批量查条目所属线索（工作台「线索」视图聚合用，只读免令牌）。

        ids 为逗号分隔 entry_id；不存在/无线索的条目映射为空列表。
        """
        out: dict[str, list[dict]] = {}
        for raw in ids.split(","):
            eid = raw.strip()
            if eid:
                out[eid] = dl.threads_for_entry(eid)
        return {"map": out}

    @router.post("/threads")
    async def create_thread(request: Request):
        """新建线索；entry_ids 一并入库 = 探索路径一键固化（§9.4 路径固化）。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        try:
            thread = dl.create_thread(str(body.get("name", "")),
                                      note=body.get("note"))
        except Exception as exc:  # ContractError 等 → 400
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        added: list[str] = []
        skipped: list[str] = []
        for raw in body.get("entry_ids") or []:
            eid = str(raw).strip()
            if not eid:
                continue
            try:
                dl.add_thread_item(thread.id, eid)
                added.append(eid)
            except Exception:
                skipped.append(eid)  # 不存在/重复——不阻塞其余条目入库
        payload = _thread_payload(dl.get_thread(thread.id))
        payload["added"] = added
        payload["skipped"] = skipped
        return payload

    @router.get("/threads/{thread_id}")
    def get_thread(thread_id: str):
        thread = dl.get_thread(thread_id)
        if thread is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "线索不存在"}},
                                status_code=404)
        return _thread_payload(thread)

    @router.post("/threads/{thread_id}/update")
    async def update_thread(thread_id: str, request: Request):
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        try:
            dl.update_thread(thread_id, name=body.get("name"), note=body.get("note"))
        except Exception as exc:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        return {"id": thread_id}

    @router.post("/threads/{thread_id}/delete")
    async def delete_thread(thread_id: str, request: Request):
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        try:
            dl.delete_thread(thread_id)
        except Exception as exc:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        return {"id": thread_id, "deleted": True}

    @router.post("/threads/{thread_id}/items")
    async def add_thread_item(thread_id: str, request: Request):
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        try:
            item = dl.add_thread_item(thread_id, str(body.get("entry_id", "")),
                                      relation_type=str(body.get("relation_type", "seq")),
                                      note=body.get("note"))
        except Exception as exc:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        return {"item_id": item.id, "entry_id": item.entry_id, "position": item.position,
                "relation_type": item.relation_type}

    @router.post("/threads/{thread_id}/items/{item_id}/remove")
    async def remove_thread_item(thread_id: str, item_id: str, request: Request):
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        try:
            dl.remove_thread_item(thread_id, item_id)
        except Exception as exc:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        return {"id": thread_id, "removed": item_id}

    @router.post("/threads/{thread_id}/items/{item_id}/update")
    async def update_thread_item(thread_id: str, item_id: str, request: Request):
        """改线索条目属性：relation_type（顺承/因果/前置/对比…）与 note。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        relation_type = body.get("relation_type")
        note = body.get("note")
        if relation_type is None and note is None:
            return JSONResponse(
                {"error": {"code": "BAD_REQUEST",
                           "message": "至少给 relation_type 或 note 之一"}},
                status_code=400)
        try:
            dl.update_thread_item(thread_id, item_id,
                                  relation_type=str(relation_type) if relation_type is not None else None,
                                  note=note)
        except Exception as exc:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        return {"id": thread_id, "item_id": item_id}

    @router.post("/threads/{thread_id}/items/{item_id}/move")
    async def move_thread_item(thread_id: str, item_id: str, request: Request):
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        try:
            position = int(body.get("position", 0))
        except (TypeError, ValueError):
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": "position 必须是整数"}},
                                status_code=400)
        try:
            dl.move_thread_item(thread_id, item_id, position)
        except Exception as exc:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        return {"id": thread_id, "item_id": item_id, "position": position}

    @router.post("/threads/{thread_id}/suggest")
    def suggest_thread(thread_id: str, request: Request):
        """thread_suggest：LLM 建议阅读顺序并应用（llm 不可用 = 原序，不写库）。

        同步 def（第五十八批）：LLM 调用可达秒-分钟级，禁止占用事件循环。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        thread = dl.get_thread(thread_id)
        if thread is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "线索不存在"}},
                                status_code=404)
        if not thread.items:
            return {"id": thread_id, "llm_used": False, "applied": False,
                    "order": [], "rationale": "线索为空，无排序对象"}
        from ...semantic.base import TaskContext
        from ...semantic.llm import LlmClient

        entries = {e.id: e for e in
                   dl.get_entries_by_ids([i.entry_id for i in thread.items])}
        items: list[dict[str, Any]] = []
        for it in thread.items:
            e = entries.get(it.entry_id)
            if e is None:
                continue
            body_text = e.inline_content or ""
            if not body_text and e.content_hash:
                body_text = dl.get_content(e.content_hash) or ""
            items.append({"entry_id": e.id, "title": e.title,
                          "body": body_text[:200], "native_path": e.native_path})
        _, suggest = semantics.resolve_task("thread_suggest")
        result = suggest(items, thread.name,
                         TaskContext(run_id="web-threads", llm=LlmClient.from_config(cfg),
                                     config=cfg, datalayer=dl))
        applied = False
        if result.get("llm_used"):
            try:
                dl.reorder_thread_items(thread_id, result["order"])
                applied = True
            except Exception:
                applied = False  # 条目集过期等——建议仍返回供前端手动应用
        return {"id": thread_id, "order": result["order"],
                "rationale": result.get("rationale", ""),
                "llm_used": result.get("llm_used", False), "applied": applied,
                "error": result.get("error")}

    @router.post("/threads/{thread_id}/digest")
    def digest_thread(thread_id: str, request: Request):
        """thread_digest + delta_summarize（第五十五批，§9.4，LLM 摘要后置）。

        delta_summarize：只对缺 meta.delta_summary 的条目跑（省 token），
        产物落 entries.meta.delta_summary；thread_digest：thread 层跑一次，
        产物落 threads.digest。llm 不可用/失败 = 两层都静默降级，不写库，
        线程视图照常显示原始正文（摘要是压缩表示，原始层永在）。
        同步 def（第五十八批）：LLM 调用可达秒-分钟级，禁止占用事件循环。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        thread = dl.get_thread(thread_id)
        if thread is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "线索不存在"}},
                                status_code=404)
        from ...semantic.base import TaskContext
        from ...semantic.llm import LlmClient

        if not thread.items:
            return {"id": thread_id, "llm_used": False, "applied": False,
                    "digest": thread.digest or "", "summaries": {},
                    "rationale": "线索为空，无摘要对象"}
        entries = {e.id: e for e in
                   dl.get_entries_by_ids([i.entry_id for i in thread.items])}
        # 各轮增量正文：邮件条目 inline_content 即 quote_strip 产物；无 inline 的
        # 非 mail 条目回退 content_store（截断），照常参与 thread_digest
        def _delta(e) -> str:
            if e is None:
                return ""
            text = (e.inline_content or "").strip()
            if not text and e.content_hash:
                text = (dl.get_content(e.content_hash) or "").strip()
            return text

        ctx = TaskContext(run_id="web-threads", llm=LlmClient.from_config(cfg),
                          config=cfg, datalayer=dl)
        _, delta_run = semantics.resolve_task("delta_summarize")
        _, digest_run = semantics.resolve_task("thread_digest")

        # ① delta_summarize：缺摘要的条目才跑
        pending = []
        for it in thread.items:
            e = entries.get(it.entry_id)
            if e is not None and not (e.meta.get("delta_summary") or "").strip():
                pending.append({"entry_id": e.id, "title": e.title,
                                "delta": _delta(e)[:2000],
                                "sender": (e.meta.get("from") or ""),
                                "sent_at": (e.meta.get("date") or "")})
        d_result = delta_run(pending, ctx) if pending else {"summaries": {}, "llm_used": False}
        written = 0
        if d_result.get("summaries"):
            for eid, s in d_result["summaries"].items():
                if str(s).strip():
                    dl.merge_meta(eid, {"delta_summary": str(s).strip()})
                    written += 1

        # ② thread_digest：全量轮次跑一次（读全量重新组织，不拼各轮摘要）
        turns = [{"sender": (entries[it.entry_id].meta.get("from") or "") if it.entry_id in entries else "",
                  "sent_at": (entries[it.entry_id].meta.get("date") or "") if it.entry_id in entries else "",
                  "title": entries[it.entry_id].title if it.entry_id in entries else "",
                  "delta": _delta(entries.get(it.entry_id))[:2500]}
                 for it in thread.items if it.entry_id in entries]
        t_result = digest_run(turns, thread.name, ctx) if turns else {"digest": "", "llm_used": False}
        applied = False
        if t_result.get("digest"):
            try:
                dl.set_thread_digest(thread_id, t_result["digest"])
                applied = True
            except Exception:
                applied = False
        llm_used = bool(d_result.get("llm_used")) or bool(t_result.get("llm_used"))
        error = d_result.get("error") or t_result.get("error")
        return {"id": thread_id, "llm_used": llm_used, "applied": applied,
                "digest": t_result.get("digest", ""),
                "summaries": d_result.get("summaries", {}),
                "summarized": written, "error": error}

    @router.get("/entries/{entry_id}/threads")
    def entry_threads(entry_id: str):
        """条目挂在哪些线索里（UI 徽标）。"""
        return {"threads": dl.threads_for_entry(entry_id)}

    @router.get("/entries/{entry_id}/summary")
    def entry_summary(entry_id: str):
        """条目轻量概要（关系图弹窗卡用）：完整 detail 含全文，悬浮场景过重。

        只取正文前缀（substr，不整段进内存），服务端归一空白后截 snippet 至
        160 字符——悬浮卡片不需要长文（第三十七批：400→160 + 前缀读取提速）。
        """
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        head = dl.get_content_preview(entry.content_hash, 2000) \
            if entry.content_hash else ""
        snippet = " ".join((head or "").split())[:160]
        return {
            "id": entry.id, "title": entry.title, "locator": entry.locator,
            "source_type": entry.source_type, "created_at": entry.created_at,
            "snippet": snippet,
            "categories": [{"path": c["path"] or c["name"]}
                           for c in dl.get_entry_categories(entry_id)],
        }

    return router
