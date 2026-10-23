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
