# AGENTS.md —— 知道 KnowAtlas 的仓库级 Agent 记忆

> 定位：只放**跨会话成立**的约定、坑与入口。状态数字现场取（跑测试、取提交号），不写死在这里。
> 本机专属事实（解释器路径、代理、凭据）写 `AGENTS.local.md`——已 gitignore，不提交。
> 背景依据：`docs/design/知识索引工具-实施约束规范.md`（下文第 4 节的出处，冲突时以本文为准并由用户裁决）。

## 0. 会话继续协议（用户 2026-10-25 定稿）

**触发词**：用户说「继续 / 接着 / 往下 / continue / resume」或任何同义表述，
即视为授权**直接开始**，不要再问「要继续吗」。

**开场三步，缺一不可**：

1. `uv run --with zstandard python tools/session_check.py`
   —— 判定当前是新会话 / 同会话已压缩 / 同会话未压缩。
2. 读 `docs/log.md` 最后一个「交接块」+「当前状态」，把「下一步」「不要重跑」抄进本轮计划。
3. `uv run --with zstandard python tools/context_probe.py`
   —— 取 `effective_pct`；它是相对**历史最高压缩水位**的占用，`window_pct` 不是风险指标。

**判定分支（session_check 退出码）**：

| 码 | 判定 | 动作 |
|---|---|---|
| 0 | `NEW_SESSION` | 按交接块继续；不要回读旧会话文件。 |
| 10 | `SAME_SESSION_UNCOMPACTED` | 同会话未压缩；若探针 HANDOFF/CRITICAL，立即写交接并停，不要硬撑。 |
| 20 | `SAME_SESSION_COMPACTED` | 摘要**有损**；先重读交接块 + 本文 + 相关源码/数据，核对后再动手，不要凭记忆重跑。 |
| 30 | `NO_HANDOFF` | 缺机器可读交接块；先读人类可读交接，接近阈值时补写带标记的交接块。 |

**阈值**：`effective_pct` >= 80% 收尾（WARN），>= 85% **停止并写交接**（HANDOFF），
>= 95% 立即停（CRITICAL）。**不要等 DSH 自动压缩**——压缩摘要会丢「不要重跑什么」
这类否定性事实，模型容易重复已完成工作或重跑贵命令。

**交接块必含**（模板见 `docs/log.md`「交接协议 v2」）：

- 当前目标 / 已完成（含产物路径与现场数字）/ 下一步（按序、首步可直接执行）/
  **不要重跑**（目录·批次·判据）/ 验证命令（新会话开场先跑哪条、期望输出）/ 已知失败与处理 /
  会话指纹（session id + compactions + tokens + 时间）。
- 必须带机器可读标记：`<!-- HANDOFF {"session":"...","compactions":N,"tokens":N,"at":"ISO8601","status":"HANDOFF",...} -->`。
  `session_check.py` 与 `context_watcher.py` 只认这个标记；`at` 是去重指纹，每次必须不同。

**停止动作**：写交接块 → 发通知（`uv run python tools/notify.py --title ... --body ... --level HANDOFF`，
或由 watcher 自动推）→ 明确告诉用户「请开新会话，说『继续』」。

**通知与 watcher**：

- `uv run python tools/notify.py --status` 看渠道与凭据；`--test` 自测。
- 微信渠道：PushPlus（推荐）/ Server酱 / WxPusher / 企业微信机器人；桌面 toast 是兜底。
- watcher：计划任务 `KnowAtlasContextWatcher` 每 2 分钟跑一次
  `context_watcher.py --once`；常驻方式 `powershell -NoProfile -File tools/start_watcher.ps1`。
- watcher 会在阈值、会话被压缩、`docs/log.md` 出现新交接块时推送；同级去重，冷却 1800s。

**证据要求**：继续协议开场的 `session_check` 判定与 `effective_pct` 要贴进回复，
让用户能核对没有误判；不要只说「我看过 log 了」。

## 1. 硬规则：写业务代码前先讲方案（用户 2026-10-24 追加，优先级最高）

