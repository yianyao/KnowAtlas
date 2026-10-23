# 桌面壳（第七十四批）

`main.py` = pywebview 无框窗口 + 现有本地服务（守护线程内跑同一 FastAPI app）。
业务代码零改动：装配与 `python -m knowatlas serve` 完全一致。

## 运行

```bash
# 仓库根目录；依赖为可选装（缺失时脚本会提示）
pip install pywebview
python desktop/main.py                  # 默认 127.0.0.1:8420（取 config）
python desktop/main.py --port 9000      # 覆盖端口
python desktop/main.py --width 1280 --height 800
```

- Windows 需 WebView2 运行时（Win10/11 默认自带）。
- 数据位置与 `serve` 同规则：`KNOWATLAS_HOME` → cwd → `~/.knowatlas`；
  本目录无任何硬编码用户名/盘符（换机直接跑）。
- 浏览器方式仍可用：`python -m knowatlas serve` 后访问同一地址，
  界面一致（窗口控制按钮仅在桌面壳内出现）。

## 界面构成

- 标题栏：品牌区为拖拽区（`.pywebview-drag-region`，pywebview 官方 drag region
  模式，`easy_drag=False`）；全局搜索、收录、设置、窗口控制（最小化/最大化/关闭，
  经 `js_api` 调窗口方法，未装 pywebview 时自动隐藏）。
- 左导航栏：检索 / 关系图 / 线索库 / 词云 / 时间线 / 管理（原页签行改竖排，
  JS 选择器不变）。
- 分类树面板：默认展开，◀ 折叠（快捷键 `[`，偏好记 localStorage）。
- 状态栏：服务地址与库统计（`/api/stats`）。
- 样式令牌：`src/knowatlas/web/static/tokens.css`（深色令牌）+
  `components.css`（壳组件）；视图层样式仍在 index.html 内联块（批次 75 起
  逐步令牌化）。

## 打包（第七十九批）

```bash
# 仓库根目录；打包依赖缺失时 build.py 会给出精确安装命令
.venv/Scripts/python.exe -m pip install pyinstaller pywebview
.venv/Scripts/python.exe desktop/build.py
```

- 产物：`dist/KnowAtlas/KnowAtlas.exe`（单目录版——启动快、免每次解压；
  整个 `dist/KnowAtlas` 目录即应用本体，任意拷贝）。
- 编排：`desktop/knowatlas.spec`。web/static 按数据文件落位
  `knowatlas/web/static`（app.py 的 `__file__` 相对定位在冻结环境解析到
  同位路径，业务零改动）；pywebview/clr_loader/pythonnet 整包收集
  （WebView2 加载器 dll）。
- **体积纪律**：本地向量模型链（torch/sentence_transformers/transformers）
  显式排除——embed.py 为函数内延迟可选导入，缺失时优雅降级。打包版不含
  模型（约省 2GB），需要检索 sim 通道时用源码方式运行。
- 数据规则与 serve 完全一致：config 按 CWD 的 `config/knowatlas.toml` 或
  `KNOWATLAS_CONFIG` 解析；数据目录 `KNOWATLAS_HOME` → `~/.knowatlas`。
  把 exe 放仓库根目录双击即用本仓库 config（推荐），放别处则走默认库。
- `--port/--host` 覆盖已写回 cfg（第七十九批冒烟实测修补）：安全中间件的
  Host 白名单按 cfg 端口生成，壳层在 create_app 前同步覆盖值，换端口探活
  与浏览器访问不会被 FORBIDDEN_HOST 拒掉（业务文件零改动）。

## 真机验收清单（批次 74-79 累计；双通道=桌面壳 + 浏览器）

1. 无框窗口拖拽：按住标题栏品牌区/空白间隔拖动；点击搜索框、按钮不误拖。
2. 窗口控制：最小化/最大化-还原/关闭三钮；浏览器通道三钮隐藏。
3. 三栏检索：分类树/结果列表/预览面板拖拽调宽；收起树（`[`）与预览；
   重启后宽度记忆生效。
4. 分类树折叠：◀ 折叠/展开，`[` 快捷键；localStorage 记忆。
5. Ctrl+K 命令面板：六视图切换、折叠/展开、收录、聚焦搜索、刷新统计。
6. 浮层一致性：toast（收录失败等）、ka.confirm/prompt 模态框均为深色令牌
   样式（原生 Chromium 浅色弹窗应零出现）。
7. 关系图：深色画布、焦点黄环、边 tooltip 深色；放射/层级/稀疏折叠交互。
8. 词云：词元为深底亮化色（非浅底中调色）；点词过滤正常。
9. 时间线：柱色为 accent 蓝、tooltip/轴深色；桶点击下钻。
10. 管理页：七入口切换、暂存/舍弃/勘误操作浮层正常；书签坞深色。
11. 深色一致性：整窗无白底闪块（`color-scheme: dark` + 令牌全覆盖）。
12. 打包版特有：exe 双击启动 ≤5 秒出窗；数据落在 `~/.knowatlas`；
    写操作（收录/改分类）可用（同源会话令牌自动注入）。
