"""REST 端点（完整方案 §8）+ H5 五条安全约束。

安全约束（仅绑 127.0.0.1 不够——挡不住 CSRF 与 DNS rebinding）：
1. Host 校验；2. Origin 校验；3. 写操作 X-KnowAtlas-Token；4. content-type 白名单；
5. CORS 不放宽（bookmarklet 的 no-cors POST 把 token 放 query 参数 ?token=）。
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

_TOKEN_HEADER = "x-knowatlas-token"
_WRITE_COOKIE = "knowatlas_write"  # 同源自动写凭据（HttpOnly，JS 读不到明文）


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def token_fingerprint(token: str) -> str:
    """令牌指纹（sha256 前 8 位）——供人与服务核对，**绝不回传明文令牌**。

    为什么需要（0.2.0 第十六批，用户连续两次"配了环境变量还是用不了"）：
    令牌不匹配的常见原因有三——①网页弹窗里填的值与服务端实际读到的不是同一个；
    ②配完环境变量没重启 serve（进程启动时读一次）；③同名环境变量在"系统级/用户级"
    两处都存在时被另一级覆盖。指纹让这三类问题都能一眼核对，不必反复试。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8] if token else ""


def _port_of(cfg: Any) -> int:
    return int(cfg.get("general.server_port", 8420))


def check_write_access(request: Request, cfg: Any) -> JSONResponse | None:
    """写操作守卫：Host/Origin 已由中间件校验，这里查 token 与 content-type。"""
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return JSONResponse(
            {"error": {"code": "UNSUPPORTED_MEDIA_TYPE", "message": "写操作仅收 application/json"}},
            status_code=415,
        )
    token_env = str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN"))
    expected = os.environ.get(token_env, "")
    if not expected:
        return JSONResponse(
            {"error": {"code": "TOKEN_NOT_CONFIGURED",
                       "message": f"环境变量 {token_env} 未设置，写端点不可用"}},
            status_code=503,
        )
    supplied = (request.headers.get(_TOKEN_HEADER)
                or request.cookies.get(_WRITE_COOKIE, "")
                or request.query_params.get("token", ""))
    if supplied != expected:
        return JSONResponse(
            {"error": {"code": "FORBIDDEN",
                       "message": (f"写操作需 {_TOKEN_HEADER} 头（或 ?token=，bookmarklet 用）；"
                                   f"服务端当前令牌指纹={token_fingerprint(expected)}（见 serve 启动日志）。"
                                   "不匹配最常见三因：①弹窗里填的值与服务端不是同一个；"
                                   "②配完环境变量没重启 serve；③同名环境变量在系统级/用户级两处都有、被另一级覆盖。")}},
            status_code=403,
        )
    return None


def install_security_middleware(app: FastAPI, cfg: Any) -> None:
    """Host / Origin 校验（约束 1、2）。"""
    port = _port_of(cfg)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    @app.middleware("http")
    async def _host_origin_guard(request: Request, call_next):  # noqa: ANN202
        host = request.headers.get("host", "")
        if host not in allowed_hosts:
            return JSONResponse(
                {"error": {"code": "FORBIDDEN_HOST",
                           "message": f"Host 不在白名单：{host}（防 DNS rebinding）"}},
                status_code=403,
            )
        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            return JSONResponse(
                {"error": {"code": "FORBIDDEN_ORIGIN",
                           "message": f"Origin 不在白名单：{origin}（防 CSRF）"}},
                status_code=403,
            )
        return await call_next(request)


