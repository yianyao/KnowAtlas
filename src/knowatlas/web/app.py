"""FastAPI 应用工厂（完整方案 §8；仅绑 127.0.0.1）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import install_security_middleware, register_routes

_STATIC_DIR = Path(__file__).resolve().parent / "static"


class _NoStoreHTML(StaticFiles):
    """HTML 入口加 Cache-Control: no-store（批次 106）。

    症状：改了 index.html，用户标签页仍端着旧 DOM，报「看不到修复」；
    根因是浏览器按 ETag 把 HTML 缓在内存里，不刷新就永远不校验。
    只对 text/html 生效——js/css/字体照常走 ETag，不牺牲静态资源缓存。
    """

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.headers.get("content-type", "").startswith("text/html"):
            resp.headers["Cache-Control"] = "no-store"
        return resp


def create_app(cfg, dl, locators, semantics) -> FastAPI:
    app = FastAPI(title="KnowAtlas（知道）", version="0.1.0",
                  docs_url=None, redoc_url=None, openapi_url=None)
    install_security_middleware(app, cfg)
    register_routes(app, cfg, dl, locators, semantics)
    if _STATIC_DIR.is_dir():
        app.mount("/", _NoStoreHTML(directory=str(_STATIC_DIR), html=True), name="static")
    return app
