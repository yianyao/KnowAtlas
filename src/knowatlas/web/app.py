"""FastAPI 应用工厂（完整方案 §8；仅绑 127.0.0.1）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import install_security_middleware, register_routes

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(cfg, dl, locators, semantics) -> FastAPI:
    app = FastAPI(title="KnowAtlas（知道）", version="0.1.0",
                  docs_url=None, redoc_url=None, openapi_url=None)
    install_security_middleware(app, cfg)
    register_routes(app, cfg, dl, locators, semantics)
    if _STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
    return app
