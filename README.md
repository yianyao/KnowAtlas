# kpe —— 大文件知识点抽取

把一本长书（PDF/Markdown/纯文本）切成结构块，逐块抽"能脱离原文独立读懂"的
知识点，产出可复核的 JSONL + Markdown。**不依赖 KnowAtlas**，任何
OpenAI 兼容模型都能用；以后可作为库嵌回 KnowAtlas。

## 依赖与运行

只需 `pdfplumber`（本仓库已装）。不装包也能直接跑：

```bash
# Windows PowerShell（仓库根目录）
$env:PYTHONPATH = "tools/kpe"
uv run python -m kpe --help
```

或在 `tools/kpe` 下 `pip install -e .` 后直接用 `kpe`：

```bash
pip install -e D:\sData\git\KnowAltas\tools\kpe
kpe chunks "D:\sData\KnowLedge\AI-Agents-in-Depth-zh-CN .pdf" --out temp/kpe-aiagents
```

## 实测（AI-Agents-in-Depth，304 页 / 44 万字）

| 指标 | 值 |
|---|---:|
| 块数 | 96 |
| 知识点 | 571 |
| quote 命中 | 570/571 |
| 成本 | ≈ ¥0.85（DeepSeek 关思考、4 并发） |
| 耗时 | 130 s |

复核稿：`temp/kpe-aiagents/review.md`；详见
`docs/design/试跑-AI-Agents-kpe-2026-10-25.md`。

## 三步

```bash
# 1) 分块（不花钱）：先看章节路径/页码/块大小对不对
uv run python -m kpe chunks "D:\sData\KnowLedge\AI-Agents-in-Depth-zh-CN .pdf" \
  --out temp/kpe-aiagents

# 2) 抽取（示例：SiliconFlow 的 DeepSeek，关思考）
$env:KNOWATLAS_LLM_API_KEY_SF1 = "..."   # 不要写进配置文件
uv run python -m kpe extract temp/kpe-aiagents \
  --base-url https://api.siliconflow.cn/v1 \
  --model deepseek-ai/DeepSeek-V4.1-Flash \
  --api-key-env KNOWATLAS_LLM_API_KEY_SF1 \
  --thinking off --workers 4 \
  --price-in 2 --price-out 8

# 3) 复核稿
uv run python -m kpe review temp/kpe-aiagents
```

先跑 3 章试点：

```bash
uv run python -m kpe extract temp/kpe-aiagents ... \
  --chapter "第 2 章" --chapter "第 3 章" --chapter "第 7 章"
```

## 换模型（含腾讯混元 Hy3）

所有模型走同一套 OpenAI 兼容接口，只换三个参数：

```bash
uv run python -m kpe extract temp/kpe-aiagents \
  --base-url https://api.hunyuan.cloud.tencent.com/v1 \
  --model "<Hy3 的 model id，以腾讯云文档为准>" \
  --api-key-env HUNYUAN_API_KEY \
  --thinking omit --workers 2
```

- `--thinking off`：DeepSeek 关思考（快、省）；`on` 开思考；`omit` 不传该参数
  （混元/其他模型用这个）。
- 免费模型也可：`--model Qwen/Qwen3-8B` 或 `THUDM/GLM-4-9B-0414`（SiliconFlow），
  质量见 `docs/design/` 的模型矩阵实测。

## 产物（`--out` 目录）

| 文件 | 内容 |
|---|---|
| `manifest.json` | 书元数据、目录条数、页偏移、分块参数、块数 |
| `chunks.jsonl` | 每块：章节路径、页码、字符数、正文 |
| `cache/<id>.json` | 每次 LLM 原始响应 + usage（断点续跑，重跑不重复花钱） |
| `points.jsonl` | 点：章节、页码、text、quote、quote_ok、模型 |
| `rejected.jsonl` | 被闸门拒掉的点及原因（调 prompt 用） |
| `failed.jsonl` | 失败块（`--retry-failed` 重跑） |
| `stats.json` | 块/点/拒/重复/失败/quote 命中/token/耗时 |
| `review.md` | 按章分组的复核稿（默认不带每节路径/页码，要溯源加 `--with-sections`） |

## 规则

- **分块**：PDF 优先解析目录页（印刷页码 + 页偏移），按章/节/小节合并到
  ~6,000 字；无目录退化 Markdown 标题或 6,000 字窗口；跳过前言/目录/致谢/
  思考题/本章小结。
- **引言坑**：若某本书的"引言"是 L1 且正文全是 L2/L3，不能按"祖先被跳过"
  级联跳过（否则整本丢）；现在只按自身标题跳过，并把
  `全书结构/如何阅读本书/前置知识/关于作者/Contents…` 等加入跳过名单。
- **抽取**：1–6 条/块，自包含、一条一事、quote 逐字 15–40 字、逐段扫描。
- **校验**：JSON 容错（失败自动修复重问一次）；quote 去标点后模糊匹配；
  最小自洽闸门（过短/代词开头/截断/目录/围栏）；书内去重。
- **断点续跑**：缓存命中直接复用；`--retry-failed` 只重跑失败块。

## 目录

```
tools/kpe/
  kpe/{cli,pdf,chunk,prompt,llm,validate,store,review}.py
  tests/
```