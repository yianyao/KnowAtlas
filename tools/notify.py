#!/usr/bin/env python3
"""兼容壳：等价于 ``session-guard notify``。

真正的实现在独立仓库 ../session-guard（可跨机安装）：``session-guard notify``。
保留本文件是为了让既有命令继续可用：
    uv run python tools/notify.py --status
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_guard_bridge import run  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run("notify"))