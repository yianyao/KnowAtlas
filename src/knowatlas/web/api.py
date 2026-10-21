"""REST 端点（完整方案 §8）+ H5 五条安全约束。

安全约束（仅绑 127.0.0.1 不够——挡不住 CSRF 与 DNS rebinding）：
1. Host 校验；2. Origin 校验；3. 写操作 X-KnowAtlas-Token；4. content-type 白名单；
5. CORS 不放宽（bookmarklet 走 GET 跳转 index.html?add= 由首页同源提交会话请求，不做跨站 POST；?token= 仅作 CLI/脚本兜底）。
"""

from __future__ import annotations

import hashlib
import os
import uuid
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

    _CLOUD_PALETTE = ("#d1495b", "#e07a3c", "#c9a227", "#5f9e4e", "#2e9e83",
                      "#2b8fb3", "#3f6fb5", "#63599e", "#8d5aa8", "#b5497e",
                      "#a4485f", "#5f6b7a")
    # 词元噪音停用词（真实库冒烟 2026-10-21：markdown 残片/数据导出占位符）
    _CLOUD_NOISE = frozenset({
        "nan", "pass", "unnamed", "null", "none", "undefined", "na",
        "true", "false", "nbsp", "utf", "utf8", "utf-8",
    })

    def _cloud_word_ok(kw: str) -> bool:
        """词元准入：至少一个字母（滤纯数字/「2024年」类）、非纯符号/标点
        （##、--- 类 markdown 残片）、非噪音停用词、长度 ≥2（md/py 类英文短词
        反映库构成，保留）。"""
        import re as _re  # noqa: PLC0415 热路径外沿导入，避免模块级 re 依赖面
        if len(kw) < 2:
            return False
        if not _re.search(r"[^\W\d_]", kw):       # 无任何字母
            return False
        if _re.fullmatch(r"[\W_]+", kw):          # 纯符号/标点
            return False
        if kw.lower() in _CLOUD_NOISE:
            return False
        return True

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

    @app.post("/api/threads/{thread_id}/digest")
    async def digest_thread(thread_id: str, request: Request):
        """thread_digest + delta_summarize（第五十五批，§9.4，LLM 摘要后置）。

        delta_summarize：只对缺 meta.delta_summary 的条目跑（省 token），
        产物落 entries.meta.delta_summary；thread_digest：thread 层跑一次，
        产物落 threads.digest。llm 不可用/失败 = 两层都静默降级，不写库，
        线程视图照常显示原始正文（摘要是压缩表示，原始层永在）。
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
