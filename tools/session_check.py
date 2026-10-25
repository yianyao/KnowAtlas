#!/usr/bin/env python3
"""兼容壳：等价于 ``session-guard check``。

真正的实现在独立仓库 ../session-guard（可跨机安装）：``session-guard check``。
保留本文件是为了让既有命令继续可用：
    uv run --with zstandard python tools/session_check.py
退出码不变：0 NEW_SESSION / 10 SAME_SESSION_UNCOMPACTED /
20 SAME_SESSION_COMPACTED / 30 NO_HANDOFF / 40 NO_SESSION。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_guard_bridge import run  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run("check"))