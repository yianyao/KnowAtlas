"""REST 端点（完整方案 §8）+ H5 五条安全约束。

安全约束（仅绑 127.0.0.1 不够——挡不住 CSRF 与 DNS rebinding）：
1. Host 校验；2. Origin 校验；3. 写操作 X-KnowAtlas-Token；4. content-type 白名单；
5. CORS 不放宽（bookmarklet 走 GET 跳转 index.html?add= 由首页同源提交会话请求，不做跨站 POST；?token= 仅作 CLI/脚本兜底）。
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from ..datalayer.db import REJECT_COOLING_DAYS
from ..errors import AdapterError, ContractError
from ..models import Entry, FetchResult
from ..semantic.keywords import word_ok as _cloud_word_ok

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

    # 各知识源配置状态（第五十九批：管理页「数据管理」用）——键集与 config.py
    # 的 CONFIG_KEY 白名单同源；只报已配置与否，不回传任何路径/凭证明文。
    _KNOWN_SOURCES = [
        ("bookmarks", "浏览器书签"), ("folders", "本地文件夹"), ("emmx", "脑图"),
        ("mail", "邮件"), ("opml", "OPML 订阅"), ("session", "AI 会话"),
        ("db", "数据文件"), ("bilibili", "B站收藏夹"), ("ima", "IMA"),
        ("txdoc", "腾讯文档"), ("wx", "微信"), ("manual", "手动收录"),
    ]

    @app.get("/api/sources")
    def sources_status() -> dict:
        """只读：各知识源在 config 中的配置状态（configured 布尔）。"""
        return {"sources": [{"name": name, "label": label,
                             "configured": bool(cfg.get(f"sources.{name}") or {})}
                            for name, label in _KNOWN_SOURCES]}

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

    @app.post("/api/entries/{entry_id}/restore")
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

    @app.post("/api/entries/bulk-status")
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

    @app.post("/api/entries/{entry_id}/rename")
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

    @app.post("/api/entries/merge")
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

    @app.get("/api/entries/{entry_id}/preview")
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

    @app.get("/api/entries/{entry_id}/emmx_tree")
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
        if not loc.startswith("emmx://") or "#map" not in loc:
            return JSONResponse(
                {"error": {"code": "NOT_MINDMAP",
                           "message": "该条目无整图大纲（降级或节点条目）"}},
                status_code=404)
        rel = loc[len("emmx://"):].split("#", 1)[0]
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
        from ..adapters.emmx import parse_tree
        try:
            tree = parse_tree(path)
        except AdapterError as e:
            return JSONResponse(
                {"error": {"code": "PARSE_FAILED", "message": str(e)}},
                status_code=422)
        return {"id": entry_id, "title": entry.title, **tree}

    @app.post("/api/points/{point_id}/explain")
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
        from ..semantic.llm import LlmClient
        llm = LlmClient.from_config(cfg)
        if llm is None:
            return JSONResponse(
                {"error": {"code": "LLM_DISABLED",
                           "message": "LLM 未启用——释疑是增强层（[llm] enabled=true）"}},
                status_code=503)
        from ..semantic.base import TaskContext
        from ..semantic.tasks import point_explain as explain_task
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

    @app.post("/api/synthesize/preview")
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
        from ..semantic.llm import LlmClient
        llm = LlmClient.from_config(cfg)
        if llm is None:
            return JSONResponse(
                {"error": {"code": "LLM_DISABLED",
                           "message": "LLM 未启用——合成是增强层（[llm] enabled=true）"}},
                status_code=503)
        from ..semantic.base import TaskContext
        from ..semantic.tasks import synthesize as synth_task
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

    @app.post("/api/synthesize/commit")
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

    @app.get("/api/graph/topics")
    def graph_topics():
        """知识主题聚合（批次 88，方案 §9：点聚类主题节点，条目退溯源层）。

        全库点向量贪心归簇（阈值 0.72），簇 ≥2 点成主题；主题名=成员共享词
        （禁发明性命名）。零费用零写库，纯查询期计算；点向量未建时返回
        note 提示。试点口径：先看聚合效果再定铺开与下钻交互。
        """
        from ..pipeline.graph_topics import topic_clusters
        return topic_clusters(dl)

    @app.post("/api/entries/auto-name")
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
        from ..semantic.naming import auto_name_entries
        result = auto_name_entries(cfg, dl, ids, force=force,
                                   prompt_override=prompt_override or None)
        return result

    @app.get("/api/pending")
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

    @app.get("/api/rejected")
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

    @app.get("/api/freshness")
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

    @app.post("/api/entries/{entry_id}/unflag-freshness")
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

    @app.get("/api/errata")
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

    @app.get("/api/errata/points")
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

    @app.post("/api/entries/{entry_id}/errata")
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

    @app.post("/api/entries/{entry_id}/errata/dismiss")
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

    @app.post("/api/points/{point_id}/fact-check/dismiss")
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

    _CLOUD_PALETTE = ("#d1495b", "#e07a3c", "#c9a227", "#5f9e4e", "#2e9e83",
                      "#2b8fb3", "#3f6fb5", "#63599e", "#8d5aa8", "#b5497e",
                      "#a4485f", "#5f6b7a")
    # 词元噪音表与准入规则已移 semantic/keywords.py（第六十批知识集组头共用），
    # 本文件以 _cloud_word_ok 别名引用，行为不变。

    @app.get("/api/cloud")
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

    @app.get("/api/timeline")
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

    # ---- MCP 只读查询端点（第四十六批）----
    # v0 形态 = REST 只读投影（/api/mcp/ 命名空间），供 agent 调用；
    # 真 MCP 协议（stdio/SSE，需引入 mcp SDK）后置——YAGNI，先让 agent 能查。
    # 只读纪律：三个 handler 只调 dl 的查询方法（search_fts/get_tree/
    # get_entry/get_content_preview/subtree_category_ids/get_category_paths），
    # 无任何写操作；tests/test_web_api.py 有 AST 级只读校验探针钉死。
    @app.get("/api/mcp/search")
    def mcp_search(q: str = "", limit: int = 20):
        """检索（只读）：FTS 查询，返回命中条目（agent 查询入口）。"""
        hits = dl.search_fts(q, limit=max(1, min(int(limit), 100)))
        return {"query": q, "count": len(hits), "hits": [
            {"entry_id": h.entry_id, "title": h.title, "locator": h.locator,
             "snippet": h.snippet, "rank": h.rank} for h in hits]}

    @app.get("/api/mcp/tree")
    def mcp_tree():
        """树遍历（只读）：全分类树 + 未分类精确计数（agent 遍历入口；
        计数走 COUNT 不封顶——list+limit 会截断出假数字）。"""
        return {"tree": dl.get_tree(), "uncategorized": dl.count_uncategorized()}

    @app.get("/api/mcp/entry/{entry_id}")
    def mcp_entry(entry_id: str, content_limit: int = 4000):
        """单条目详情（只读）：元信息 + 分类路径 + 正文前缀（content_store
        substr 截取，不整段进内存）。条目不存在 → 404。"""
        e = dl.get_entry(entry_id)
        if e is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        body = e.inline_content or ""
        if e.content_hash:
            body = dl.get_content_preview(e.content_hash, max(0, min(int(content_limit), 20000))) or body
        return {"id": e.id, "title": e.title, "locator": e.locator,
                "source_type": e.source_type, "status": e.status,
                "created_at": e.created_at,
                "category_ids": dl.entry_category_ids(e.id),
                "meta": e.meta, "content": body}

    @app.get("/api/graph")
    def graph(max_entries: int = 400):
        """关系图数据（结构关系 v0：分类挂接 + 同域名）。保留兼容；新视图见下。"""
        return dl.get_graph_data(max_entries=max_entries)

    @app.get("/api/graph/overview")
    def graph_overview():
        """大纲图（初始视图）：只含一级大类，value = 子树 active 条目数。"""
        return dl.get_graph_overview()

    @app.get("/api/graph/subtree")
    def graph_subtree(category_id: str, limit: int = 120, hierarchy: bool = False,
                      compact: bool = False):
        """下钻图：某分类的子孙分类 + 挂接条目（近 limit 条）+ 祖先链上下文；
        hierarchy=true 纯层级模式（批次 63）：只出下一级子分类，条目在叶子层出现；
        compact=true 稀疏折叠（批次 72）：直挂 ≤2 条的子分类藏条目（folded 徽标），
        分类节点带 depth 供前端分层铺开。"""
        data = dl.get_graph_subtree(category_id, limit=limit, hierarchy=hierarchy,
                                    compact=compact)
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

    @app.get("/api/graph/radiate")
    def graph_radiate(node_id: str, per_channel: int = 8):
        """放射邻域：焦点一跳关联，每节点带 reasons[]、每边带 reason（第三十三批）。"""
        data = dl.radiate(node_id, per_channel=max(1, min(per_channel, 40)))
        if data is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "节点不存在"}},
                                status_code=404)
        return data

    @app.get("/api/graph/reverse")
    def graph_reverse(node_id: str, limit: int = 20):
        """双向反查：哪些焦点能到达该节点（分类带 path、线索带 thread.html url）。"""
        data = dl.reverse_reach(node_id, limit=max(1, min(limit, 50)))
        if data is None:
            return JSONResponse({"error": {"code": "NOT_FOUND",
                                           "message": "节点不存在或不支持反查"}},
                                status_code=404)
        return data

    @app.post("/api/entries/{entry_id}/recategorize")
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

    @app.post("/api/entries/batch-recategorize")
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

    @app.post("/api/entries/{entry_id}/confirm-category")
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

    @app.get("/api/entries/points")
    def entries_points(ids: str = ""):
        """批量取条目挂的点（③默认聚合呈现，批次 67，两层形态共存的消费面）。

        条目（方案级）照常检索展示，点级收进前端可展开区——聚合默认、下钻可选。
        text 已服务端截断（点全文走条目原文）。必须声明在 /api/entries/{entry_id}
        之前——否则 "points" 会被路径参数捕获。
        """
        id_list = [s.strip() for s in ids.split(",") if s.strip()][:100]
        return {"points": dl.points_of_entries(id_list)}

    @app.post("/api/sources/emmx/rejudge")
    def emmx_rejudge(request: Request, body: dict = Body(default={})):
        """脑图形态人工裁决（④一键合并/拆开，批次 67）：改判定缓存强判 → emmx
        单源 purge 重灌。

        body: rel=文件相对路径（locator emmx://<rel>#… 的中段）、
        form="integral"（并=整图一条）| "split"（拆=按节点切条）。
        缓存键=文件字节 sha256（与适配器同口径，人工可改写强判——判定缓存即
        人工裁决入口）；重灌走 run_sync 单源（收集零 LLM——缓存命中；分类只对
        新/更新条目）。同步 def：run_sync 含快照/抓取等重 I/O，禁止占事件循环
        （同 add_entry 第五十八批）。点层影响：purge 级联删该源溯源，重灌后
        下次 kpoints 自动重抽（幂等游标缺失即补）。
        """
        guard = check_write_access(request, cfg)
        if guard is not None:
            return guard
        rel = str(body.get("rel", "")).strip().strip("/")
        form = str(body.get("form", "")).strip()
        if form not in ("integral", "split"):
            return JSONResponse(
                {"error": {"code": "BAD_REQUEST",
                           "message": "form 必须是 integral（整图）或 split（切分）"}},
                status_code=400)
        if not rel:
            return JSONResponse({"error": {"code": "BAD_REQUEST", "message": "缺少 rel"}},
                                status_code=400)
        fpath: Any = None
        for r in (cfg.get("sources.emmx.roots") or []):
            cand = Path(str(r)) / rel
            if cand.is_file():
                fpath = cand
                break
        if fpath is None:
            return JSONResponse(
                {"error": {"code": "NOT_FOUND",
                           "message": f"文件不存在：{rel}（roots 下找不到）"}},
                status_code=404)
        from ..adapters.emmx import (_judge_cache_path, _load_judge_cache,
                                     _save_judge_cache)
        if _judge_cache_path(cfg) is None:
            return JSONResponse(
                {"error": {"code": "NO_HOME",
                           "message": "KNOWATLAS_HOME 未设置，判定缓存不可用"}},
                status_code=409)
        fkey = hashlib.sha256(fpath.read_bytes()).hexdigest()
        cache = _load_judge_cache(cfg)
        cache[fkey] = {"judge": form,
                       "reason": f"人工裁决（Web 一键{'整图' if form == 'integral' else '切分'}，批次 67）"}
        _save_judge_cache(cfg, cache)
        from ..pipeline.sync import run_sync
        stats = run_sync(cfg, dl, locators, semantics, full=True,
                         source="emmx", purge_source="emmx",
                         purge_reason="web_rejudge")
        return {"rel": rel, "form": form,
                "purge": stats.get("purge"),
                "emmx": stats.get("sources", {}).get("emmx", {})}

    @app.post("/api/entries/{entry_id}/form")
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
        from ..pipeline.points import run_points_extract
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

    @app.get("/api/entries/{entry_id}")
    def entry_detail(entry_id: str):
        detail = dl.get_entry_detail(entry_id)
        if detail is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "条目不存在"}},
                                status_code=404)
        return detail

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

    @app.get("/api/threads")
    def list_threads(thread_type: str | None = None):
        return {"threads": dl.list_threads(thread_type=thread_type)}

    @app.get("/api/threads-lookup")
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

    @app.post("/api/threads/{thread_id}/digest")
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
        from ..semantic.base import TaskContext
        from ..semantic.llm import LlmClient

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

    @app.post("/api/recall")
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
        from ..semantic.base import TaskContext

        _, recall_task = semantics.resolve_task("topic_recall")
        return recall_task(topic, TaskContext(run_id="web-recall", datalayer=dl), limit=limit)

    @app.get("/api/entries/{entry_id}/threads")
    def entry_threads(entry_id: str):
        """条目挂在哪些线索里（UI 徽标）。"""
        return {"threads": dl.threads_for_entry(entry_id)}

    @app.get("/api/entries/{entry_id}/summary")
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

    @app.get("/api/search")
    def search(q: str = "", mode: str = "fts"):
        # 知识点主通道（批次 86）+ 条目区从点反查（批次 92，裁决 #13：搜概念
        # 词应出该概念论述点非全文概要；条目区=命中点的溯源条目去重为主 +
        # 标题/路径直击保留——词越精确条目越少，正文级全文命中不再单独出条目卡）
        # 批次 87：点向量语义通道——embedder 可用时 FTS 点 + 点向量余弦 RRF
        # 融合重排（语义词如「进销存」零字面命中也能召回），via_sim 标向量独有点
        pts_raw = dl.search_points(q)
        embedder = None
        try:
            from ..pipeline.embed_index import search_points_hybrid
            from ..semantic.embed import from_config as embedder_from_config
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
            from ..pipeline.embed_index import hybrid_search
            from ..semantic.embed import from_config as embedder_from_config

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

    @app.get("/api/sets/group")
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
        from ..pipeline.embed_index import group_hits
        return group_hits(dl, id_list)

    @app.post("/api/entries")
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
