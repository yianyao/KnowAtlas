"""三份参考文档必须与源码一致：过期就红，避免文档悄悄漂移。

对应的生成器是 `tools/gen_docs.py`（`--check` 只比对不写）。
过期时的修法：`uv run python tools/gen_docs.py`，然后一起提交。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reference_docs_in_sync() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "gen_docs.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, (
        "参考文档与源码不一致，跑 `uv run python tools/gen_docs.py` 后提交：\n"
        f"{proc.stdout}\n{proc.stderr}"
    )