**动手写业务代码之前，必须先说明「实现逻辑 + 步骤」，等用户确认后再操作。**

- 先给四件事：改哪些文件 / 为什么这么改（逻辑） / 分几步 / 动到哪些契约（表结构·字段·scheme·接口签名·config 键集）以及怎么验证。
- 用户点头 → 再改；用户没点头 → 只做只读排查，输出结论与方案。
- 「业务代码」包含：`src/knowatlas/` 下的 `pipeline/` `adapters/` `semantic/` `datalayer/` `web/`（含 `static/*.html|css|js`）、`cli.py`、`config.py`。
- 不受此约束（可直接做）：只读排查与读码、跑测试/探针、改文档（本文、`docs/design/`、`CHANGELOG.md`）、改 `config/*.example.toml` 的注释、`temp/` 下的过程脚本。

## 2. 项目是什么

个人知识统一索引与分类导航工具：不动原始数据，为分散各处的知识源建共享的结构化元数据，
以分类树 / 词云 / 关系图 / 线索库 / 时间线为入口逐层下钻，并回溯到原始来源。

**三层 + 两契约**：

| 层 | 目录 | 职责 |
|---|---|---|
| 源适配器 | `adapters/` | 每源一个文件，只翻译成统一条目，不抓取不分类 |
| 内容获取器 | `fetchers/` | 按 locator scheme（https/file/mail/emmx/…）注册，跨源共享 |
| 语义处理器 | `semantic/tasks/` | 按 task 注册，与源无关；先验 → 规则 → embedding/LLM 三级流水线 |

两契约：**统一数据层**（SQLite，唯一事实来源）+ **能力注册表**（`registry/`）。
Web 层：`web/app.py`（应用工厂）+ `web/api.py`（REST，含五条安全约束）。

## 3. 怎么跑

```bash
uv sync --extra dev                                    # 依赖在 pyproject.toml（uv.lock 已锁）
cp config/knowatlas.example.toml config/knowatlas.toml # config/ 整目录 gitignore
uv run python -m knowatlas kinit                       # 建表 + 注册内置能力
uv run python -m knowatlas serve                       # http://127.0.0.1:8420
uv run python -m pytest -q                             # 基线：全绿（含 1 skipped）
```

- 没有 `config/knowatlas.toml` 时**所有**命令都会 `ConfigError` 退出，不会静默用默认值（`config.py::load_config`）。
- `[llm]` 的 key 只从环境变量读（`KNOWATLAS_LLM_API_KEY`）；未设时语义层静默跳过，主链路照跑——条目会停在「未归类」，`kadd` 的 DeepSeek 兜底抓取同样跳过。
- CLI 子命令：`kinit` `kadd` `ksync` `serve` `kexport` `kbackup` `ktest` `kcheck` `kpoints` `kaging` `kerrata` `kpeimport`。
- **长文知识点抽取走独立工具 `tools/kpe`**（可安装包 `kpe`，分块→抽取→复核，产物 `<out>/{manifest.json,points.jsonl}`），
  入库用 `kpeimport <out> [--entry ID|--match 通配] [--replace] [--dry-run]`；
  点 meta 固定带 `extractor="kpe"`、`book`、`section_path`、`quote`（见
  `docs/design/变更工单-2026-10-25-KPE导入适配器.md`）。
- **`tools/kpe` 的上游是独立仓库** <https://github.com/yianyao/kpe>（MIT，`D:\kpe` 为唯一开发处）。
  改 KPE 一律在 `D:\kpe` 提交推送，再在本仓库拉回来：
  `git subtree pull --prefix=tools/kpe kpe main --squash`（remote `kpe` 已在 `.git/config`）。
  **方向单向**：不要在本仓库直接改 `tools/kpe` 下的代码，否则下次 pull 会冲突。
