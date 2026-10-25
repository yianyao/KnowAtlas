"""让本仓库的 ``tools/*.py`` 转调到独立包 session-guard 的兼容桥。

解析顺序：
    1. 已安装的 ``session_guard``（pip / uv tool / pipx）
    2. 环境变量 ``SESSION_GUARD_SRC`` 指向的 ``src`` 目录
    3. 本仓库同级的 ``../session-guard/src``（本机默认布局）

独立仓库：D:\\sData\\git\\session-guard
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_importable() -> str:
    try:
        import session_guard  # noqa: F401

        return "installed"
    except ImportError:
        pass

    repo_root = Path(__file__).resolve().parent.parent
    candidates: list[Path] = []
    env = os.environ.get("SESSION_GUARD_SRC")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(repo_root.parent / "session-guard" / "src")
    for candidate in candidates:
        if (candidate / "session_guard" / "__init__.py").is_file():
            sys.path.insert(0, str(candidate))
            return str(candidate)

    sys.exit(
        "未找到 session_guard 包。任选其一：\n"
        "  pip install ../session-guard\n"
        "  把独立仓库放到本仓库同级（../session-guard）\n"
        "  设置 SESSION_GUARD_SRC=<session-guard>/src"
    )


def run(subcommand: str) -> int:
    ensure_importable()
    from session_guard.cli import main

    return main([subcommand, *sys.argv[1:]])