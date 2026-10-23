#!/usr/bin/env python3
"""KnowAtlas 桌面壳一键构建脚本（第七十九批；纯 stdlib）。

用法（仓库根目录，用项目 venv 跑）：
    .venv/Scripts/python.exe desktop/build.py

前置：venv 内已装 pyinstaller 与 pywebview（本脚本给出精确安装命令）。
产物：dist/KnowAtlas/KnowAtlas.exe（单目录版——启动快、免每次解压）。
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowatlas.spec")
DIST = os.path.join(ROOT, "dist", "KnowAtlas", "KnowAtlas.exe")


def _ensure_deps() -> None:
    missing = []
    for mod, pkg in (("PyInstaller", "pyinstaller"), ("webview", "pywebview")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("缺少依赖：" + "、".join(missing))
        print(f"安装：{sys.executable} -m pip install " + " ".join(missing))
        raise SystemExit(2)


def main() -> int:
    _ensure_deps()
    print("== KnowAtlas 桌面壳打包开始（单目录版，约 2-5 分钟）==")
    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean", SPEC]
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        print("打包失败（PyInstaller 退出码 %d）。" % proc.returncode, file=sys.stderr)
        return proc.returncode
    if not os.path.exists(DIST):
        print(f"打包流程结束但未找到产物：{DIST}", file=sys.stderr)
        return 1
    size_mb = os.path.getsize(DIST) / 1024 / 1024
    print(f"== 打包完成：{DIST}（exe {size_mb:.1f} MB）==")
    print("提示：dist/KnowAtlas 整个目录是应用本体——任意拷贝/发送均可，")
    print("双击 KnowAtlas.exe 运行；config 与数据目录规则与 serve 一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
