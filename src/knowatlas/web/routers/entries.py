"""web/routers/entries.py——条目（列表/详情/预览/改分类/表单/入库/状态）（拆分自 web/api.py，URL/响应结构不变）。

本域端点：
- /entries/{entry_id}/reject
- /entries/{entry_id}/restore
- /entries/bulk-status
- /entries/{entry_id}/rename
- /entries/merge
- /entries/{entry_id}/preview
- /entries/{entry_id}/emmx_tree
- /entries/{entry_id}/file
- /entries/auto-name
- /pending
- /rejected
- /dead-links
- /not-knowledge
- /entries/{entry_id}/unflag
- /entries/{entry_id}/recategorize
- /entries/batch-recategorize
- /entries/{entry_id}/confirm-category
- /entries/linkage
- /entries/points
- /entries/{entry_id}/form
- /entries/{entry_id}
- /entries
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import APIRouter
from fastapi import Body, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from ...datalayer.db import REJECT_COOLING_DAYS
from ...errors import AdapterError, ContractError
from ..ctx import AppCtx, _now_iso


def register(ctx: AppCtx) -> APIRouter:
    """注册 22 个端点；cfg/dl 等取自 ctx，闭包名与原 api.py 一致。"""
    router = APIRouter()
    cfg, dl, locators, semantics = ctx.cfg, ctx.dl, ctx.locators, ctx.semantics
    # 安全/令牌助手仍归 api.py（函数内导入，避免 api↔routers 循环）
    from ..api import check_write_access

    from ...pipeline.kadd import ensure_category_path, ingest_url

    @router.post("/entries/{entry_id}/reject")
    async def reject_entry(entry_id: str, request: Request):
        """用户明确舍弃（老化 L3 人裁入口，方案 §7.5）：即刻 rejected 全面不可见
        ——树/检索/词云/导出全部排除，重新同步永不复活；meta.rejected_at 起
        30 天冷却（误裁反悔窗口），期满 ksync 自动物理删除。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        dl.set_status([entry_id], "rejected")
        dl.merge_meta(entry_id, {"rejected_at": _now_iso()})
        dl.log_task(_now_iso(), "web", "reject", entry_id,
                    {"old_status": entry.status, "cooling_days": REJECT_COOLING_DAYS})
        return {"entry_id": entry_id, "status": "rejected",
                "cooling_days": REJECT_COOLING_DAYS}

    @router.post("/entries/{entry_id}/restore")
    async def restore_entry(entry_id: str, request: Request):
        """从 rejected 恢复为 active（误舍弃的后悔药；清冷却起点重新计时语义不复存）。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        dl.set_status([entry_id], "active")
        dl.merge_meta(entry_id, {"rejected_at": None})
        dl.log_task(_now_iso(), "web", "restore", entry_id, {"old_status": entry.status})
        return {"entry_id": entry_id, "status": "active"}

    @router.post("/entries/bulk-status")
    async def bulk_status(request: Request, body: dict = Body(default={})):
        """批量状态流转（批次 68，截图痛点「舍弃十个点十次」）。

        body: ids=[entry_id…]（≤500）、action="activate"（转正：pending/rejected/
        staged → active，清冷却起点）| "reject"（舍弃：→ rejected + 冷却起点）。
        每条 task_log 留痕（bulk 标记串联）；missing 列出库中不存在的 id。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        ids = [str(x).strip() for x in (body.get("ids") or []) if str(x).strip()]
        action = str(body.get("action", "")).strip()
        if action not in ("activate", "reject"):
            return JSONResponse(
                {"error": {"code": "BAD_REQUEST",
                           "message": "action 必须是 activate（转正）或 reject（舍弃）"}},
                status_code=400)
        if not ids:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": "ids 为空"}},
                                status_code=400)
        ids = list(dict.fromkeys(ids))[:500]
        status = "active" if action == "activate" else "rejected"
        done: list[str] = []
        missing: list[str] = []
        for eid in ids:
            entry = dl.get_entry(eid)
            if entry is None:
                missing.append(eid)
                continue
            dl.set_status([eid], status)
            dl.merge_meta(eid, {"rejected_at": _now_iso() if action == "reject" else None})
            dl.log_task(_now_iso(), "web", f"bulk_{action}", eid,
                        {"old_status": entry.status, "cooling_days": REJECT_COOLING_DAYS})
            done.append(eid)
        return {"done": done, "missing": missing, "status": status,
                "cooling_days": REJECT_COOLING_DAYS if action == "reject" else None}

    @router.post("/entries/{entry_id}/rename")
    def rename_entry(request: Request, entry_id: str, body: dict = Body(default={})):
        """条目改名（批次 71，截图痛点「网页原标题带站点尾巴毫无知识味」）。

        body: name=新名字（1..120 字）。写 meta.display_name 覆盖层——数据层
        _row_to_entry 统一应用，列表/检索/图全部生效；full 重同步冲不回（覆盖层
        在 meta）。name 为空串=清除覆盖回归源标题。task_log 留痕。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        name = str(body.get("name", "")).strip()
        if len(name) > 120:
            return JSONResponse(
                {"error": {"code": "BAD_REQUEST", "message": "名字最长 120 字"}},
                status_code=400)
        dl.merge_meta(entry_id, {"display_name": name or None})
        dl.log_task(_now_iso(), "web", "rename", entry_id,
                    {"old": entry.title[:60], "new": name[:120] or None})
        return {"entry_id": entry_id, "name": name or None,
                "title": dl.get_entry(entry_id).title}

    @router.post("/entries/merge")
    def merge_entries_ep(request: Request, body: dict = Body(default={})):
        """条目合并（批次 71，截图批注「PECOS×3 这种就该合并」）。

        body: primary_id=主条目、merge_ids=[被并条目…]（≤50）。被并条目的
        locator/知识点溯源/分类全部归主条目，自身置 rejected（带冷却起点，
        30 天后老化物理删除出口自动清）。task_log 留痕。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        primary_id = str(body.get("primary_id", "")).strip()
        merge_ids = [str(x).strip() for x in (body.get("merge_ids") or []) if str(x).strip()]
        merge_ids = list(dict.fromkeys(merge_ids))[:50]
        if not primary_id or not merge_ids:
            return JSONResponse(
                {"error": {"code": "BAD_REQUEST",
                           "message": "需要 primary_id 和 merge_ids（至少 1 条）"}},
                status_code=400)
        if primary_id in merge_ids:
            return JSONResponse(
                {"error": {"code": "BAD_REQUEST", "message": "主条目不能出现在 merge_ids"}},
                status_code=400)
        try:
            stats = dl.merge_entries(primary_id, merge_ids, reason="web_merge")
        except ContractError as e:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": str(e)}},
                                status_code=400)
        return stats

    @router.get("/entries/{entry_id}/preview")
    def entry_preview(request: Request, entry_id: str):
        """条目预览（批次 71，截图痛点「点条目直接跳 file:// 或离开站内」）。

        返回 display_name/正文前 2000 字（content_store）/元信息（来源/分类/
        附加 locator/点数）——前端弹层展示，「打开原文」走 locator。
        """
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        body_text = ""
        if entry.content_hash:
            full = dl.get_content(entry.content_hash) or ""
            body_text = full[:2000] + ("…[截断]" if len(full) > 2000 else "")
        cats = [c["name"] for c in dl.get_entry_categories(entry_id)]
        extra_locs = dl.all_entry_locators().get(entry_id, [])
        pts = dl.points_of_entries([entry_id])
        n_points = len(pts.get(entry_id, [])) if isinstance(pts, dict) else len(pts)
        return {"id": entry_id, "title": entry.title, "locator": entry.locator,
                "source_type": entry.source_type, "native_path": entry.native_path,
                "status": entry.status, "categories": cats,
                "extra_locators": extra_locs, "points_count": n_points,
                "merged_from": entry.meta.get("merged_from") or [],
                "body": body_text}

    @router.get("/entries/{entry_id}/emmx_tree")
    def entry_emmx_tree(request: Request, entry_id: str):
        """脑图大纲树（批次 91）：读 .emmx 重建节点树，站内树形浏览不依赖外部工具。

        locator 形如 emmx://<相对路径>#map，相对路径在 [sources.emmx].roots 下
        逐根探测；文件缺失/解析失败返回 404/422+原因（前端诚实提示，不渲染
        假树）。只读解析，零写库零 LLM。
        """
        entry = dl.get_entry(entry_id)
        if entry is None or entry.source_type != "emmx":
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "条目不存在或非脑图"}},
                status_code=404)
        loc = entry.locator or ""
        # 9.x 整图条目 `#map`；14.x 二进制页条目 `#page` / `#page-1`（一页一条目）
        rel, _sep, anchor = loc[len("emmx://"):].partition("#") if loc.startswith("emmx://") else ("", "", "")
        if not rel or not (anchor == "map" or anchor.startswith("page")):
            return JSONResponse(
                {"error": {"code": "NOT_MINDMAP",
                           "message": "该条目无整图大纲（降级或节点条目）"}},
                status_code=404)
        path = None
        for root in (cfg.get("sources.emmx.roots") or []):
            cand = Path(str(root)) / rel
            if cand.is_file():
                path = cand
                break
        if path is None:
            return JSONResponse(
                {"error": {"code": "FILE_MISSING",
                           "message": f"脑图文件不在 roots 下：{rel}"}},
                status_code=404)
        from ...adapters.emmx import parse_tree
        try:
            tree = parse_tree(path)
        except AdapterError as e:
            return JSONResponse(
                {"error": {"code": "PARSE_FAILED", "message": str(e)}},
                status_code=422)
        if anchor != "map":  # 14.x：只回本条目那一页，节点头数按页重算
            only = [p for p in tree["pages"] if p.get("name") == anchor]
            if only:
                tree = {"pages": only,
                        "node_count": sum(p.get("node_count", 0) for p in only)}
        return {"id": entry_id, "title": entry.title, **tree}

    # ---- 条目原文站内代理（2026-10-26 P4 后置项 B：修「反查可溯源，但打不开」） ----
    # file:// 存的是「配置根相对路径」（可迁移铁律），浏览器既把首段当主机名、又禁止
    # http 页面跳 file:// —— 由服务端按 [sources.folders].roots 解析成绝对路径再流式返回。
    # 只读、零写库、零 LLM：Host/Origin 已由中间件守，路径做根内包含性校验。
    _INLINE_IMAGE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}

    # 纯文本类：走 text/plain，浏览器当正文显示（不会执行）
    _INLINE_TEXT = {".md", ".markdown", ".txt", ".csv", ".log", ".json", ".yaml", ".yml"}

    def _file_locator_rel(locator: str) -> str | None:
        """file://<rel> → rel（口径同 fetchers/file_reader.py）；非法返回 None。

        拒空串、反斜杠、`..`、盘符绝对路径——file:// 只允许配置根相对路径（§5 可迁移铁律）。
        """
        parts = urlparse(locator)
        if parts.scheme != "file":
            return None
        rel = unquote(parts.netloc + parts.path).lstrip("/")
        if not rel or "\\" in rel or ".." in Path(rel).parts:
            return None
        if len(rel) >= 2 and rel[1] == ":":
            return None
        return rel

    def _file_response(path: Path) -> Response:
        """按后缀分流：可安全内联的才 inline，其余强制下载。

        HTML/SVG/XML 若 inline 会以**本服务同源**执行，能读走 localStorage 里的
        写令牌 → 一律 attachment + octet-stream（Office/emmx 浏览器本来也渲染不了）。
        """
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            media_type, disp = "application/pdf", "inline"
        elif suffix in _INLINE_IMAGE:
            media_type, disp = _INLINE_IMAGE[suffix], "inline"
        elif suffix in _INLINE_TEXT:
            media_type, disp = "text/plain; charset=utf-8", "inline"
        else:
            media_type, disp = "application/octet-stream", "attachment"
        return FileResponse(path, media_type=media_type, filename=path.name,
                            content_disposition_type=disp,
                            headers={"X-Content-Type-Options": "nosniff"})

    @router.get("/entries/{entry_id}/file")
    def entry_file(entry_id: str):
        """条目原文（浏览器可打开的站内代理；只读）。

        `file://` 条目（文件夹源）→ 按 `[sources.folders].roots` 逐根解析成绝对路径，
        realpath 必须落在根内（符号链接跑出根按不存在处理，错误响应不回显绝对路径）；
        PDF/图片/文本内联，其余附件下载。非 `file://`（https/emmx/…）→ 404 NOT_SUPPORTED，
        前端据此退化为纯文本（第三十七批纪律：不渲染打不开的假链接）。
        """
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                status_code=404)
        loc = entry.locator or ""
        if not loc.startswith("file://"):
            scheme = loc.split("://", 1)[0] if "://" in loc else "空"
            return JSONResponse(
                {"error": {"code": "NOT_SUPPORTED",
                           "message": f"该条目原文不是本地文件（{scheme} 链接），"
                                      "网页条目直接在浏览器打开，脑图条目看站内大纲树"}},
                status_code=404)
        rel = _file_locator_rel(loc)
        if rel is None:
            return JSONResponse(
                {"error": {"code": "OUT_OF_ROOT",
                           "message": "locator 不是配置根相对路径"
                                      "（禁 .. / 反斜杠 / 盘符绝对路径）"}},
                status_code=403)
        for root in (cfg.get("sources.folders.roots") or []):
            root_path = Path(str(root)).resolve()
            target = (root_path / rel).resolve()
            if target.is_file() and target.is_relative_to(root_path):
                return _file_response(target)
        return JSONResponse(
            {"error": {"code": "FILE_MISSING",
                       "message": f"文件不在 [sources.folders].roots 下或已被移动：{rel}"}},
            status_code=404)

    @router.post("/entries/auto-name")
    def auto_name(request: Request, body: dict = Body(default={})):
        """AI 批量起名（批次 71，截图批注「按知识的名字来命名」）。

        对 ids（≤50）条目：取正文 → LLM 起 8-20 字知识化短名（默认提示词可用
        body.prompt 覆盖）→ 写 meta.display_name。同步 def（LLM 网络调用禁占
        事件循环）。已有 display_name 的跳过（force=true 强制重起）。返回逐条
        新名与跳过清单。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        ids = [str(x).strip() for x in (body.get("ids") or []) if str(x).strip()]
        ids = list(dict.fromkeys(ids))[:50]
        force = bool(body.get("force"))
        prompt_override = str(body.get("prompt", "")).strip()
        if not ids:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": "ids 为空"}},
                                status_code=400)
        from ...semantic.naming import auto_name_entries
        result = auto_name_entries(cfg, dl, ids, force=force,
                                   prompt_override=prompt_override or None)
        return result

    @router.get("/pending")
    def pending_entries(limit: int = 500):
        """入库待审队列（批次 68）：status=pending 的新条目——未审不进消费面。

        源配置 new_entries="pending" 时该源新条目落这里；审 = 批量转正/舍弃
        （POST /api/entries/bulk-status）。pending 条目不分类不抓正文不抽点
        （省 LLM/抓取费用——垃圾可能根本没人看）。
        """
        out = []
        for e in dl.list_entries(status="pending", limit=limit):
            out.append({"id": e.id, "title": e.title, "locator": e.locator,
                        "source_type": e.source_type, "native_path": e.native_path,
                        "meta": {"source_type": e.meta.get("source_type"),
                                 "mind_path": e.meta.get("mind_path")},
                        "created_at": e.created_at})
        return {"count": len(out), "entries": out}

    @router.get("/rejected")
    def rejected_entries(limit: int = 500):
        """已舍弃条目列表（冷却倒计时/恢复入口）。

        rejected_at 起 30 天冷却，期满 ksync 自动物理删除（老化删除出口）；
        无 rejected_at 的历史舍弃不计冷却、不会自动删除。
        """
        now = datetime.now(timezone.utc)
        out = []
        for e in dl.list_entries(status="rejected", limit=limit):
            rat = e.meta.get("rejected_at")
            left: int | None = None
            if rat:
                try:
                    t = datetime.fromisoformat(str(rat))
                    if t.tzinfo is None:
                        t = t.astimezone()
                    left = max(0, REJECT_COOLING_DAYS
                               - int((now - t).total_seconds() // 86400))
                except ValueError:
                    left = None
            out.append({"id": e.id, "title": e.title, "locator": e.locator,
                        "source_type": e.source_type,
                        "rejected_at": rat, "cooling_days_left": left})
        return {"entries": out}

    @router.get("/dead-links")
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

    @router.get("/not-knowledge")
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

    @router.post("/entries/{entry_id}/unflag")
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

    @router.post("/entries/{entry_id}/recategorize")
    async def recategorize(entry_id: str, request: Request):
        """人工校正：条目改挂目标分类（按路径，不存在则自动建，origin=manual）。

        默认替换语义：全部旧挂接摘除（含旧 manual——"manual 永不覆盖"约束
        的是机器来源 H3，不约束人工自己的后续校正）。
        keep_existing=true（多父挂接，第五十二批）：只追加新挂接不摘旧——
        一条知识本来就常属多个分支（DAG 设计初衷）。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        target_path = str(body.get("target_path", "")).strip().strip("/")
        keep_existing = bool(body.get("keep_existing", False))
        if not target_path:
            return JSONResponse({"error": {"code": "BAD_REQUEST",
                                           "message": "缺少 target_path（如 技术开发/前端）"}},
                                status_code=400)
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        old_links = dl.get_entry_categories(entry_id)
        old_paths = [l["path"] for l in old_links]
        cid = ensure_category_path(dl, target_path, "manual")
        if not keep_existing:
            # 人工迁移语义：替换全部旧挂接（含旧 manual）
            for link in old_links:
                if link["category_id"] != cid:
                    dl.detach_category(entry_id, link["category_id"])
        else:
            dl.detach_category(entry_id, cid)  # 幂等防重复挂接
        dl.attach_category(entry_id, cid, 1.0, "manual", "web-recategorize")
        dl.log_task(_now_iso(), "web", "recategorize", entry_id,
                    {"old_paths": old_paths, "new_path": target_path,
                     **({"keep_existing": True} if keep_existing else {})})
        return {"entry_id": entry_id, "category_path": target_path}

    @router.post("/entries/batch-recategorize")
    async def batch_recategorize(request: Request):
        """批量人工校正（第五十二批）：多个条目一起改挂/追加挂到目标路径。

        复现性纪律与单条一致：每个条目独立写一条 task_log
        （action=batch_recategorize，detail.batch_id 串联同一批）。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        body = await request.json()
        target_path = str(body.get("target_path", "")).strip().strip("/")
        keep_existing = bool(body.get("keep_existing", False))
        entry_ids = [str(x) for x in (body.get("entry_ids") or []) if str(x)]
        if not target_path:
            return JSONResponse({"error": {"code": "BAD_REQUEST",
                                           "message": "缺少 target_path（如 技术开发/前端）"}},
                                status_code=400)
        if not entry_ids:
            return JSONResponse({"error": {"code": "BAD_REQUEST",
                                           "message": "缺少 entry_ids（条目 id 数组）"}},
                                status_code=400)
        cid = ensure_category_path(dl, target_path, "manual")
        batch_id = uuid.uuid4().hex[:8]
        done: list[str] = []
        skipped: list[dict] = []
        for eid in dict.fromkeys(entry_ids):  # 去重保序
            entry = dl.get_entry(eid)
            if entry is None:
                skipped.append({"entry_id": eid, "reason": "not_found"})
                continue
            old_paths = [l["path"] for l in dl.get_entry_categories(eid)]
            if not keep_existing:
                for link in dl.get_entry_categories(eid):
                    if link["category_id"] != cid:
                        dl.detach_category(eid, link["category_id"])
            else:
                dl.detach_category(eid, cid)  # 幂等防重复挂接
            dl.attach_category(eid, cid, 1.0, "manual", f"web-batch:{batch_id}")
            dl.log_task(_now_iso(), "web", "batch_recategorize", eid,
                        {"old_paths": old_paths, "new_path": target_path,
                         "batch_id": batch_id,
                         **({"keep_existing": True} if keep_existing else {})})
            done.append(eid)
        return {"batch_id": batch_id, "done": done, "skipped": skipped,
                "category_path": target_path}

    @router.post("/entries/{entry_id}/confirm-category")
    async def confirm_category(entry_id: str, request: Request):
        """确认归类（回归集，0.2.0 第五十一批）：把条目当前主分类路径确认为
        回归集期望（manual 挂接优先，其余取第一个）。同条目重复确认覆盖旧值。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        links = dl.get_entry_categories(entry_id)
        if not links:
            return JSONResponse(
                {"error": {"code": "BAD_REQUEST",
                           "message": "条目未挂任何分类——先归类再确认"}},
                status_code=400)
        main = next((l for l in links if l["origin"] == "manual"), links[0])
        dl.add_regress_case(entry_id, main["path"], source="manual")
        dl.log_task(_now_iso(), "web", "confirm_regress", entry_id,
                    {"expected_path": main["path"]})
        return {"entry_id": entry_id, "expected_path": main["path"]}

    @router.get("/entries/linkage")
    def entries_linkage(ids: str = ""):
        """批量取条目的分类挂接 + 脑图内路径（双向联动② + 批次 68 面包屑）。

        只读；最多 100 个 id（前端按视图批量取，防 URL 过长）。必须声明在
        /api/entries/{entry_id} 之前——否则 "linkage" 会被路径参数捕获。
        mind_paths 只对 emmx 节点条目有值（meta.mind_path，④上下文呈现——
        「人也不知道哪些点会合成整图，因为啥都看不到」的用户批注）。
        """
        id_list = [s.strip() for s in ids.split(",") if s.strip()][:100]
        if not id_list:
            return {"linkage": {}, "mind_paths": {}}
        mind: dict[str, str] = {}
        for eid in id_list:
            e = dl.get_entry(eid)
            if e is not None and e.source_type == "emmx":
                mp = str(e.meta.get("mind_path") or "").strip()
                if mp:
                    mind[eid] = mp
        return {"linkage": {eid: dl.get_entry_categories(eid) for eid in id_list},
                "mind_paths": mind}

    @router.get("/entries/points")
    def entries_points(ids: str = ""):
        """批量取条目挂的点（③默认聚合呈现，批次 67，两层形态共存的消费面）。

        条目（方案级）照常检索展示，点级收进前端可展开区——聚合默认、下钻可选。
        text 已服务端截断（点全文走条目原文）。必须声明在 /api/entries/{entry_id}
        之前——否则 "points" 会被路径参数捕获。
        """
        id_list = [s.strip() for s in ids.split(",") if s.strip()][:100]
        return {"points": dl.points_of_entries(id_list)}

    @router.post("/entries/{entry_id}/form")
    def entry_form(request: Request, entry_id: str, body: dict = Body(default={})):
        """条目级形态覆盖（批次 70，非 emmx 文档的「拆/合」）：
        写 meta.force_form → 清该条目点溯源 → 即时重抽。

        body: form="integral"（合=整条一点，零 LLM）| "split"（拆=LLM 切点，需
        llm.enabled）| "auto"（清覆盖，回归目录/分类规则）。覆盖永久生效
        （全量重抽也尊重标记）；emmx 不走此端点（源级 rejudge 已有，两套不打架）。
        同步 def：重抽含 LLM 网络调用，禁止占事件循环（同 emmx_rejudge）。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        form = str(body.get("form", "")).strip().lower()
        if form not in ("integral", "split", "auto"):
            return JSONResponse(
                {"error": {"code": "BAD_REQUEST",
                           "message": "form 必须是 integral（合）/ split（拆）/ auto（回归规则）"}},
                status_code=400)
        entry = dl.get_entry(entry_id)
        if entry is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        if entry.source_type == "emmx":
            return JSONResponse(
                {"error": {"code": "BAD_REQUEST",
                           "message": "emmx 条目用源级 rejudge（/api/sources/emmx/rejudge），条目级覆盖不适用"}},
                status_code=400)
        from ...pipeline.points import run_points_extract
        # 1) 覆盖标记（auto=删键回归规则；merge_meta None=删键）
        dl.merge_meta(entry_id, {"force_form": None if form == "auto" else form})
        # 2) 清该条目点溯源（孤儿点级联删，共享点保留；游标随之清）
        purged = dl.purge_entry_points(entry_id, reason=f"web_form_{form}")
        # 3) 即时重抽（split 需 LLM——未启用记 error 返回，不静默）
        stats = run_points_extract(cfg, dl, limit=1, entry_ids=[entry_id])
        judge = ("integral" if stats.get("integral")
                 else "split" if stats.get("split") else None)
        dl.log_task(_now_iso(), "web", "entry_form", entry_id,
                    {"form": form, "purged_sources": purged,
                     "judge": judge,
                     "points_created": stats.get("points_created", 0),
                     "errors": stats.get("errors", [])})
        resp: dict[str, Any] = {"entry_id": entry_id, "form": form,
                                "purged_sources": purged,
                                "points_created": stats.get("points_created", 0),
                                # 自洽性闸门附加字段（TODO 8.5）：整条被拦时前端
                                # 可提示原因；老前端忽略此键不受影响。
                                "gate": {"blocked": bool(stats.get("gate_blocked")),
                                         "rejected": stats.get("points_rejected", 0),
                                         "reasons": stats.get("reject_reasons") or {}},
                                "errors": stats.get("errors", [])}
        pts = dl.points_of_entries([entry_id])
        resp["points"] = pts.get(entry_id, []) if isinstance(pts, dict) else pts
        return resp

    @router.get("/entries/{entry_id}")
    def entry_detail(entry_id: str):
        detail = dl.get_entry_detail(entry_id)
        if detail is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        return detail

    @router.post("/entries")
    def add_entry(request: Request, body: dict = Body(default={})):
        """手动收录（同 kadd 链路）。同步 def（第五十八批）：ingest_url 内含
        抓取网页的网络 I/O（可达秒-分钟级），禁止占用事件循环。"""
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        url = str(body.get("url", "")).strip()
        if not url:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": "缺少 url"}},
                                status_code=400)
        run_id = dl.recent_runs(1)[0]["id"] if dl.recent_runs(1) else "web0000000000000"
        summary = ingest_url(cfg, dl, locators, semantics, url, run_id)
        return summary

    return router
