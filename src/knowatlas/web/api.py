"""REST 端点（完整方案 §8）+ H5 五条安全约束。

安全约束（仅绑 127.0.0.1 不够——挡不住 CSRF 与 DNS rebinding）：
1. Host 校验；2. Origin 校验；3. 写操作 X-KnowAtlas-Token；4. content-type 白名单；
5. CORS 不放宽（bookmarklet 走 GET 跳转 index.html?add= 由首页同源提交会话请求，不做跨站 POST；?token= 仅作 CLI/脚本兜底）。
"""

from __future__ import annotations

import hashlib
import os
import socket
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .ctx import AppCtx
from .routers import admin, categories, discovery, entries, graph, knowledge, threads

_TOKEN_HEADER = "x-knowatlas-token"
_WRITE_COOKIE = "knowatlas_write"  # 同源自动写凭据（HttpOnly，JS 读不到明文）
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


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


def local_addresses() -> list[str]:
    """本机网卡地址（含 loopback），用于局域网白名单。枚举失败只回 loopback。

    为什么按「本机地址」而不是「任意内网段」：Host 校验挡的是 DNS rebinding——
    攻击者只能让浏览器带**自己域名**的 Host 来打，枚举本机地址既够手机用，
    又不会把 192.168.0.0/16 整个放进来（那等于把校验关掉）。
    """
    found: set[str] = {"127.0.0.1"}
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP):
            addr = info[4][0]
            if addr:
                found.add(addr)
        for addr in socket.gethostbyname_ex(host)[2]:
            found.add(addr)
    except OSError:  # 断网 / 主机名解析不了：只留 loopback，不抛
        pass
    return sorted(found)


def allowed_hosts(cfg: Any) -> set[str]:
    """Host 白名单：loopback 恒放行；`serve --host 0.0.0.0`（或配了非 loopback 的
    server_host）时追加本机网卡地址 —— 手机经 `http://<内网IP>:8420` 才进得来。"""
    port = _port_of(cfg)
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    bound = str(cfg.get("general.server_host", "127.0.0.1")).strip()
    if bound and bound not in _LOOPBACK:
        for addr in local_addresses():
            hosts.add(f"{addr}:{port}")
            if ":" in addr:  # IPv6 在 Host 头里带方括号
                hosts.add(f"[{addr}]:{port}")
    return hosts


def allowed_origins(cfg: Any) -> set[str]:
    """Origin 白名单（防 CSRF）：与 Host 白名单同源推导，只放 http。"""
    return {f"http://{h}" for h in allowed_hosts(cfg)}


def lan_urls(port: int) -> list[str]:
    """本机局域网访问 URL（排除 loopback，IPv6 带方括号）——serve 启动打印用。"""
    out: list[str] = []
    for addr in local_addresses():
        if addr in ("127.0.0.1", "::1"):
            continue
        out.append(f"http://{'[' + addr + ']' if ':' in addr else addr}:{port}")
    return out


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
    """Host / Origin 校验（约束 1、2）。白名单按 cfg 现算，见 allowed_hosts()。"""
    hosts = allowed_hosts(cfg)
    origins = allowed_origins(cfg)

    @app.middleware("http")
    async def _host_origin_guard(request: Request, call_next):  # noqa: ANN202
        host = request.headers.get("host", "")
        if host not in hosts:
            return JSONResponse(
                {"error": {"code": "FORBIDDEN_HOST",
                           "message": f"Host 不在白名单：{host}（防 DNS rebinding）"}},
                status_code=403,
            )
        origin = request.headers.get("origin")
        if origin is not None and origin not in origins:
            return JSONResponse(
                {"error": {"code": "FORBIDDEN_ORIGIN",
                           "message": f"Origin 不在白名单：{origin}（防 CSRF）"}},
                status_code=403,
            )
        return await call_next(request)


def register_routes(app: FastAPI, cfg: Any, dl: Any, locators: Any, semantics: Any) -> None:
    """注册全部 REST 端点：URL 与响应结构逐字不变，按域拆在 routers/ 下。

    include 顺序 = 原 register_routes 里各域首个端点的出现顺序（FastAPI 按注册顺序匹配，
    同域内的顺序由各 router 文件保证；`/api/entries/linkage` 等静态段先于 `/{entry_id}`）。
    """
    ctx = AppCtx(cfg=cfg, dl=dl, locators=locators, semantics=semantics)
    for module in (discovery, admin, graph, categories, entries, knowledge, threads):
        app.include_router(module.register(ctx), prefix="/api")