- 桌面壳（`desktop/main.py`，pywebview）是可选装：装不上不影响 `serve`。
- **会话守卫工具已抽成独立仓库** `../session-guard`（可跨机安装：`pip install .` / `uv tool install .`，
  命令 `session-guard probe|check|watch|notify`）。`tools/context_probe.py`、`session_check.py`、
  `context_watcher.py`、`notify.py` 只是薄封装（`tools/session_guard_bridge.py`），
  按「已安装包 > `SESSION_GUARD_SRC` > 同级 `../session-guard/src`」解析；旧命令与计划任务不用改。

## 4. 硬纪律（违反会被 pre-commit / CI / canary 拦下）

1. **契约变更先写工单**：字段 / locator scheme / `SOURCE_TYPES`·`STATUSES` / 表结构 / 接口签名 / `CONFIG_SCHEMA_KEYS` 的任何改动，先写 `docs/design/变更工单-*.md`；改完跑 `uv run python -m pytest tests/test_canary.py`。
2. **`datalayer/` 是唯一碰 SQLite 的模块**（防腐化红线）：`grep -rn "sqlite3.connect" src/` 只允许命中 `datalayer/db.py`，`INSERT/UPDATE/DELETE` 同理。
3. **能力注册只出现在 `registry/builtins.py`**：handler/task 文件不得自注册（防 import 副作用）。新能力 = 新文件 + builtins 加一行，不改主流程。
4. **格式**：落盘文本统一 UTF-8 无 BOM + LF（`.gitattributes` 锁 `eol=lf`；`*.bat/*.cmd` 例外为 CRLF）。禁止 `Set-Content -Encoding UTF8` 写源码（带 BOM）。
5. **凭证纪律**：配置里只写 `*_env` 变量名，密钥本体不入仓库 / 不入配置 / 不入日志。
6. **过程文件落 `temp/`**（gitignore），结论回写到本文或 `docs/design/`——`temp/` 可随时清空而不丢知识。
7. **测试串行跑**，跑套件时不要并发改仓库（历史两次「假红」的根因）。
8. **判定分级**：FAIL 阻断 / WARN 人工甄别 / SKIP 计退出码——**SKIP 永不伪装成通过**。
9. 运行数据不出项目根：`data/`（DB·正文库·快照）、`exports/`、`config/` 全在 gitignore 内。

## 5. 已踩过的坑（改相关模块前先看）

- **端口与 Host 白名单**：`web/api.py::install_security_middleware` 按 `cfg.general.server_port` 生成白名单。`serve --port 9000` 不会回写 cfg → 换端口访问直接被 `FORBIDDEN_HOST` 拒。桌面壳（`desktop/main.py`）在 `create_app` 前覆盖了 cfg 值，CLI 的 `serve --port` 没有——改端口相关逻辑时两处都要看。
- **写操作三件套**：`X-KnowAtlas-Token` 头 + `application/json` + Host/Origin 命中白名单。serve 未设环境变量时会**自动生成一次性令牌并打印在启动日志**里，重启即失效。
- **`markitdown` 的 Office/PDF 解析依赖必须显式装**（`mammoth`/`openpyxl`/`xlrd`/`python-pptx`/`pdfplumber`），漏装时静默抛 `MissingDependencyException`——已在 `pyproject.toml` 里。
- **`meta` 是浅合并**（`datalayer/db.py::_SOURCE_FIELDS` 注释）：upsert 只用源拥有的字段覆盖，`value_flag`/`link_status`/`dedupe_master`/`freshness_flag` 等后处理键必须保住，否则同步会抹掉人工结论。
- **消费面守卫 `_consumable()`** 同时存在 SQL 片段与 `pipeline/dedupe.py::_is_consumable` 两处口径，改一处必须同步另一处。
- 版本号不一致：`pyproject.toml` 写 `0.2.0`，`src/knowatlas/__init__.py` 仍为 `0.1.0`（`--version` 取后者）；改版本时两处一起改。
- Windows 控制台默认 GBK：CLI 中文输出会显示乱码（数据本身是 UTF-8）；看中文先 `chcp 65001` 并设 `PYTHONIOENCODING=utf-8`。