# 知道 KnowAtlas

个人知识统一索引与分类导航工具：不动原始数据，为分散在各处的知识源建立共享的结构化元数据，
以分类树 / 词云 / 关系图为入口，逐层下钻并回溯到原始来源。

- 仓库：https://github.com/yianyao/KnowAtlas
- 契约文档：`docs/design/`（权威版本）；命名定稿：中文「知道」，英文 **KnowAtlas**
  （包名 `knowatlas`，环境变量前缀 `KNOWATLAS_`，写操作头 `X-KnowAtlas-Token`，配置 `config/knowatlas.toml`）

## 架构一句话

三层 + 两契约：**源适配器**（只翻译，不抓取不分类）→ **内容获取器**（按 locator scheme 注册，跨源共享）
→ **语义处理器**（按 task 注册，与源无关）；两契约 = 统一数据层（SQLite，唯一事实来源）+ 能力注册表。

## 快速开始

```bash
# 1. 环境——二选一：

# A. uv（推荐）：依赖已声明在 pyproject.toml，一条命令装齐
uv sync --extra dev

# B. pip（Windows Git Bash 示例；路径按本机 venv 调整）
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-core.txt
.venv/Scripts/python -m pip install -e .

# 2. 配置：复制示例并填入本机路径（config/ 不入库，凭证只存环境变量名）
cp config/knowatlas.example.toml config/knowatlas.toml

# 3. 初始化数据层（建表 + 注册内置能力 + 首条 run 记录）
#    uv 用户把下面的 .venv/Scripts/python 换成 uv run python
.venv/Scripts/python -m knowatlas kinit

# 4. 手动入口：贴一个链接，自动 抓正文 → 归类 → 入树
.venv/Scripts/python -m knowatlas kadd https://example.org/some/article

# 5. 本地服务（默认 127.0.0.1:8420；写操作需 KNOWATLAS_WEB_TOKEN）
.venv/Scripts/python -m knowatlas serve
```

## 目录速览

| 路径 | 说明 |
|---|---|
| `src/knowatlas/datalayer/` | 唯一允许碰 SQLite 的模块（防腐化红线） |
| `src/knowatlas/adapters/` | 第一层：每源一个文件，只产出统一条目 |
| `src/knowatlas/fetchers/` | 第二层：按 scheme 注册的获取器 |
| `src/knowatlas/semantic/` | 第三层：先验 → 规则 → embedding/LLM 三级流水线 |
| `src/knowatlas/registry/` | 能力注册表（新能力 = 新文件 + builtins.py 一行） |
| `tests/` | 契约 / canary / 数据层 / kadd 端到端 |

## 纪律（详见 docs/design/知识索引工具-实施约束规范.md）

- 改任何契约（字段/scheme/表结构/接口签名）必须先写变更工单，改完跑 `pytest tests/test_canary.py`。
- 过程文件一律落盘到工作区 `temp/`，不进项目根；`config/` 凭证与 `data/` 运行数据永不入库。
- 仓库内文本一律 LF（`.gitattributes` 锁定）；本地 pre-commit 门禁 + CI 兜底双层。
