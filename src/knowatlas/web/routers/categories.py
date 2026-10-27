"""web/routers/categories.py——分类（列表/重命名/移动/合并/未归类）（拆分自 web/api.py，URL/响应结构不变）。

本域端点：
- /categories/{category_id}/entries
- /uncategorized
- /categories
- /categories/{category_id}/rename
- /categories/{category_id}/move
- /categories/{category_id}/merge
"""

from __future__ import annotations


from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import JSONResponse

from ..ctx import AppCtx, _now_iso


def register(ctx: AppCtx) -> APIRouter:
    """注册 6 个端点；cfg/dl 等取自 ctx，闭包名与原 api.py 一致。"""
    router = APIRouter()
    cfg, dl, locators, semantics = ctx.cfg, ctx.dl, ctx.locators, ctx.semantics
    # 安全/令牌助手仍归 api.py（函数内导入，避免 api↔routers 循环）
    from ..api import check_write_access

    @router.get("/categories/{category_id}/entries")
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

    @router.get("/uncategorized")
    def uncategorized(limit: int = 200):
        """暂存区：未挂任何分类的 active 条目。"""
        entries = dl.get_uncategorized(limit=limit)
        return {"entries": [{"id": e.id, "title": e.title, "locator": e.locator,
                             "source_type": e.source_type, "native_path": e.native_path}
                            for e in entries]}

    @router.post("/categories")
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

    @router.post("/categories/{category_id}/rename")
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

    @router.post("/categories/{category_id}/move")
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

    @router.post("/categories/{category_id}/merge")
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

    return router
