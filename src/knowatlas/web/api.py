"""REST 端点（完整方案 §8）+ H5 五条安全约束。

安全约束（仅绑 127.0.0.1 不够——挡不住 CSRF 与 DNS rebinding）：
1. Host 校验；2. Origin 校验；3. 写操作 X-KnowAtlas-Token；4. content-type 白名单；
5. CORS 不放宽（bookmarklet 的 no-cors POST 把 token 放 query 参数 ?token=）。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_TOKEN_HEADER = "x-knowatlas-token"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
    supplied = request.headers.get(_TOKEN_HEADER) or request.query_params.get("token", "")
    if supplied != expected:
        return JSONResponse(
            {"error": {"code": "FORBIDDEN",
                       "message": f"写操作需 {_TOKEN_HEADER} 头（或 ?token=，bookmarklet 用）"}},
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

    @app.get("/api/graph")
    def graph(max_entries: int = 400):
        """关系图数据（结构关系 v0：分类挂接 + 同域名）。"""
        return dl.get_graph_data(max_entries=max_entries)

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

    @app.get("/api/entries/{entry_id}")
    def entry_detail(entry_id: str):
        detail = dl.get_entry_detail(entry_id)
        if detail is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        return detail

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
