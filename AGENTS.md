# AGENTS.md —— kpe 操作卡（给自动化 Agent）

> 这是一个**独立命令行工具**，不依赖任何宿主项目。整个仓库只有 `kpe/` 源码、
> `tests/` 与 `examples/`；产物写到 `--out` 指定的目录，不碰数据库、不改系统状态。
>
> 读代码前先读本卡；下面每一条都是踩过的坑。

## 0. 一句话

```bash
python -m kpe chunks <输入> --out <目录>        # 免费，先跑这个
python -m kpe extract <目录> --base-url ... --model ... --api-key-env ... --limit 3
python -m kpe review <目录>
```

## 1. 环境

- Python ≥ 3.10；唯一第三方依赖 `pdfplumber`（解析 PDF 用；只跑 Markdown/文本时也要装，因为模块顶层 import）。
- 本仓库自带 `pyproject.toml`：`uv run --with pdfplumber python -m kpe --version` 可直接用，不必先 `uv sync`。
- 跑测试：`uv run --with pdfplumber --with pytest python -m pytest -q`（14 项，离线，不需要 key）。

## 2. 必须遵守

1. **不要用裸 `kpe` 入口**：部分 Windows 机器有应用程序控制策略，`kpe.exe` 会被拦
   （`Failed to spawn: kpe` / `os error 4551`）。统一写 `python -m kpe`。
2. **key 只从环境变量读**：`--api-key-env` 传的是**变量名**，不是 key 本身。不要把 key
   写进命令行历史、配置或产物。
3. **先免费后付费**：`chunks` 不调模型；`extract` 先 `--limit 3` 验证 key/网络/JSON，
   再全量。全量失败可以用 `--retry-failed` 补齐，不会重复花钱。
4. **产物目录可丢弃也可续跑**：`cache/` + `done.jsonl` 决定哪些块已完成；
   `--redo` 才全重跑。不要为了「重来」去删目录，先看 `stats`。
5. **改动 `kpe/` 后跑测试**；`tests/` 零网络、零 key，别引入需要网络的测试。

## 3. 常见故障对照

| 现象 | 处理 |
|---|---|
| `No module named pdfplumber` | `uv run --with pdfplumber ...` 或 `pip install pdfplumber` |
| `No module named kpe` | 不在仓库根目录；`cd` 到含 `kpe/` 的目录，或 `pip install .` |
| `环境变量 XXX 为空` | key 没注入当前进程；用 `set`/`export` 后同一条命令里跑 |
| HTTP 401 / 429 | key 错或限流；降 `--workers`，稍后重试 |
| `没有待处理的块（都已 done…）` | 正常；换 `--out` 目录或加 `--redo` |
| 分块 `目录条=0` | PDF 没有可解析目录，已退化为窗口分块，可继续 |
| 中文乱码（Windows） | `chcp 65001` + `PYTHONIOENCODING=utf-8` |

## 4. 成本纪律

- `--price-in/--price-out`（元/百万 token）传进去，结束时会打印本次估算成本。
- 参考：304 页 / 44 万字 → 96 块 / 571 点 ≈ ¥0.85、130 s（DeepSeek 关思考 4 并发）。
- 免费模型（8B）可行但慢（约 6–10 s/块），先 `--limit 3` 看质量再决定。

## 5. 版本与发布

- 版本号在 `kpe/__init__.py::__version__` 与 `pyproject.toml` 两处，**一起改**。
- 发布：`uv build` 产 wheel/sdist；仓库 MIT，提交信息用 `feat:/fix:/docs:/test:` 前缀。