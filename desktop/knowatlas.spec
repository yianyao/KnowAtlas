# -*- mode: python ; coding: utf-8 -*-
"""KnowAtlas 桌面壳打包编排（第七十九批）。

6 批桌面化路线第 6 批：把 desktop/main.py（pywebview 壳 + 现有 FastAPI 服务）
打成 Windows 单目录应用。业务源码（src/knowatlas）只作依赖收集，零改动——
web/static 以数据文件落位 knowatlas/web/static，app.py 的
`Path(__file__).parent / "static"` 在冻结环境下解析到 sys._MEIPASS 同位路径。

构建（仓库根目录）：
    .venv/Scripts/python.exe desktop/build.py
产物：
    dist/KnowAtlas/KnowAtlas.exe

体积纪律：本地向量模型链（torch/sentence_transformers/transformers）显式
排除——embed.py 为函数内延迟可选导入，缺失时业务侧已有优雅降级；打包版
不含模型（约 2GB），需要 sim 通道时用源码方式运行。

运行数据纪律（项目可迁移铁律）：exe 不含任何硬编码路径；config 仍按
CWD 的 config/knowatlas.toml 或 KNOWATLAS_CONFIG 解析，数据目录仍由
KNOWATLAS_HOME / ~/.knowatlas 决定——与 serve 完全同规则。
"""

import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None

_here = os.path.dirname(os.path.abspath(SPEC))
_root = os.path.dirname(_here)                      # 仓库根
_src = os.path.join(_root, "src")

# web/static 数据 + pywebview（WebView2 运行库/加载器 dll）+ clr_loader
datas, binaries, hiddenimports = [], [], []
for pkg in ("webview", "clr_loader", "pythonnet"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas.append((os.path.join(_src, "knowatlas", "web", "static"),
              "knowatlas/web/static"))
# 迁移文件目录：schema.py 运行时 iterdir() 动态发现（冻结后 .py 进 PYZ，
# 目录必须以数据文件落位同位路径，冒烟实测踩坑后补）
datas.append((os.path.join(_src, "knowatlas", "datalayer", "migrations"),
              "knowatlas/datalayer/migrations"))

hiddenimports += [
    # pywebview Windows 后端（EdgeChromium 优先，WinForms 兜底）
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    # uvicorn 程序化启动的动态加载组件（loops/protocols 按 setuptools 入口发现）
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
]

a = Analysis(
    [os.path.join(_here, "main.py")],
    pathex=[_here, _src],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 本地向量模型链（体积；embed 延迟导入有降级）
        "torch", "sentence_transformers", "transformers",
        # 与桌面壳无关的重件
        "matplotlib", "tkinter", "IPython", "pytest",
    ],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KnowAtlas",
    icon=os.path.join(_here, "icon.ico"),
    debug=False,
    strip=False,
    upx=False,
    console=False,          # 桌面应用无控制台；诊断信息走窗口内界面与日志
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="KnowAtlas",
)
