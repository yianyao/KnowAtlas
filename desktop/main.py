"""桌面壳入口（第七十四批）：pywebview 无框窗口 + 现有 FastAPI 服务（守护线程内）。

业务零改动——装配与 `knowatlas serve` 逐行同构（load_config → DataLayer →
build_registries → create_app），区别仅两处：uvicorn 搬进守护线程；窗口由
pywebview 在主线程跑（pywebview 要求主线程）。

依赖（可选，缺失时本脚本给出安装指引）：
    pip install pywebview
    # 或一次性装全部可选依赖：
    pip install -r requirements-optional.txt
Windows 需 WebView2 运行时（Win10/11 默认自带；缺失时 pywebview 会提示安装）。

运行（仓库根目录）：
    python desktop/main.py                 # 默认读 config：127.0.0.1:8420
    python desktop/main.py --port 9000     # 覆盖端口
    python desktop/main.py --width 1280 --height 800

换机器迁移：数据目录由 KNOWATLAS_HOME / ~/.knowatlas 决定（与 serve 同规则），
本脚本不含任何硬编码用户名/盘符（项目可迁移铁律第 4 条）。
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import time
import urllib.request


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="knowatlas-desktop",
        description="知道 KnowAtlas 桌面壳（pywebview + 现有本地服务）")
    p.add_argument("--host", default=None, help="覆盖服务监听地址（默认取 config）")
    p.add_argument("--port", type=int, default=None, help="覆盖服务端口（默认取 config）")
    p.add_argument("--width", type=int, default=1440, help="窗口初始宽（默认 1440）")
    p.add_argument("--height", type=int, default=900, help="窗口初始高（默认 900）")
    return p.parse_args()


class _DesktopApi:
    """暴露给前端的窗口控制（pywebview js_api）。窗口未就绪时全部安全空转。"""

    def __init__(self) -> None:
        self._window = None
        self._maximized = False

    def bind(self, window) -> None:
        self._window = window

    def minimize(self) -> None:
        w = self._window
        if w is not None and hasattr(w, "minimize"):
            w.minimize()

    def toggle_maximize(self) -> None:
        w = self._window
        if w is None:
            return
        try:
            if self._maximized:
                if hasattr(w, "restore"):
                    w.restore()
                self._maximized = False
            else:
                if hasattr(w, "maximize"):
                    w.maximize()
                self._maximized = True
        except Exception:
            pass

    def close(self) -> None:
        w = self._window
        if w is not None and hasattr(w, "destroy"):
            w.destroy()


def main() -> int:
    args = _parse_args()
    try:
        import webview
    except ImportError:
        print("缺少依赖 pywebview。安装：pip install pywebview", file=sys.stderr)
        print("（或一次性装全部可选依赖：pip install -r requirements-optional.txt）",
              file=sys.stderr)
        return 2

    from knowatlas.config import load_config
    from knowatlas.datalayer.db import DataLayer
    from knowatlas.logging_setup import setup_logging
    from knowatlas.registry.builtins import build_registries
    from knowatlas.web.app import create_app

    cfg = load_config()
    setup_logging(cfg.log_level)
    dl = DataLayer(cfg.db_path)
    dl.init_schema()
    locators, semantics = build_registries(cfg)

    # 写令牌：与 serve 同策略——未设环境变量则生成本次会话令牌（桌面壳内写操作
    # 走同源会话 Cookie，用户无需手工粘贴；打印仅供排查）。
    token_env = str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN"))
    token = os.environ.get(token_env, "")
    if not token:
        token = secrets.token_urlsafe(16)
        os.environ[token_env] = token
        print(f"本次会话写令牌（桌面壳内写操作走同源 Cookie，无需手工粘贴）：{token}")

    app = create_app(cfg, dl, locators, semantics)
    host = args.host or str(cfg.get("general.server_host", "127.0.0.1"))
    port = int(args.port or cfg.get("general.server_port", 8420))
    url = f"http://{host}:{port}/index.html"

    import uvicorn

    server = threading.Thread(
        target=lambda: uvicorn.run(app, host=host, port=port, log_level="warning"),
        daemon=True,
    )
    server.start()

    # 等服务就绪再开窗（uvicorn 冷启动约数百毫秒；本机代理会拦截 localhost，
    # 显式绕过——见环境事实「全局 http_proxy 读走」坑）。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            opener.open(f"http://{host}:{port}/api/session", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        print("服务未在 10 秒内就绪，仍尝试打开窗口……", file=sys.stderr)

    api = _DesktopApi()
    window = webview.create_window(
        "知道 KnowAtlas",
        url,
        js_api=api,
        frameless=True,       # 无系统边框；标题栏自绘，拖拽区见 components.css
        easy_drag=False,      # 仅 .pywebview-drag-region 区域可拖（不误伤画布/选区）
        width=args.width,
        height=args.height,
        min_size=(1024, 680),
        background_color="#0C0E12",
    )
    api.bind(window)
    try:
        webview.start()
    finally:
        dl.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