def register_routes(app: FastAPI, cfg: Any, dl: Any, locators: Any, semantics: Any) -> None:
    from ..pipeline.kadd import ensure_category_path, ingest_url

    @app.get("/api/stats")
    def stats() -> dict:
        return dl.get_stats()

    @app.get("/api/token-hint")
    def token_hint() -> dict:
        """令牌核对辅助：只给**指纹**（sha256 前 8 位）与来源，永不回传明文。"""
        env_name = str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN"))
        tok = os.environ.get(env_name, "")
        return {"env_name": env_name, "fingerprint": token_fingerprint(tok),
                "configured": bool(tok)}

    @app.get("/api/session")
    def session(response: Response) -> dict:
        """页面打开时调用一次：服务端把写令牌种进 HttpOnly Cookie，之后浏览器的
        同源请求自动携带——**用户不需要手工填任何令牌**（0.2.0 第十七批）。

        防护不降级：cookie 是 HttpOnly（JS 读不到明文）+ SameSite=Strict（跨站请求
        不携带）+ 绑定 127.0.0.1 域（别的站点拿不到），Host/Origin 校验照旧。
        """
        env_name = str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN"))
        tok = os.environ.get(env_name, "")
        if tok:
            response.set_cookie(_WRITE_COOKIE, tok, httponly=True,
                                samesite="strict", path="/")
        return {"env_name": env_name, "fingerprint": token_fingerprint(tok),
                "configured": bool(tok), "cookie": _WRITE_COOKIE if tok else ""}

    @app.get("/api/tree")
    def tree() -> dict:
        return {"tree": dl.get_tree(), "uncategorized": len(dl.get_uncategorized(limit=1000))}

    @app.get("/api/categories/{category_id}/entries")
    def category_entries(category_id: str, source_type: str | None = None):
        """该分类子树（含自身，多父去重）下的 active 条目列表。"""
        if dl.get_category(category_id) is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "分类不存在"}},
                                status_code=404)
        entries = dl.get_entries_for_categories(
            dl.subtree_category_ids(category_id), source_type=source_type, limit=500)
        return {"category_id": category_id,
                "paths": dl.get_category_paths(category_id),
                "entries": [{"id": e.id, "title": e.title, "locator": e.locator,
                             "source_type": e.source_type, "status": e.status} for e in entries]}

    @app.get("/api/uncategorized")
    def uncategorized(limit: int = 200):
        """暂存区：未挂任何分类的 active 条目。"""
        entries = dl.get_uncategorized(limit=limit)
        return {"entries": [{"id": e.id, "title": e.title, "locator": e.locator,
                             "source_type": e.source_type, "native_path": e.native_path}
                            for e in entries]}

    @app.post("/api/entries/{entry_id}/reject")
    async def reject_entry(entry_id: str, request: Request):
        """用户明确舍弃：状态置 rejected——不入树/检索/图，重新同步永不复活。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        dl.set_status([entry_id], "rejected")
        dl.log_task(_now_iso(), "web", "reject", entry_id, {"old_status": entry.status})
        return {"entry_id": entry_id, "status": "rejected"}

    @app.post("/api/entries/{entry_id}/restore")
    async def restore_entry(entry_id: str, request: Request):
        """从 rejected 恢复为 active（误舍弃的后悔药）。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        dl.set_status([entry_id], "active")
        dl.log_task(_now_iso(), "web", "restore", entry_id, {"old_status": entry.status})
        return {"entry_id": entry_id, "status": "active"}

    @app.get("/api/rejected")
    def rejected_entries(limit: int = 500):
        """已舍弃条目列表（查看/恢复入口）。"""
        rows = dl.list_entries(status="rejected", limit=limit)
        return {"entries": [{"id": e.id, "title": e.title, "locator": e.locator,
                             "source_type": e.source_type} for e in rows]}

    @app.get("/api/dead-links")
    def dead_links():
        """失效链接（体检 dead）与疑似临时故障（error）清单。"""
        return {
            "dead": [{"id": e.id, "title": e.title, "locator": e.locator,
                      "code": e.meta.get("link_code"),
                      "checked_at": e.meta.get("link_checked_at")}
                     for e in dl.list_by_link_status("dead")],
            "error": [{"id": e.id, "title": e.title, "locator": e.locator,
                       "code": e.meta.get("link_code"),
                       "checked_at": e.meta.get("link_checked_at")}
                      for e in dl.list_by_link_status("error")],
        }

    @app.get("/api/not-knowledge")
    def not_knowledge():
        """待清理候选：判为「非具体知识」（站点门户/资源列表/纯资源）的条目。

        两个来源：L0 价值守卫（URL 结构规则，meta.value_flag_reason 记原因：
        resource_file / portal_homepage / index_subdir）与 LLM 语义判断
        （classify_deep kind=non，无 reason）。仅标记不自动舍弃——保留决定权在用户。
        """
        return {"entries": [{"id": e.id, "title": e.title, "locator": e.locator,
                             "source_type": e.source_type,
                             "reason": e.meta.get("value_flag_reason")}
                            for e in dl.list_by_value_flag("not_knowledge")]}

    @app.post("/api/entries/{entry_id}/unflag")
    async def unflag_entry(entry_id: str, request: Request):
        """用户否决非知识判定（规则或 LLM）：置 value_flag=ok，之后两者都不再标记。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        if dl.get_entry(entry_id) is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        dl.merge_meta(entry_id, {"value_flag": "ok"})
        dl.log_task(_now_iso(), "web", "unflag_not_knowledge", entry_id, {})
        return {"entry_id": entry_id, "value_flag": "ok"}

    @app.get("/api/graph")
    def graph(max_entries: int = 400):
        """关系图数据（结构关系 v0：分类挂接 + 同域名）。保留兼容；新视图见下。"""
        return dl.get_graph_data(max_entries=max_entries)

    @app.get("/api/graph/overview")
    def graph_overview():
        """大纲图（初始视图）：只含一级大类，value = 子树 active 条目数。"""
        return dl.get_graph_overview()

    @app.get("/api/graph/subtree")
    def graph_subtree(category_id: str, limit: int = 120):
        """下钻图：某分类的子孙分类 + 挂接条目（近 limit 条）+ 祖先链上下文。"""
        data = dl.get_graph_subtree(category_id, limit=limit)
        if data is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "分类不存在"}},
                                status_code=404)
        return data

    @app.get("/api/graph/search")
    def graph_search(q: str = "", limit: int = 80):
        """搜索驱动子图：条目标题 / 分类名命中 + 各自分类链与挂接边（按需加载）。"""
        q = q.strip()
        if not q:
            return {"query": q, "nodes": [], "links": []}
        return dl.search_graph(q, limit=limit)

    @app.post("/api/entries/{entry_id}/recategorize")
    async def recategorize(entry_id: str, request: Request):
        """人工校正：条目改挂目标分类（按路径，不存在则自动建，origin=manual）。

        机器来源旧分类被摘除；人工校正（manual）永不覆盖（H3）。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        target_path = str(body.get("target_path", "")).strip().strip("/")
        if not target_path:
            return JSONResponse({"error": {"code": "BAD_REQUEST",
                                           "message": "缺少 target_path（如 技术开发/前端）"}},
                                status_code=400)
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        old_links = dl.get_entry_categories(entry_id)
        old_paths = [l["path"] for l in old_links if l["origin"] != "manual"]
        cid = ensure_category_path(dl, target_path, "manual")
        # 人工迁移语义：替换全部旧挂接（含旧 manual）——"manual 永不覆盖"约束的是
        # 机器来源（H3），不约束人工自己的后续校正
        for link in old_links:
            if link["category_id"] != cid:
                dl.detach_category(entry_id, link["category_id"])
        dl.attach_category(entry_id, cid, 1.0, "manual", "web-recategorize")
        dl.log_task(_now_iso(), "web", "recategorize", entry_id,
                    {"old_paths": [l["path"] for l in old_links], "new_path": target_path})
        return {"entry_id": entry_id, "category_path": target_path}

    @app.post("/api/categories")
    async def create_category(request: Request):
        """新建分类节点（父可选；无父 = 顶层）。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        name = str(body.get("name", "")).strip()
        parent_ids = [str(p) for p in body.get("parent_ids", []) if str(p).strip()]
        try:
            cat = dl.create_category(name, parent_ids, origin="manual")
        except Exception as exc:  # ContractError 等 → 400
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        dl.log_task(_now_iso(), "web", "create_category", cat.id,
                    {"name": name, "parent_ids": parent_ids})
        return {"id": cat.id, "name": cat.name}

    @app.post("/api/categories/{category_id}/rename")
    async def rename_category(category_id: str, request: Request):
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        new_name = str(body.get("name", "")).strip()
        old = dl.get_category(category_id)
        if old is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "分类不存在"}},
                                status_code=404)
        try:
            dl.rename_category(category_id, new_name)
        except Exception as exc:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        dl.log_task(_now_iso(), "web", "rename_category", category_id,
                    {"old": old.name, "new": new_name})
        return {"id": category_id, "name": new_name}

    @app.post("/api/categories/{category_id}/move")
    async def move_category(category_id: str, request: Request):
        """移动分类到新父（parent_ids 为空 = 移到顶层）。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        parent_ids = [str(p) for p in body.get("parent_ids", []) if str(p).strip()]
        try:
            dl.move_category(category_id, parent_ids)
        except Exception as exc:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        dl.log_task(_now_iso(), "web", "move_category", category_id,
                    {"new_parent_ids": parent_ids})
        return {"id": category_id, "parent_ids": parent_ids}

    @app.post("/api/categories/{category_id}/merge")
    async def merge_category(category_id: str, request: Request):
        """合并分类：source 的条目与子树并入 target，source 删除。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        target_id = str(body.get("target_id", "")).strip()
        if target_id == category_id:
            return JSONResponse({"error": {"code": "BAD_REQUEST",
                                           "message": "不能合并到自身"}}, status_code=400)
        try:
            dl.merge_categories(category_id, target_id)
        except Exception as exc:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(exc)}},
                                status_code=400)
        dl.log_task(_now_iso(), "web", "merge_category", category_id, {"target_id": target_id})
        return {"merged": category_id, "into": target_id}

    @app.get("/api/entries/linkage")
    def entries_linkage(ids: str = ""):
        """批量取条目的分类挂接（双向联动②：条目列表点分类路径徽标在树中定位）。

        只读；最多 100 个 id（前端按视图批量取，防 URL 过长）。必须声明在
        /api/entries/{entry_id} 之前——否则 "linkage" 会被路径参数捕获。
        """
        id_list = [s.strip() for s in ids.split(",") if s.strip()][:100]
        if not id_list:
            return {"linkage": {}}
        return {"linkage": {eid: dl.get_entry_categories(eid) for eid in id_list}}

    @app.get("/api/entries/{entry_id}")
    def entry_detail(entry_id: str):
        detail = dl.get_entry_detail(entry_id)
        if detail is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        return detail

    # ---- Thread 串联工作区（完整方案 §9.4，0.2.0 第三十二批） ----

    def _thread_payload(thread) -> dict:
        """线索详情：items 展开为条目信息（标题/来源/状态），position 即阅读序。"""
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
                })
        return {"id": thread.id, "name": thread.name, "note": thread.note,
                "thread_type": thread.thread_type, "created_at": thread.created_at,
                "updated_at": thread.updated_at, "items": items}

    @app.get("/api/threads")
    def list_threads(thread_type: str | None = None):
        return {"threads": dl.list_threads(thread_type=thread_type)}

    @app.post("/api/threads")
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

    @app.get("/api/threads/{thread_id}")
    def get_thread(thread_id: str):
        thread = dl.get_thread(thread_id)
        if thread is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "线索不存在"}},
                                status_code=404)
        return _thread_payload(thread)

    @app.post("/api/threads/{thread_id}/update")
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

    @app.post("/api/threads/{thread_id}/delete")
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

    @app.post("/api/threads/{thread_id}/items")
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

    @app.post("/api/threads/{thread_id}/items/{item_id}/remove")
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

    @app.post("/api/threads/{thread_id}/items/{item_id}/update")
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

    @app.post("/api/threads/{thread_id}/items/{item_id}/move")
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

    @app.post("/api/threads/{thread_id}/suggest")
    async def suggest_thread(thread_id: str, request: Request):
        """thread_suggest：LLM 建议阅读顺序并应用（llm 不可用 = 原序，不写库）。"""
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
        from ..semantic.base import TaskContext
        from ..semantic.llm import LlmClient

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

    @app.post("/api/recall")
    async def recall(request: Request):
        """topic_recall 多路召回（只读，无需写令牌）：主题词或 c:/e: 节点 id。"""
        body = await request.json()
        topic = str(body.get("topic", "")).strip()
        try:
            limit = max(1, min(int(body.get("limit", 60)), 200))
        except (TypeError, ValueError):
            limit = 60
        from ..semantic.base import TaskContext

        _, recall_task = semantics.resolve_task("topic_recall")
        return recall_task(topic, TaskContext(run_id="web-recall", datalayer=dl), limit=limit)

    @app.get("/api/entries/{entry_id}/threads")
    def entry_threads(entry_id: str):
        """条目挂在哪些线索里（UI 徽标）。"""
        return {"threads": dl.threads_for_entry(entry_id)}

    @app.get("/api/search")
    def search(q: str = "", mode: str = "fts"):
        hits = dl.search_fts(q)
        payload = {"mode": mode, "effective_mode": "fts", "hits": [
            {"entry_id": h.entry_id, "title": h.title, "locator": h.locator,
             "snippet": h.snippet, "rank": h.rank} for h in hits
        ]}
        if mode == "hybrid":
            payload["note"] = "hybrid 依赖 embedding 级（M4 接入），本次已降级 fts"
        return payload

    @app.post("/api/entries")
    async def add_entry(request: Request):
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        url = str(body.get("url", "")).strip()
        if not url:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": "缺少 url"}},
                                status_code=400)
        run_id = dl.recent_runs(1)[0]["id"] if dl.recent_runs(1) else "web0000000000000"
        summary = ingest_url(cfg, dl, locators, semantics, url, run_id)
        return summary
