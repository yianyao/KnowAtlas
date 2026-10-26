# kpe —— 长文知识点抽取

把一本长书（PDF / Markdown / 纯文本）切成结构块，逐块抽「能脱离原文独立读懂」
的知识点，产出可复核的 JSONL + Markdown 复核稿。

- **不依赖任何框架**：只用标准库 + `pdfplumber`，模型走任意 OpenAI 兼容接口；
- **不写数据库**：产物就是一目录文件，可版本化、可 diff；
- **可断点续跑**：每块响应落盘缓存，重跑不重复花钱；
- **成本可控**：先用 `chunks` 免费看结构，再用 `--limit 3` 花几分钱试通。

## 安装

需要 Python ≥ 3.10。

```bash
git clone https://github.com/yianyao/kpe.git
cd kpe
uv run --with pdfplumber python -m kpe --version      # 0.1.0
```

或装进当前环境（之后可直接 `python -m kpe`）：

```bash
pip install .
```

> **Windows 提示**：部分机器的应用程序控制策略会拦控制台入口 `kpe.exe`
> （报 `os error 4551`）。遇到就统一用 `python -m kpe ...`，功能完全一样。

## 三步

```bash
# 1) 分块（不花钱）：先确认章节路径、页码、块大小
python -m kpe chunks examples/sample.md --out temp/sample

# 2) 抽取（花钱）：只有 --base-url/--model/--api-key-env 需要按你的服务商改
set KNOWATLAS_LLM_API_KEY=sk-...
python -m kpe extract temp/sample ^
  --base-url https://api.siliconflow.cn/v1 ^
  --model deepseek-ai/DeepSeek-V4.1-Flash ^
  --api-key-env KNOWATLAS_LLM_API_KEY ^
  --thinking off --workers 4 --price-in 2 --price-out 8

# 3) 复核稿
python -m kpe review temp/sample
```

先花几分钱试 3 块，确认 key、网络、JSON 都通：

```bash
python -m kpe extract temp/sample ... --limit 3
```

## 四个命令

| 命令 | 作用 |
|---|---|
| `chunks` | 只分块，不调模型；打印页数、目录条数、页偏移、块数 |
| `extract` | 逐块抽点；`--chapter` 选章、`--limit N` 试跑、`--retry-failed` 补失败、`--redo` 全重跑 |
| `review` | 按章生成 `review.md`；`--with-sections` 带每节路径与页码 |
| `stats` | 打印 manifest + 按现有产物现算的总点数/token/耗时 |

完整参数见 [`使用手册.md`](使用手册.md)。

## 产物（`--out` 目录）

| 文件 | 内容 |
|---|---|
| `manifest.json` | 书元数据、目录条数、页偏移、分块参数、块数 |
| `chunks.jsonl` | 每块：章节路径、页码、字符数、正文 |
| `cache/<id>.json` | 每次模型原始响应 + usage（断点续跑的依据） |
| `points.jsonl` | 点：章节、页码、text、quote、quote_ok、模型 |
| `rejected.jsonl` | 被闸门拒掉的点及原因（调 prompt 用） |
| `failed.jsonl` | 失败块（`--retry-failed` 重跑） |
| `stats.json` | 块/点/拒/重复/失败/quote 命中/token/耗时 |
| `review.md` | 按章分组的复核稿 |

## 分块与校验规则（摘要）

- **分块**：PDF 优先解析目录页（印刷页码 + 页偏移），按章/节/小节合并到
  ~6,000 字；无目录时退化到 Markdown 标题或 6,000 字窗口；跳过前言/目录/
  致谢/思考题/本章小结（`--keep-front` 可保留前言）。
- **抽取**：每块 1–6 条，自包含、一条一事、`quote` 逐字 15–40 字、逐段扫描。
- **校验**：JSON 容错（解析失败自动修复重问一次）；`quote` 去标点后模糊匹配；
  最小自洽闸门（过短 / 代词开头 / 截断 / 目录 / 围栏）；书内去重。

## 实测成本参考

《AI-Agents-in-Depth》304 页 / 44 万字，DeepSeek 关思考、4 并发：

| 指标 | 值 |
|---|---:|
| 块数 | 96 |
| 知识点 | 571 |
| quote 命中 | 570 / 571 |
| 成本 | ≈ ¥0.85 |
| 耗时 | 130 s |

换模型只改 `--base-url / --model / --api-key-env`；`--thinking` 用
`off`（DeepSeek）、`on` 或 `omit`（不传该参数，混元等）。

## 目录结构

```
kpe/
  kpe/{cli,pdf,chunk,prompt,llm,validate,store,review}.py
  tests/          # 14 项 pytest，零网络
  examples/       # 零成本自检样例
```

## 许可

MIT，见 [LICENSE](LICENSE)。