"""web/routers/admin.py——管理（源状态/会话/令牌提示/MCP/重判）（拆分自 web/api.py，URL/响应结构不变）。

本域端点：
- /sources
- /token-hint
- /session
- /mcp/search
- /mcp/tree
- /mcp/entry/{entry_id}
- /sources/emmx/rejudge
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi import Body, Request, Response
from fastapi.responses import JSONResponse

from ..ctx import AppCtx


def register(ctx: AppCtx) -> APIRouter:
    """注册 7 个端点；cfg/dl 等取自 ctx，闭包名与原 api.py 一致。"""
    router = APIRouter()
    cfg, dl, locators, semantics = ctx.cfg, ctx.dl, ctx.locators, ctx.semantics
    # 安全/令牌助手仍归 api.py（函数内导入，避免 api↔routers 循环）
    from ..api import _WRITE_COOKIE, check_write_access, token_fingerprint

    # 各知识源配置状态（第五十九批：管理页「数据管理」用）——键集与 config.py
    # 的 CONFIG_KEY 白名单同源；只报已配置与否，不回传任何路径/凭证明文。
    _KNOWN_SOURCES = [
        ("bookmarks", "浏览器书签"), ("folders", "本地文件夹"), ("emmx", "脑图"),
        ("mail", "邮件"), ("opml", "OPML 订阅"), ("session", "AI 会话"),
        ("db", "数据文件"), ("bilibili", "B站收藏夹"), ("ima", "IMA"),
        ("txdoc", "腾讯文档"), ("wx", "微信"), ("manual", "手动收录"),
    ]

    @router.get("/sources")
    def sources_status() -> dict:
        """只读：各知识源在 config 中的配置状态（configured 布尔）。"""
        return {"sources": [{"name": name, "label": label,
                             "configured": bool(cfg.get(f"sources.{name}") or {})}
                            for name, label in _KNOWN_SOURCES]}

    @router.get("/token-hint")
    def token_hint() -> dict:
        """令牌核对辅助：只给**指纹**（sha256 前 8 位）与来源，永不回传明文。"""
        env_name = str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN"))
        tok = os.environ.get(env_name, "")
        return {"env_name": env_name, "fingerprint": token_fingerprint(tok),
                "configured": bool(tok)}

    @router.get("/session")
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

    # ---- MCP 只读查询端点（第四十六批）----
    # v0 形态 = REST 只读投影（/api/mcp/ 命名空间），供 agent 调用；
    # 真 MCP 协议（stdio/SSE，需引入 mcp SDK）后置——YAGNI，先让 agent 能查。
    # 只读纪律：三个 handler 只调 dl 的查询方法（search_fts/get_tree/
    # get_entry/get_content_preview/subtree_category_ids/get_category_paths），
    # 无任何写操作；tests/test_web_api.py 有 AST 级只读校验探针钉死。
    @router.get("/mcp/search")
    def mcp_search(q: str = "", limit: int = 20):
        """检索（只读）：FTS 查询，返回命中条目（agent 查询入口）。"""
        hits = dl.search_fts(q, limit=max(1, min(int(limit), 100)))
        return {"query": q, "count": len(hits), "hits": [
            {"entry_id": h.entry_id, "title": h.title, "locator": h.locator,
             "snippet": h.snippet, "rank": h.rank} for h in hits]}

    @router.get("/mcp/tree")
    def mcp_tree():
        """树遍历（只读）：全分类树 + 未分类精确计数（agent 遍历入口；
        计数走 COUNT 不封顶——list+limit 会截断出假数字）。"""
        return {"tree": dl.get_tree(), "uncategorized": dl.count_uncategorized()}

    @router.get("/mcp/entry/{entry_id}")
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

    @router.post("/sources/emmx/rejudge")
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
        from ...adapters.emmx import (_judge_cache_path, _load_judge_cache,
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
        from ...pipeline.sync import run_sync
        stats = run_sync(cfg, dl, locators, semantics, full=True,
                         source="emmx", purge_source="emmx",
                         purge_reason="web_rejudge")
        return {"rel": rel, "form": form,
                "purge": stats.get("purge"),
                "emmx": stats.get("sources", {}).get("emmx", {})}

    return router
