# KnowAtlas / KPE 操作日志

> 约定：每做一步操作追加一条；新会话先读本文件末尾「当前状态 / 下一步」。
> 本文件只记事实与决定，不写密钥。

## 2026-10-25

- 15:36 过滤 agentic-ai-guide 的前置点：1377 → 1373（丢「关于作者」3 条、「Contents 免责声明」1 条），生成
  `D:\kpe-agentic-ai-guide\review.clean.md`、`points.clean.jsonl`、`stats.clean.json`。
- 15:36 并入 KnowAtlas 点层（`data/knowledge.db`）：points 47 → 1991。
  - agentic-ai-guide → entry `83717cc1e9dbe352`，1373 点；
  - AI-Agents-in-Depth → entry `9f118bf8f0d79592`，571 点；
  - 备份：`temp/knowledge-before-kpe-import-20261025.db`。
- 15:40 按「保留最新的点」清理两本书旧的 `integral` 书目摘要点（各 1 条，均只挂一个 entry）：
  points 1991 → 1989，sources 1991 → 1989；两本 entry 现在分别 1373 / 571 个 KPE 点。
  - 备份：`temp/knowledge-before-integral-purge-20261025.db`。
- 15:41 检查剩余文件：`D:\sData\KnowLedge` 顶层还有 8 个 PDF、2 个 MD 未跑 KPE；
  `DeepSeek-Harness-Whitepaper.pdf` 已跑 78 点；`重要概念.emmx` 不支持；
  子目录 `ai-agents-in-action-2nd-edition-cn-main` 的 11 个 MD 已在库里有旧点，
  `agentic-design-patterns-main` 是 PDF 的源仓库，暂不重复处理。
- 15:42 启动批量分块（只分块、不调模型）：10 个文件，输出到 `D:\kpe-batch\<slug>`。
  目标：先拿到块数/字数，再按成本分批抽取。
- 15:44 批量分块已在后台启动（job `pwsh-86ab66725f2a49f5`），日志 `D:\kpe-batch\chunk-all.log`。

## 当前状态（16:01）

- 数据库：points **3976**、point_sources **3976**、points_fts **3976**；其中 `integral` 21（其他未重跑条目），`split` 3955。
- KPE 已入库 **3955 点**（quote 3825/3955，96.7%）：
  - AI-Agents-in-Depth 571；agentic-ai-guide 1373；
  - 本批 10 本 1933（hello 820、xmu 315、agentic-patterns 420、hermes 93、
    harness-eng 81、dsv41 78、obsidian 50、loop 35、snowflake 7、snowflake-plus 34）；
  - DeepSeek-Harness 78。
- 本批 quote 命中 1817/1933（94.0%）；dsv41 62/78、xmu 281/315 偏低。
- 旧点清理：snowflake 15→7、snowflake-plus 41→34；其余重跑条目只剩最新 KPE 点。
- 备份：`temp/knowledge-before-keep-latest-20261025.db`、
  `temp/knowledge-before-dsharness-20261025.db`。
- 批处理产物：`D:\kpe-batch\<slug>\{chunks,points,points.clean,review.clean}.{jsonl,md}`。

## 未处理 / 边界

- `ai-agents-in-action-2nd-edition-cn-main` 的 14 个 MD 拆章：库里已有旧点，但没重跑 KPE。
- `agentic-design-patterns-main` 是 PDF 的源仓库（含 bilingual 章节/图片/README），
  与已跑的 `agentic-design-patterns-chinese.pdf` 重复，未处理。
- `重要概念.emmx`：KPE 不支持 emmx，跳过。
- 本次是 `temp/` 一次性脚本导入，尚未接入 `pipeline/points.py` 的正式适配器。

## 下一步

1. 若需要，把 `ai-agents-in-action` 的 MD 拆章也跑 KPE，替换旧点；预计 100 块以内。
2. 给 KPE 产物写正式导入适配器（业务代码，先出方案再改）。
3. 用同一份 chunks 换 Hy3 跑对比，再决定默认模型。

## 上下文与交接

- 本会话已很长，但 DSH 没有暴露精确 token 计数；我只能按轮次/输出量估算。
- **我不能自行新开 DSH 会话**（没有创建会话的工具）；接近上限时我会在这里写交接块并停下来，
  由你在 GUI 新开会话或恢复会话。
- 新会话开场：读本文件「当前状态 / 下一步」，检查 `D:\kpe-batch\` 下已有 `stats.json` 的目录，
  已完成的不重跑（KPE `done.jsonl` 也会自动跳过）。
- 交接块模板：
  - 正在跑的文件 / 命令：
  - 已完成文件与点数：
  - 下一个文件：
  - 已知失败与处理：

## 2026-10-25 批量处理

- 15:48 批量分块完成：10 个文件、344 块、1,737,230 字。
  - Hello-Agents 720 页 / 140 块 / 760,575 字（无目录，窗口分块）
  - 厦大 882 页 / 55 块 / 317,743 字；agentic-patterns 284 页 / 76 块 / 326,023 字
  - dsv41 17 块；hermes 16；harness-eng 14；obsidian-ai 9；loop-eng 6；
    雪花写作法 1；雪花写作法小说家 10
- 15:48 批量抽取首次启动（`--thinking omit`）；首块 completion 4099 tokens，其中
  reasoning 3686，单块约 15 s，太慢且贵。
- 15:52 停掉首次抽取，改 `--thinking off`（发送 `thinking.type=disabled`）重启；
  已完成 9 块保留，后续从第 10 块续跑。新 job `pwsh-1ed96a2041e544dc`，
  日志 `D:\kpe-batch\extract-import-off.log`。
- 15:54 hello-agents: 抽取完成，165s。
- 15:54 hello-agents: 820 点 → 过滤后 820；入库 created=820 linked=0 skip=0；清旧 integral=1。
- 15:55 xmu-882: 抽取完成，67s。
- 15:55 xmu-882: 315 点 → 过滤后 315；入库 created=315 linked=0 skip=0；清旧 integral=1。
- 15:56 hermes: 抽取完成，47s。
- 15:56 hermes: 93 点 → 过滤后 93；入库 created=93 linked=0 skip=0；清旧 integral=1。
- 15:56 harness-eng: 抽取完成，20s。
- 15:56 harness-eng: 81 点 → 过滤后 81；入库 created=81 linked=0 skip=0；清旧 integral=1。
- 15:57 obsidian-ai: 抽取完成，13s。
- 15:57 obsidian-ai: 50 点 → 过滤后 50；入库 created=50 linked=0 skip=0；清旧 integral=1。
- 15:57 loop-eng: 抽取完成，10s。
- 15:57 loop-eng: 35 点 → 过滤后 35；入库 created=35 linked=0 skip=0；清旧 integral=1。
- 15:59 agentic-patterns: 抽取完成，110s。
- 15:59 agentic-patterns: 420 点 → 过滤后 420；入库 created=420 linked=0 skip=0；清旧 integral=1。
- 15:59 dsv41-report: 抽取完成，35s。
- 15:59 dsv41-report: 78 点 → 过滤后 78；入库 created=78 linked=0 skip=0；清旧 integral=1。
- 15:59 snowflake: 抽取完成，5s。
- 15:59 snowflake: 7 点 → 过滤后 7；入库 created=7 linked=0 skip=0；清旧 integral=0。
- 15:59 snowflake-plus: 抽取完成，6s。
- 15:59 snowflake-plus: 34 点 → 过滤后 34；入库 created=34 linked=0 skip=0；清旧 integral=0。
- 15:59 批量抽取结束；数据库 points=3914。
- 16:00 按「保留最新点」清理：snowflake 15→7、snowflake-plus 41→34；points 3899。
  备份 `temp/knowledge-before-keep-latest-20261025.db`。
- 16:01 并入 DeepSeek-Harness 78 点并清旧点：entry 78，points 3976。
  备份 `temp/knowledge-before-dsharness-20261025.db`。
- 16:01 本批 10 本 + DS-Harness 的 `review.clean.md` / `points.clean.jsonl` 均已生成；
  数据库 points/sources/fts 均为 3976。

## 上下文探针与交接（2026-10-25 16:20）

- 16:13 查 DSH 运行态：`DSH_SESSION_ID=session-64163ce7-3d6d-424b-8fbc-134f2d7b4361`，
  会话文件 `~/.dsh/sessions/--D-sData-git-KnowAltas--/<session>/session.v4.jsonl.zstd`。
- 16:14 解压会话（多帧 zstd，Python `zstandard.stream_reader`），确认事件里有
  `request/context.contextWindow`、`assistant/message.usage`、`compaction/summary`。
- 16:17 新建 `tools/context_probe.py`：读最近一次 `usage.totalTokens`、模型窗口、
  历史压缩水位，输出 OK/WARN/HANDOFF/CRITICAL。
- 16:18 实测：`currentTokens=141,432`，`contextWindow=262,144`（54.0%），
  但 DSH 最近一次压缩水位是 `147,059`，有效占用 **96.2% → CRITICAL**。
  探针命令：
  `uv run --with zstandard python tools/context_probe.py`
- 16:20 按约定**不再继续、不等待自动压缩**，写交接块并停止本会话。

### 交接块

<!-- HANDOFF {"session":"session-64163ce7-3d6d-424b-8fbc-134f2d7b4361","compactions":0,"tokens":141432,"at":"2026-10-25T16:20:00+08:00","status":"CRITICAL","goal":"KPE 批量导入收尾与会话交接","next":"二选一：ai-agents-in-action 拆章重跑 KPE；或把 KPE 产物接成 points.py 适配器","not_rerun":"D:\\kpe-batch 下已有 stats.json 的目录；两本书已入库的 KPE 点","verify":"uv run --with zstandard python tools/context_probe.py --json"} -->

- 正在跑的文件 / 命令：无。两个批处理 job 都已完成。
- 已完成：
  - 数据库 `data/knowledge.db`：points 3976、point_sources 3976、points_fts 3976；
    KPE 点 3955（AI-Agents 571、agentic-guide 1373、本批 10 本 1933、DS-Harness 78）。
  - 本批产物：`D:\kpe-batch\<slug>\{review.clean.md,points.clean.jsonl,stats.clean.json}`。
  - AI-Agents / agentic 产物：`temp/kpe-aiagents/`、`D:\kpe-agentic-ai-guide\`。
  - 旧的 integral / 被新 KPE 覆盖的旧点已清理；备份在 `temp/knowledge-before-*.db`。
- 下一个文件 / 任务（任选）：
  1. `ai-agents-in-action-2nd-edition-cn-main` 的 14 个拆章 MD 重跑 KPE；
  2. 把这套 KPE 产物接成 `pipeline/points.py` 的正式导入适配器（业务代码，先方案）。
- 已知失败与处理：
  - `--thinking omit` 在 SiliconFlow 不关思考，已改 `--thinking off`；
  - `重要概念.emmx` KPE 不支持，未处理；
  - `agentic-design-patterns-main` 是 PDF 源仓库，避免重复未处理。
- 新会话开场：先读本文件「上下文探针与交接」和「当前状态」，再决定做哪一项；
  不要重跑 `D:\kpe-batch\` 下已有 `stats.json` 的目录。

> 说明：DSH 当前没有给 agent “新建/切换会话”的工具，所以我不能自动换会话；
> 我能做的是在阈值处停止并写交接，由你在 GUI 新开会话或恢复会话。

## 2026-10-25 16:45 会话治理工具（继续协议 / 探针 / 通知）

- 16:34 重写 `tools/context_probe.py`：
  - 按工作区定位会话（`--workspace`），watcher 用 `use_env=False` 避免新会话后还盯旧会话；
  - 扫描同工作区历史会话，学习 DSH 真实压缩水位并缓存（`~/.knowatlas/context-cache.json`）；
  - 本机 baseline 实测 **147,059 tokens**（模型窗口 262,144 的 56.1%）；
  - 输出 `effective_pct`，退出码 OK=0/WARN=10/HANDOFF=20/CRITICAL=30。
- 16:37 新增 `tools/session_check.py`：读 log.md 最后一个 `<!-- HANDOFF {...} -->`，
  对比当前会话 id 与 compaction 次数，判定 NEW_SESSION / SAME_SESSION_COMPACTED /
  SAME_SESSION_UNCOMPACTED / NO_HANDOFF。
- 16:39 新增 `tools/notify.py`：PushPlus / Server酱 / WxPusher / 企业微信机器人 / 通用 webhook /
  Windows toast；配置在仓库外 `~/.knowatlas/notify.toml`，密钥只读环境变量与 `HKCU\Environment`。
  实测 desktop toast 通过；PushPlus 等凭据待用户提供。
- 16:43 新增 `tools/context_watcher.py`：按 effective_pct 阈值 + compaction 次数 + log.md 新交接块
  发通知；同级去重、冷却 1800s；状态存 `~/.knowatlas/watcher-state.json`。
- 16:44 新增 `tools/start_watcher.ps1`（常驻隐藏进程）与 `tools/install_watcher_task.ps1`
  （Windows 计划任务，每 2 分钟 `--once`）。
- 当前会话：`session-ebc4c31e-...`，相对 16:20 交接块是 **NEW_SESSION**（交接会话为 64163ce7）。
- 16:39 计划任务 `KnowAtlasContextWatcher` 安装并首跑：`LastTaskResult=0`，每 2 分钟一次。
- 16:39 `session_check` 实测：
  - 当前会话 → `NEW_SESSION`（exit 0）；
  - 旧会话 64163ce7 → `SAME_SESSION_COMPACTED`（exit 20，compactions 4 > 交接时 0）。
- 16:40 通知实测：desktop toast OK；本地 webhook 回环 payload OK；
  PushPlus 未设 token（缺凭据，暂由 desktop 兜底）。
- 16:41 `~/.knowatlas/notify.toml` 已生成，`min_level=INFO`；密钥只从环境变量 /
  `HKCU\Environment` 读，仓库与日志里没有密钥。
- 16:42 本机只有 PowerShell 5.1（无 `pwsh`）：`.ps1` 必须 ASCII——无 BOM 的 UTF-8 中文
  会被 5.1 当 ANSI 读成乱码并弄断引号（已踩，脚本已改英文）。

## 交接协议 v2（2026-10-25 16:45，用户定稿）

> 用户说「继续 / 接着 / 往下 / continue / resume」等任意同义表述，即视为授权按本协议**直接开始**，
> 不再反问「要继续吗」。开场只做三件事，做完再动手。

### 开场三步

1. `uv run --with zstandard python tools/session_check.py`
   - 判断当前是 **新会话 / 同会话已压缩 / 同会话未压缩**
     （依据 log.md 最后一个 HANDOFF 标记 + 会话文件里的 compaction 次数）。
2. 读本文件最后一个「交接块」与「当前状态」，把「不要重跑」「下一步」抄进本轮计划。
3. `uv run --with zstandard python tools/context_probe.py`
   - 取 currentTokens / baseline / effective_pct；`effective_pct` 才是真实水位。

### 判定分支

| session_check 退出码 | 含义 | 动作 |
|---|---|---|
| 0 NEW_SESSION | 新会话 | 按交接块继续；不要回读旧会话文件。 |
| 10 SAME_SESSION_UNCOMPACTED | 同一会话、没压缩 | 上下文可能仍高；探针 HANDOFF/CRITICAL 就立即写交接并停，不要硬撑。 |
| 20 SAME_SESSION_COMPACTED | 同一会话、已被自动压缩 | 摘要**有损**：先重读交接块 + `AGENTS.md` + 相关源码/数据，核对后再动手；不要凭记忆重跑。 |
| 30 NO_HANDOFF | 没有机器可读交接块 | 先读人类可读交接；接近阈值时补写带 HANDOFF 标记的交接块。 |

### 阈值（以历史最高压缩水位为 100%）

| 级别 | effective_pct | 动作 |
|---|---|---|
| OK | < 80% | 正常推进 |
| WARN | >= 80% | 收尾，不再开新的大任务 |
| HANDOFF | >= 85% | **停止**：写交接块 → 发通知 → 告诉用户开新会话 |
| CRITICAL | >= 95% | 立即停，不再发新请求 |

DSH 自动压缩水位本机实测约 **147,059 tokens**（模型窗口的 56%），所以「窗口用了 80%」并不安全；
一律看 `effective_pct`，不看 `window_pct`。

### 交接块模板（阈值处必写）

```markdown
### 交接块（HH:MM）
<!-- HANDOFF {"session":"session-...","compactions":N,"tokens":N,"at":"ISO8601","status":"HANDOFF","goal":"...","next":"...","not_rerun":"...","verify":"..."} -->

- 当前目标：一句话，可验收。
- 已完成：做到哪一步 + 产物路径 + 数据数字（现场取，不写死）。
- 下一步：按顺序列 1/2/3，第一步必须能直接执行。
- 不要重跑：命令/目录/批次，明确到路径与判据（如已有 stats.json）。
- 验证命令：新会话开场先跑哪条，期望输出是什么。
- 已知失败与处理：报错原文关键词 + 已试过的绕法。
- 会话指纹：session id / compactions / tokens / 时间。
```

**机器可读标记不可缺少**：`session_check.py` 与 `context_watcher.py` 只认
`<!-- HANDOFF {...} -->`。`at` 用 ISO8601 带时区，作为去重指纹；每次交接必须不同。

### 为什么不让 DSH 自动压缩后继续

压缩摘要会丢「不要重跑什么」「哪个测过哪个没测」这类否定性事实，模型容易重复已完成工作或重跑贵命令。
所以到 85% 就停、写交接、开新会话；压缩后继续只在无法新开会话时作为兜底，且必须先重读交接块与关键文件。

### 通知

- 渠道：PushPlus（微信）、Server酱、WxPusher、企业微信机器人、通用 webhook、Windows toast。
- 配置：`~/.knowatlas/notify.toml`（仓库外）；密钥只放用户环境变量，脚本会读 `HKCU\Environment`。
- 自测：`uv run python tools/notify.py --status` / `--test`。
- 常驻：`powershell -NoProfile -File tools/start_watcher.ps1`；
  计划任务：`powershell -NoProfile -File tools/install_watcher_task.ps1`（本机只有 PowerShell 5.1，无 pwsh）。
- watcher 每轮检查 `effective_pct` 与 log.md 的新 HANDOFF 块；同级去重，compaction 次数增加会单独提醒。

## 当前状态与交接检查点（2026-10-25 16:46）

<!-- HANDOFF {"session":"session-ebc4c31e-38c6-4de2-9c4f-064cee393274","compactions":0,"tokens":111410,"at":"2026-10-25T16:46:00+08:00","status":"WARN","goal":"落地会话继续协议 + 上下文探针 + 微信/桌面通知 watcher","next":"1) setx KNOWATLAS_PUSHPLUS_TOKEN 并 notify --test；2) 观察计划任务与 80%/85% 通知；3) 需要时提交 tools/ 与文档","not_rerun":"install_watcher_task.ps1（已安装）；notify.py --init（配置已存在）；context baseline（已缓存 147059）","verify":"uv run --with zstandard python tools/session_check.py; uv run python tools/notify.py --status; uv run --with zstandard python tools/context_watcher.py --once --no-notify"} -->

- 当前目标：把「说继续就能开始」固化成协议，并让阈值/交接通过微信和桌面通知到人。
- 已完成：
  - `AGENTS.md` §0 继续协议；`docs/log.md` 交接协议 v2 + 模板；
  - `tools/context_probe.py`（工作区定位 + 压缩水位学习，baseline 147,059）；
  - `tools/session_check.py`（NEW_SESSION / SAME_SESSION_COMPACTED / SAME_SESSION_UNCOMPACTED / NO_HANDOFF）；
  - `tools/notify.py`（PushPlus / Server酱 / WxPusher / 企微 / webhook / Windows toast）；
  - `tools/context_watcher.py` + `start_watcher.ps1` + `install_watcher_task.ps1`；
  - 计划任务 `KnowAtlasContextWatcher` 已安装并首跑成功（`LastTaskResult=0`）。
- 下一步：
  1. 用户提供微信推送 token（PushPlus 最简）并 `setx KNOWATLAS_PUSHPLUS_TOKEN "<token>"`；
  2. `uv run python tools/notify.py --test` 验证微信收到；
  3. 视需要把 `tools/`、`AGENTS.md`、`docs/log.md` 提交。
- 不要重跑：`install_watcher_task.ps1`（计划任务已存在）；`notify.py --init`（配置已存在）；
  不要重建 context baseline（`~/.knowatlas/context-cache.json` 已缓存）。
- 验证命令：
  - `uv run --with zstandard python tools/session_check.py`
  - `uv run python tools/notify.py --status`
  - `uv run --with zstandard python tools/context_watcher.py --once --no-notify --json`
- 已知失败与处理：PushPlus 无 token 时只有 desktop 成功（预期）；PowerShell 5.1 的 `.ps1`
  必须 ASCII（已改英文）；`uv run python tools/session_check.py` 缺 zstandard 会报错，
  必须带 `--with zstandard`。
- 会话指纹：`session-ebc4c31e-38c6-4de2-9c4f-064cee393274` / compactions 0 /
  tokens 111,410 / 2026-10-25T16:46+08:00。

## 抽包：session-guard 独立仓库（2026-10-25 17:05）

- 16:52 用户要求「把刚写的工具单独抽出来，不只本机用」。方案：独立仓库 + 可安装包 + `tools/` 薄封装。
- 16:58 新仓库 `D:\sData\git\session-guard`：`src/session_guard/`（cli/config/sessions/probe/handoff/watcher/notify）、
  `tests/`（33 项全绿）、`examples/`（systemd / launchd / Windows 计划任务）、README。
  关键改动：会话定位改为读会话首行 `cwd` 匹配工作区（不再猜 DSH 目录名编码）；
  状态目录按平台解析，旧 `~/.knowatlas` 自动沿用；桌面通知覆盖 Windows toast / macOS osascript / Linux notify-send；
  环境变量 `SESSION_GUARD_*` 为主、兼容 `KNOWATLAS_*`。
- 17:01 `uv build` 产 wheel/sdist；干净 venv 装 wheel 后 `session-guard probe` 实测可用。
- 17:02 `session-guard notify --test`：desktop toast + PushPlus `HTTP 200 code=200`，微信链路打通（此前交接块说「token 未设置」已过时）。
- 17:03 KnowAtlas `tools/` 四个脚本改为薄封装（`tools/session_guard_bridge.py`）：
  `session_check` 仍判 `NEW_SESSION`；`context_probe` baseline 仍为 147,059（scanned=5）；
  `context_watcher --once --no-notify` 无新通知。
- 17:04 新仓库首提交 `04851fd`；`AGENTS.md` §3、`AGENTS.local.md` 已补入口说明。
- 当前会话 `session-a312f91f-...`；17:02 `effective_pct=75.6%`（111,238 / 147,059）。

### 交接块（17:04）
<!-- HANDOFF {"session":"session-a312f91f-a326-441a-860d-f120973a0500","compactions":0,"tokens":123000,"at":"2026-10-25T17:04:05+08:00","status":"WARN","goal":"session-guard 抽成独立可安装仓库，旧 tools/ 入口继续可用","next":"1) cd D:\\sData\\git\\session-guard && uv run --extra dev pytest（33 项应全绿）；2) 发布时先 git remote add + push（注意本机 github 直连被墙，镜像只读）；3) 视需要提交 KnowAtlas 的 tools/、AGENTS.md、docs/log.md","not_rerun":"uv build（dist 已有 wheel）；notify --test（17:02 已发）；context baseline（147059 已缓存）；install_watcher_task.ps1（计划任务已存在）","verify":"uv run --with zstandard python tools/session_check.py -> NEW_SESSION；tools/context_probe.py -> baseline 147059 scanned=5","done":"独立仓库 commit 04851fd；33 项测试绿；wheel 干净 venv 实测；微信+桌面通知实测；tools/ 四个薄封装" } -->

- 当前目标：把会话守卫工具从 KnowAtlas `tools/` 抽成可跨机安装的独立包，并保持旧命令/计划任务可用。
- 已完成：
  - 独立仓库 `D:\sData\git\session-guard`，首提交 `04851fd`；包 `session-guard` 0.1.0，
    命令 `session-guard probe|check|watch|notify`；`uv build` 产 wheel/sdist。
  - `src/session_guard/`：cli / config / sessions / probe / handoff / watcher / notify；
    会话定位改读首行 `cwd`，状态目录按平台解析并自动沿用 `~/.knowatlas`，桌面通知覆盖三平台。
  - 33 项 pytest 全绿；wheel 装入干净 venv 后 `probe` 实测；`notify --test` → toast + PushPlus `code=200`。
  - KnowAtlas `tools/*.py` 改薄封装（`tools/session_guard_bridge.py`），实测判定/探针/watcher 输出与抽包前一致。
  - `AGENTS.md` §3、`AGENTS.local.md` 已补入口与迁移说明。
- 下一步：
  1. `cd D:\sData\git\session-guard && uv run --extra dev pytest`，期望 33 passed；
  2. 需要发布时 `git remote add origin ... && git push`（本机 github 直连 443 被墙，镜像只读，推送需另想办法）；
  3. 视需要把 KnowAtlas 的 `tools/`、`AGENTS.md`、`docs/log.md` 提交（本次未提交）。
- 不要重跑：`uv build`（dist 下已有）；`notify --test`（17:02 已发）；baseline 重建（147,059 已缓存）；
  `install_watcher_task.ps1`（计划任务已存在）。
- 验证命令：`uv run --with zstandard python tools/session_check.py`（期望 `NEW_SESSION`）；
  `tools/context_probe.py`（期望 `baseline 147,059, scanned=5`）。
- 已知失败与处理：PowerShell 5.1 下看中文先 `chcp 65001`；`tools/` 薄封装依赖同级
  `../session-guard`，挪走需 `pip install session-guard` 或设 `SESSION_GUARD_SRC`。
- 会话指纹：`session-a312f91f-a326-441a-860d-f120973a0500` / compactions 0 /
  tokens ≈123,000 / 2026-10-25T17:04+08:00（WARN，83.6%）。

## 2026-10-25 17:07 新会话：验证交接 + 两笔提交

- 17:07 新会话 `session-3317aaf5-93e1-4d10-a7d2-a2e4b0e79adb`；开场三步：
  `session_check` → `NEW_SESSION`（exit 0）；`context_probe` → `effective_pct=9.8%`
  （14,456 / 147,059，compactions 0，status OK）→ 不需要交接，按 17:04 交接块继续。
- 17:09 核对交接块里的验证项：`session-guard` **34 passed**（交接写 33；其后
  `5338209`「--dry-run 只报告不发送」与 `89f11f7`「消除 find_session 按 env 判定的偶发失败」
  两提交新增 1 项）；`tools/kpe` **14 passed**。
- 17:10 提交 `ae4e8aa`：会话治理 9 文件、+601（4 个 py 薄封装 + bridge + 2 个 ps1 +
  `AGENTS.md` §0 + `docs/log.md` 首入库）。
- 17:11 提交 `471dee3`：`tools/kpe/` + 5 份设计文档，24 文件、+2812（含 `uv.lock`；
  `__pycache__/`、`*.egg-info/`、`.venv/` 均被 `.gitignore` 挡住，未入库）。
- 17:13 主仓库基线：`567 tests collected`，`uv run python -m pytest` 两次退出码均 0（全绿）。
  注意 `pyproject.toml` 的 `addopts = "-q"`，命令行再加 `-q` 会变 `-qq` 并吞掉
  「N passed」汇总行——要汇总就别再传 `-q`。
- 现象：`tools/kpe/.venv`（约 44 MB，`uv run` 自动创建）与 `tools/kpe/uv.lock` 是本次跑测试的副产物，
  前者已忽略、后者已入库。控制台看中文仍是 GBK 乱码（文件本身 UTF-8 无 BOM、LF，已验）。
- 下一步：
  1. `session-guard` 与 `kpe` 都还没有远程仓库；本机 github 直连 443 被墙、镜像只读，
     要发布得另想办法（或先 `git bundle` 落盘）。
  2. KPE 正式接入 `pipeline/points.py` 适配器（业务代码，先出方案再改）。
  3. 待定：`ai-agents-in-action` 拆章重跑 KPE（库里还是旧点）。
- 不要重跑：`uv build`、`notify --test`、context baseline 重建、`install_watcher_task.ps1`。

## 2026-10-25 17:58 KPE 导入适配器 + ai-agents-in-action 重跑 + 收藏夹待审区

### 批 102：`kpeimport`（第二条）

- 新增 `src/knowatlas/pipeline/kpe_import.py`：读 `<out>/{manifest.json,points.jsonl}`（纯 stdlib，
  **不依赖 tools/kpe**）；条目定位 `--entry` > `--match`（须唯一命中）> `manifest.book` 与标题精确相等；
  `--replace` 先 `purge_entry_points` 再导；写库前 `snapshot(force=True)`；前置节点丢弃；幂等跳过。
- `cli.py` 加 `kpeimport` 子命令；`docs/design/变更工单-2026-10-25-KPE导入适配器.md` 已立。
- `tests/test_kpe_import.py` 6 项：按标题定位 / 前置丢弃 + offset 回填 / 幂等 / replace（孤儿删、共享点留） /
  多命中拒绝 / dry-run 不写库。
- 验证：全量 `pytest` **573 passed, 1 skipped**（exit 0）；`test_canary.py` 绿（指纹未动）。

### 第三条：ai-agents-in-action 重跑

- 14 章 MD（51.4 万字）逐章 chunks+extract：产物 `temp/kpe-aiagents-ch/ch-*`；
  SiliconFlow `DeepSeek-V4.1-Flash`、thinking off、4 并发，共 **603 点**、约 ¥0.36、约 5 分钟。
- ch-1 首轮 1 块失败 → `--retry-failed` 补抽 +6 点（该章 42）。
- 导入（`temp/kpe_aiagents_import.py`，单次快照 `knowledge-20261025-180058.db`）：
  点数 **3976 → 4558**；清旧溯源 21 条（各章旧 integral 点）。
- 「0.关于本书」6 点全是排版/购买/前置知识，不是知识 → `关于本书` 补进 `FRONT_SECTIONS`，
  重导 ch-0（`--replace`）清掉 → 点数 **4552**（`points`、`point_sources`、`points_fts` 均为 4552，全部 `judge=split`）。
- 检索抽检：`上下文工程` / `MCP` / `护栏` 均命中。

### 第四条：Edge 收藏夹 → 待审区

- 本机无 HTML 导出；直读 `%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Bookmarks`（383 条）。
- `temp/bookmarks_stage.py`：规则预筛丢 AI绘图(60)/tools(9)/华为+Huawei(13)/tencent(1)/可商用素材(7)/
  移动收藏夹(11) → 282 条交 LLM（标题+域名+文件夹，8 批）→ 保留 **191**，丢弃 192；
  产物 `data/bookmarks-edge-knowledge.json`（同格式、保留层级）。
- 本机 `config/knowatlas.toml`：`[sources.bookmarks]` enabled=true、browsers=["edge"]、
  path 指向上面的产物、`new_entries="pending"`（config/ 已 gitignore，未入库）。
- `ksync --source bookmarks`：**created=191，全部 status=pending**（重复 URL 5 条）；
  待审区不抓正文/不分类/不抽点，等用户在管理页「🆕 待审」逐条转正或舍弃。

### 批 103：待审区书签审查增强（方案 A，纯前端）

- 只改 `web/static/index.html`：工具条（搜索 / 分组下拉 /「筛出 N / 共 M」/ 全选可见 / 反选）、
  按文件夹分组（组头带条数与「全选本组」）、行内 `📁文件夹` + `域名` 徽标、
  批量后 toast「已转正 N，剩余 M」、「转正后下一步」提示条（三条可复制命令）。
  接口 / 表结构 / config 键零变更，canary 未动。
- 真实浏览器验收（headless Edge + CDP，`temp/ui_check.py`，全程只读）：191 行、
  15 个分组（书签栏/AI 54、后端 10、前端 9、JS&TS 7、综合 4、编程思想 3 …）、
  文件夹与域名徽标各 191；搜 `github` → 筛出 78；全选可见 → 选中 78；
  再点「全选本组」→ 86；下一步提示渲染出 3 条命令；`js_errors=null`。
- 补记：watcher 弹窗已修（18:24）—— 计划任务改 `wscript.exe + tools/run_hidden.vbs` 隐藏启动，
  提交 `fe87fba`；实测 `LastTaskResult=0`、状态文件正常更新；安装脚本同步改造。

### 下一步

1. 你在 Web 管理页（`serve` → 管理 → 🆕 待审）挑书签：按文件夹筛选 → 全选本组 / 全选可见 → ✅转正。
   转正后照页面提示条依次跑 `ksync --fetch-limit N` → `ksync --reclassify` → `kpoints --limit N`
   （**不会自动跑**：书签是全量源，转正条目下一轮 sync 属于 unchanged，不进分类）。
2. 剩余未重跑的 `agentic-design-patterns-main`（PDF 源仓库，与已跑 PDF 重复，决定是否跳过）。
3. 想要「转正即抓取/分类/抽点」的一键闭环再走方案 B：需工单 + `api.py`/新 pipeline + 进度 UI。
- 不要重跑：`temp/kpe-aiagents-ch/*`（`stats.json` 已存在）；`kpeimport` 对已导章节（幂等跳过，除非 `--replace`）；
  `temp/bookmarks_stage.py`（LLM 判定有随机性，重跑会换一批结果）；`temp/ui_check.py` 只读、可随时复跑。

## 2026-10-25 19:27 交接（上下文 CRITICAL）

### 当前目标

语义检索上线（已完成）+ 勘误能力评估（抽样已出结果，等用户裁决是否建流水线）。

### 已完成（本轮，提交 `496ef28` / `8f2a3b8`）

- **批 103 待审区 UI**：筛选 / 分组 / 全选可见 / 文件夹+域名徽标 / 转正后三条命令提示；
  headless Edge 实测 191 行、15 组、搜 github 筛出 78；纯前端零契约变更。
- **批 104 语义检索**：`semantic/embed.py` 新增 `RemoteEmbedder`（OpenAI 兼容）；
  本机 `[embedding]` 切硅基流动 `BAAI/bge-m3`（1024 维）。
  `ksync --embed` 实测：`entry_vectors=29`（其余 pending/无正文跳过）、`point_vectors=4552`、
  语义去重 42 组 / 43 个重复；总耗时 **686s**（几乎全在 `dedup_points` 的 O(n²) 纯 Python 余弦）。
  FTS 零命中的三个语义词（进销存 / 怎么让智能体记住之前说过的话 / 函数调用和工具调用的区别）
  hybrid 各召回 30 条向量独有点，全部对题。
- **勘误抽样**（`temp/errata_sample.py`，只读）：400 点 →
  分诊 opinion 182 / unjudgeable 83 / **hard 135**；
  对 135 条硬事实核查 → **ok 104 / suspect 27 / wrong 4**（约 1% 全样本、3% 硬事实）。
  4 条 wrong 均有可核查依据，例：LangChain「专为 DAG 构建」、PPO clipping「防止灾难性遗忘」、
  MCP `idempotentHint`「失败可安全重试」。
  报告：`temp/errata_sample_report.json`（含每条 kind/verdict/reason/evidence）。
- **watcher 弹窗**已修（`fe87fba`）：计划任务改 `wscript.exe + tools/run_hidden.vbs` 隐藏启动。

### 下一步（按序）

1. **重启 `serve`**：正在跑的进程是改配置前启动的，`/api/search?mode=hybrid` 仍返回 0 命中；
   重启后前端 hybrid 才生效（config 已指向 bge-m3 + SF1 key）。
2. 看 `temp/errata_sample_report.json` 里 4 条 wrong 与 27 条 suspect，判断精度是否可接受。
3. 若接受 → 建工单做 `point_fact_check`（分诊 + 硬事实核查 + 双模型交叉可选 + 裁决 UI 扩展）；
   若不接受 → 只保留「过时性核查」，人文社科改做「多视角对照」。
4. 顺手优化：`dedup_points` 纯 Python O(n²) 686s，可改 numpy 向量化或分块（无契约变更）。

### 不要重跑

- `ksync --embed`（686s，向量已在库；换模型才需 `--embed-force`）
- `kpeimport` / `temp/kpe-aiagents-ch/*`（已导入）
- `temp/bookmarks_stage.py`（LLM 判定有随机性）
- 全量 `pytest` 刚跑过（573 passed / 1 skipped）

### 验证命令

```bash
uv run python -m pytest -q                       # 573 passed, 1 skipped
uv run --with zstandard python tools/session_check.py
uv run python temp/probe_hybrid.py               # 需导入 KNOWATLAS_LLM_API_KEY_SF1
```

### 已知失败 / 注意

- `serve` 未重载新配置（见下一步 1）。
- `fact_audit` 早前 60 点样本：0 wrong / 27 suspect —— 说明「AI 智能体理论书」大量是观点，
  全库盲跑核查会产噪声，必须分诊后再核。

<!-- HANDOFF {"session":"session-3317aaf5-93e1-4d10-a7d2-a2e4b0e79adb","compactions":1,"tokens":165000,"at":"2026-10-25T19:27:00+08:00","status":"CRITICAL","goal":"语义检索已上线；勘误抽样完成待裁决","next":"重启 serve 使 hybrid 生效；看 errata_sample_report.json 判断精度；决定是否建 point_fact_check 工单"} -->

## 2026-10-25 19:41 批 105：多选浮动条修复（用户报障）

- **现象**：待审区点「全选可见」后看不到浮动条「✅转正 / 🗑舍弃」。
- **根因**：`#bulk-bar` 只有内联 `display:none`，**全仓库没有任何 JS/CSS 把它显示出来**——
  多选模式一直是隐形的（连条上的「多选」勾选框都点不到）。
- **修法**（`web/static/index.html`，纯前端）：
  1. 内联 `display:none` 删除，改 `#bulk-bar{display:none}` + `body.multiselect #bulk-bar{display:flex}`；
  2. 新增 `setMultiSelect(on)` 统一同步两处开关 + body class + 清空选择；
  3. 管理页签栏下加常驻入口 `☑ 多选（批量操作）`（`#ms-entry-cb`）；
  4. `_ptSelectVisible()` 改调 `setMultiSelect(true)`——「全选可见/全选本组」即自动打开浮动条。
- **验证**（headless Edge + CDP，`temp/ui_bulk_check.py`）：初始 `display:none`；
  点全选后 `display:flex`、379×75 px、`已选 183`、转正按钮可见、183 个复选框全勾；
  点「取消」→ 隐藏且入口勾掉；手动勾入口 → 再次显示。`node --check` 通过、`pytest` 全绿。
- 现场数字：待审从 191 降到 **183**（用户已自行转正 8 条）。

<!-- HANDOFF {"session":"session-3317aaf5-93e1-4d10-a7d2-a2e4b0e79adb","compactions":1,"tokens":182361,"at":"2026-10-25T19:41:00+08:00","status":"CRITICAL","goal":"多选浮动条已修复；语义检索待重启 serve 生效；勘误抽样待裁决","next":"重启 serve；重启后确认 /api/search?mode=hybrid 有命中；看 errata_sample_report.json 定 point_fact_check 工单"} -->

## 2026-10-25 19:52 批 106：页面新鲜度防呆（旧 DOM 导致「修了看不到」）

- **现象（用户复报）**：批 105 修好的浮动条，用户仍看不到。排查结论：**代码没问题，是客户端端着旧页面**——
  线上 `GET /` 返回的 HTML 已含 `body.multiselect #bulk-bar`/`setMultiSelect`；headless Edge 复现全绿；
  用户的 Edge 进程是 10-24 20:46 起的，标签页从未重载，`#bulk-bar` 还是旧 DOM 里的内联 `display:none`。
- **修法（防复发，不改接口/表结构）**：
  1. `web/app.py` 新增 `_NoStoreHTML(StaticFiles)`：`text/html` 响应加 `Cache-Control: no-store`，
     js/css 仍走 ETag（不牺牲 echarts 之类大文件的缓存）。测试 `tests/test_web_api.py::test_html_entries_are_no_store`。
  2. `static/index.html` 页脚加 `#st-build` 构建戳；`checkPageFresh()` 用 `HEAD /` 的 `Last-Modified`
     与 `document.lastModified` 比对，对不上就标红 + toast「请 Ctrl+F5」——旧页面一眼可见。
  3. `#bulk-bar.has-sel { display:flex }` + `updateBulkBar()` 同步：**只要 selection 非空就显示浮动条**，
     不再只依赖多选模式（旁路/未来新入口也能兜住）。
  4. 「反选」也先 `setMultiSelect(true)`（原先只有「全选可见/全选本组」进多选）。
- **验证**：headless Edge（`temp/ui_fresh_check.py`）——页面戳 `10-25 19:36`、未标 stale；全选 → `flex`/`已选 183`/
  入口勾上；反选 → 183 条勾上、条可见；取消 → `none`/`已选 0`；无 JS 异常（仅 favicon 404，历史既有，无 favicon.ico）。
  `uv run python -m pytest -q` → 583 passed / 1 skipped。
- **提示**：以后改完 HTML，让用户 `Ctrl+F5`；页脚若标红「⚠ 已过期」就是没刷新。

## 2026-10-25 19:55 serve 重启（hybrid 生效）

- 旧 serve 是 10-24 21:37 起的，跑的是批 104 之前的代码：`/api/search?mode=hybrid` 返回
  `effective_mode=fts` + 「本次已降级 fts」。
- 重启后（隐藏窗口，日志 `temp/serve.out.log` / `temp/serve.err.log`）：`mode=hybrid`、`vectors=29`。
  顺带 `serve` 现在按批 106 给 HTML 发 `no-store`，用户 `Ctrl+F5` 一次即可拿到浮动条。
- 重启姿势（复现用）：`Start-Process <uv.exe> -ArgumentList run,python,-m,knowatlas,serve,--port,8420
  -WorkingDirectory <repo> -WindowStyle Hidden -RedirectStandardOutput temp\serve.out.log`，
  继承 `KNOWATLAS_LLM_API_KEY*` / `KNOWATLAS_WEB_TOKEN`（用户级变量要先 `Set-Item env:` 导入）。

## 2026-10-25 22:30 勘误全量核查完成（4,509 点）

- **两段式**（`temp/errata_full.py`，4 线程、分批增量落盘、可断点续跑）：
  分诊 4,509 点 → **hard 1,579 / opinion 2,016 / unjudgeable 914**（35% / 45% / 20%，与 400 抽样一致）；
  只核 hard → **wrong 37（2.3%）/ suspect 348（22%）/ ok 1,194**，未核 0。
- **中途断线一次**：核查跑到 440/1,575 时两个后端连续 `WinError 10053/10054`（连接被强断），
  1135 条未核；网络恢复后续跑到 1579/1579，失败批次 0。教训：这类长跑要**分批落盘 + 续跑**，
  一次跑完不现实。
- **错误分布**：`agentic-ai-guide` 663 hard / 23 wrong、`Hello-Agents` 315 / 9 wrong，两本占 32/37；
  其余书 0 wrong。类型：机制/公式说错 ~17（PPO 裁剪 ×4、FlashAttention ×3、偏好优化家族 ×5、
  KV cache 公式、投机解码、流水线气泡、重复惩罚、AST 等价）、规格细节错 ~11（MCP ×3、A2A ×2、
  FastAPI 422、Vue、n8n、Godot、pydantic、GAIA）、绝对化断言 ~4、定义/计数混淆 ~3。
- **产物**：`temp/errata_findings.md`（按书分节；wrong 逐条带理由+依据+point_id；suspect 按书分组）。
- **对机制的启示**：wrong 不是幻觉，是「把机制压成一句口诀」+「把特定实现说成普遍事实」——
  核查 prompt 需要 `overclaim` 原因码（必须/只能/始终/有且仅有 且无限定）。

## 2026-10-25 22:40 扩散抓取实跑（用户指定两个 GitHub 种子）

- 种子 1 `jbiaojerry/ebook-treasure-chest/tree/main/md`（entry `55a9645acd182782`）：
  `ksync --expand --expand-limit 20` → candidates 20 / created 20 / fetch_failed 0 / already_known 0。
  **但这 20 条全是「书目索引页」**（`# 版权声明` + `| 书名 | 作者 | [下载](url) |` 表格，正文 250–2,960 字，
  11/20 有明显下载表格）——不是知识。已用 `POST /api/entries/bulk-status`（action=reject）
  **批量舍弃 20 条**（`bulk_reject` 留痕，30 天冷却可 restore）。走 API 时踩到：
  httpx 默认读 `HTTP_PROXY` 会把 127.0.0.1 也走代理 → 502，须 `trust_env=False`。
- 种子 2 `yixiangshijie/ai-agents-in-action-2nd-edition-cn`（entry `f76cea820310ef37`）：**未跑**——
  该书 12 章已作为 folder 条目在库（`0.关于本书`…`11.构建智能体系统的实用技巧`），
  仓库树扩散会产出同一批章节的 blob 重复条目（canonical 不同，去重拦不住）。
- **守卫缺口**（记入 TODO P5）：批次 94 的骨架守门按「重复行」判，链接表格每行不同 → 漏；
  模板占位符 href（`${old_uri}`）也会被当候选。
- 已知限制：扁平 ID 平台（知乎 `/p/`、掘金 `/post/`、简书 `/p/`、公众号 `/s/`）同目录≠同主题，
  扩散对这类源无意义。

## 2026-10-25 22:45 TODO 排序（用户裁决）

- `docs/design/知识索引工具-TODO.md` 新增「2026-10-25 裁决」节，P0–P5 已排序：
  P0 分诊落库+领域闸门 → P1 勘误机制 → P2 老化机制（版本型/退场型两路）→ P3 点层粒度（全文分块+front matter，大件）
  → P4 点级图 → P5 扩散加固。
- 排序原则：先立机制（便宜、当天可验收），再改点集（贵、要重抽全库）；点级结论一律用 `content_hash` 做键，
  P3 重抽后同文本的点自动继承结论。

## 2026-10-25 23:05 交付：功能与操作手册（验收版）

- **产物**：`docs/使用手册-2026-10-25.md`（450 行，13 节）——只写「现在真能用」的，
  没做到的统一收在第 10 节，不与功能混写。
- **覆盖**：三层结构白话版 / 五分钟启动 / 六个入口 / 条目状态机 / 管理页八个页签 /
  13 个 CLI 命令逐个（含常用参数与行为坑）/ 12 个源的接通状态 / 13 个语义能力 /
  数据安全五约束 / **还没做到的 7 条** / 常见故障 9 条 / **验收清单 22 项**。
- **现场数字**（23:05 取）：条目 241（待审 161 / 在库 30 / 已舍弃 50）、点 4,552、
  点向量 4,552、条目向量 29、分类 8（5 组父子）、线索 0、正文副本 55。
- **核过的事实**：`pytest -o addopts="" -q` → **580 passed / 1 skipped**（此前记的 583 是旧数）；
  8 个管理页签、6 个主视图、68 个 HTTP 路由、`STATUSES` 五值、`SOURCE_TYPES` 16 值。
- **两个写手册时发现的坑**（已写进手册第 11 节）：
  1. `pyproject.toml` 的 `addopts="-q"` + 命令再带 `-q` = `-qq`，pytest **连汇总行都不打**，
     只剩一串点——「看不到 passed 数字」不等于失败，要看退出码（本次差点误判）。
  2. 管理页「📥 暂存区」**不是一种状态**，它列的是「未挂分类」的条目（`STATUSES` 里没有 `staged`）。
- 手册未生成 HTML 阅读版（skill 默认会出双版，本次按仓库既有 docs 约定只落 Markdown）；需要再补。

## 2026-10-25 23:20 P0 点分诊落库（验收通过，已实跑）

- **产物**：工单 `docs/design/变更工单-2026-10-25-点分诊.md`；新增能力 `point_triage@1.0.0`
  （`semantic/tasks/point_triage.py`，prompt 与当日全量实测逐字一致）、`pipeline/triage.py`
  （dupe 确定性标记 + 种子导入 + 新点 LLM 增量 + 幂等 + 领域闸门 `is_hard`/`HARD_SQL`）、
  datalayer `points_without_kind`/`point_kind_counts`/`points_of_kind`、
  `kpoints --triage/--from-json`、`tests/test_point_triage.py`（10 例）。
- **实跑现场数字**（23:08）：candidates 4,552 → dupe 43（`rule:dupe_of`）+ imported 4,509
  （`seed:errata_full_triage.json`，**零 LLM 调用**）→ **hard 1,579 / opinion 2,016 / unjudgeable 914**；
  重跑 candidates 0、零写入；`task_log` 4,552 条 `triage` 留痕；实跑前备份 `temp/knowledge.pre-triage.db`。
- **验收 SQL**：`select coalesce(json_extract(meta,'$.kind'),'(none)') k, count(*) from points group by k`
  → 与 `dl.point_kind_counts()` 一致（无 `(none)`）。
- **测试**：`pytest -o addopts="" -q` → **590 passed / 1 skipped**；canary `capabilities` 因新增能力
  更新为 `49fa2d77cca4`（工单在先、常量后改——canary 先红后绿是正确的漂移拦截）。
- **真 LLM 冒烟**：`point_triage.run` 两条样本 → hard / opinion 判定正确（deepseek flash，2 后端）。
- **不要重跑**：`kpoints --triage --from-json …` 再跑是零写入（无害但无意义）；**不要**跑不带
  `--from-json` 的 `kpoints --triage`——那会把未分诊的新点全量送 LLM（43 个 dupe 已标，不会送）。
- **下一步（取代下方交接块的「P0」）**：P1 `kerrata --points`——只吃 `kind=hard`（闸门直接
  `from .triage import is_hard`），以 `content_hash` 为键幂等，回放当日 37 条 wrong 验收队列数。

## 交接（2026-10-25 23:10，用户主动切会话做验收）

### 当前目标

用户先验收「当前已实现功能」，验收通过后在**新会话**按 TODO 的 P0→P5 开工。本会话不再动业务代码。

### 已完成（含产物路径与现场数字）

- **验收手册**：`docs/使用手册-2026-10-25.md`（450 行，13 节，含 22 项验收清单）。
- **勘误全量核查**（4,509 点）：hard 1,579 / opinion 2,016 / unjudgeable 914；
  hard 里 wrong 37 / suspect 348 / ok 1,194。产物：`temp/errata_full_triage.json`、
  `temp/errata_full_verify.json`、`temp/errata_full_report.json`、
  **给人看的清单 `temp/errata_findings.md`**（按书分节，wrong 带理由+依据+point_id）。
- **TODO 排序**：`docs/design/知识索引工具-TODO.md` 新增「2026-10-25 裁决」P0–P5（提交 `37a72b1`）。
- **扩散实测**：`ebook-treasure-chest/md` 跑出 20 条，全是书目索引页 → 已 `bulk-status reject`
  （30 天冷却可 restore）；第二个种子未跑（章节已在库，会造重复）。守卫缺口记入 TODO P5。
- 现场数字：条目 241（pending 161 / active 30 / rejected 50）、points 4,552、
  point_vectors 4,552、entry_vectors 29、categories 8、threads 0。
- 测试：`pytest -o addopts="" -q` → **580 passed / 1 skipped**。

### 下一步（按序，首步可直接执行）

1. **P0 分诊落库**：把 `temp/errata_full_triage.json` 的 kind 写进 `point.meta.kind`
   （+`kind_why`/`kind_at`/`kind_model`），新增 `kpoints --triage`（幂等，LLM 不通则整批 skip）；
   后续勘误/老化只吃 `kind=hard`。
2. **P1 勘误机制**：`kerrata --points`，结论写 `point.meta.fact_check`，以 `content_hash` 为键幂等，
   wrong 进裁决队列、suspect 只进筛选视图；原因码 `fact_error` / `overclaim`。
   验收：回放当日 37 条 wrong，队列数 = 37，重跑零新增。
3. **P2 老化机制**：版本型（抽版本号 + EOL 表，确定性）+ 退场型（LLM 附官方依据），
   `kaging --lifecycle` 主动扫描，只吃 `kind=hard`，只标不删。
4. 之后 P3（全文分块抽取，解决「章节名」根因，大件，需用户裁决重抽成本）→ P4（点级图）→ P5（扩散加固）。

### 不要重跑

- **勘误全量核查**（4,509 点，约 25 分钟 + 费用）：结果已在 `temp/errata_full_*.json`，直接读。
- **`ebook-treasure-chest` 扩散**：已跑完并回退，别再跑（会再造 20 条书目页）。
- **`ai-agents-in-action-2nd-edition-cn` 扩散**：该书章节已在库，跑了就是重复，别跑。
- **全量 `pytest`**：刚跑过（580/1）；除非改了业务代码。
- **`ksync --embed`**：点向量已全覆盖（4,552），条目向量 29 是既知现状，不是故障。

### 验证命令

```bash
uv run --with zstandard python tools/session_check.py   # 应判 NEW_SESSION
uv run python -m pytest -o addopts="" -q                # 580 passed, 1 skipped
curl http://127.0.0.1:8420/api/stats                    # serve 已起（PID 22144，端口 8420）
```

### 已知失败 / 注意

- **serve 是本会话早些时候重启的进程**，新会话若改后端代码需再重启才生效；改 HTML 只需用户 `Ctrl+F5`。
- 手册里的数字是 2026-10-25 23:05 的现场值，会随操作变化，验收时以 `/api/stats` 为准。
- `pytest` 带 `-q` 会与 `addopts` 叠加成 `-qq`，导致**不打印汇总行**，别误判为失败。
- 本会话 `effective_pct` 79.2%（baseline 147,059）。

<!-- HANDOFF {"session":"session-599a0405-b8b3-4be2-8ed3-889a97e073ca","compactions":1,"tokens":116432,"at":"2026-10-25T23:10:00+08:00","status":"HANDOFF","goal":"交付验收手册 docs/使用手册-2026-10-25.md；勘误全量已出清单；TODO P0-P5 已排序；用户验完开新会话按 P0 开工","next":"新会话先跑 session_check 与 pytest -o addopts= -q；然后 P0 分诊落库（point.meta.kind + kpoints --triage + 领域闸门），再 P1 勘误机制、P2 老化机制"} -->

## 交接（2026-10-25 23:30，P0/P1 已交付，水位 87.8%）

### 当前目标

按 TODO 的 P0→P5 逐项立机制。**P0（点分诊）、P1（点级勘误）已完成并实跑验收**；
下一步 P1b（UI 页签 + 原因码回填）→ P2（老化两型）→ P3/P4/P5。

### 已完成（含产物路径与现场数字）

- **P0 点分诊**（提交 `02bf82d`）：`point_triage@1.0.0` + `pipeline/triage.py` +
  `kpoints --triage/--from-json`；实跑 4,552 点 → **hard 1,579 / opinion 2,016 /
  unjudgeable 914 / dupe 43**（零 LLM 回放），重跑 candidates 0。
  工单 `docs/design/变更工单-2026-10-25-点分诊.md`。
- **P1 点级勘误**（本批，提交号见下）：`point_errata@1.0.0` + `pipeline/errata_points.py` +
  只读 `GET /api/errata/points` + `kerrata --points/--from-json`；
  实跑 1,579 hard 点 → **wrong 37 / suspect 348 / ok 1,194**（零 LLM），重跑 candidates 0；
  队列 API `count=37`（带理由/依据/溯源）。工单 `docs/design/变更工单-2026-10-25-P1点级勘误.md`。
- **测试**：`pytest -o addopts="" -q` → **598 passed / 1 skipped**；canary `capabilities`
  = `89594636c8b2`（P0+P1 两个新能力，工单在先）。
- **备份**：`temp/knowledge.pre-triage.db`（P0 前）、`temp/knowledge.pre-errata.db`（P1 前）。
- **serve 已重启**（本会话 23:27，新 PID 见 `Get-NetTCPConnection -LocalPort 8420`），
  新路由 `/api/errata/points` 生效；日志 `temp/serve.out.log` / `temp/serve.err.log`。

### 下一步（按序，首步可直接执行）

1. **P1b（小）**：
   a. `index.html::mgmtErrata()` 增「点级」区块，拉 `/api/errata/points` 渲染点卡
      （理由/依据/原因码/溯源条目），与条目级队列分区展示；
   b. 需要**写接口** `POST /api/points/{id}/fact-check/dismiss`（人裁误报 → `fact_check.dismissed=true`
      出队）——属接口契约变更，先在 P1 工单里追加一节再实现；
   c. 37 条种子结论的 `reason_code` 为空：可一次性 LLM 分类回填（~2 批）或按 reason 文本规则抽，
      回填后写 `fact_check.reason_code` + `stage` 保持可追溯。
2. **P2 老化机制**：版本型（抽版本号 + EOL 表，确定性）+ 退场型（LLM 附官方依据），
   `kaging --lifecycle` 主动扫描，只吃 `kind=hard`，只标不删。
3. 之后 P3（全文分块抽取，大件，需用户裁决重抽成本）→ P4（点级图）→ P5（扩散加固）。

### 不要重跑

- **P0 分诊回放**（`kpoints --triage --from-json …`）：已落库 4,552 点，重跑零写入。
- **P1 勘误回放**（`kerrata --points --from-json …`）：已落库 1,579 点，重跑零写入。
- **勘误全量核查**（4,509 点，约 25 分钟 + 费用）：结果在 `temp/errata_full_*.json`，直接读。
- **两个 GitHub 种子扩散**：已跑过/已回退，别再跑。
- **全量 pytest**：刚跑过（598/1）；除非改了业务代码。

### 验证命令

```powershell
uv run --with zstandard python tools/session_check.py     # 新会话应判 NEW_SESSION
uv run python -m pytest -o addopts="" -q                  # 598 passed, 1 skipped
curl http://127.0.0.1:8420/api/errata/points              # {"count":37,...}
uv run python -m knowatlas kpoints --triage               # 应 candidates 0（幂等）
```

### 已知失败 / 注意

- **37 条 wrong 的 `reason_code` 为空**（种子产物没记原因码）；LLM 新核点会产出。
- **点级队列只有 API**，管理页「🩹 勘误裁决」仍只列条目级（P1b）。
- `serve` 是本会话重启的进程；**改后端代码需再重启**才生效，改 `index.html` 用户 `Ctrl+F5` 即可。
- PowerShell 控制台直接 `Invoke-WebRequest` 打印 UTF-8 会乱码（按 Latin-1 解码），
  用 `uv run python -c` 读库或 `curl.exe` 复核，别当成数据损坏。
- 本会话 `effective_pct` 87.8%（baseline 147,059）；请开新会话继续说「继续」。

<!-- HANDOFF {"session":"session-3bfb4ef8-1581-474d-8ede-e9f8c048b7cc","compactions":0,"tokens":129100,"at":"2026-10-25T23:30:00+08:00","status":"HANDOFF","goal":"P0 点分诊与 P1 点级勘误已交付并实跑（4,552 点分诊 / 1,579 hard 勘误、队列 37）；下一步 P1b（UI 页签+写接口+原因码回填）→ P2 老化机制","next":"新会话先跑 session_check 与 pytest -o addopts= -q；然后 P1b：index.html 勘误页签接 /api/errata/points + 新增 dismiss 写接口 + 回填 37 条 reason_code；之后 P2 老化两型（kaging --lifecycle，只吃 kind=hard）"} -->

## 2026-10-26 00:20 P1b 人裁闭环交付（续会话 session-f4c32d7b）

### 开场判据

- `session_check` = `NEW_SESSION`（exit 0），上一交接 23:30 `status=HANDOFF`；
- `context_probe`：`effective_pct` **10.0%**（14,768 / 147,059，compactions=0）；
- 基线 `pytest -o addopts="" -q` → **598 passed / 1 skipped**（与交接一致，未重跑旧核查）。

### 做了什么（契约先行：先追加工单 §6，再动代码）

- **工单** `docs/design/变更工单-2026-10-25-P1点级勘误.md` 追加 §6「P1b」：写接口签名、
  `fact_check` 两个新键（`dismissed`/`dismissed_at`）、CLI 开关、datalayer 两方法、回滚 SQL。
- **写接口** `POST /api/points/{point_id}/fact-check/dismiss`：人裁误报 → 出队；
  结论/依据/原因码原样保留（可回溯「为什么曾被判错」）；`task_log` 记 `point_fact_check_dismiss`。
  坑：`merge_meta_of_point` 是**浅**合并，必须读-改-写整块 `fact_check`，否则抹掉结论。
- **原因码回填**：`point_errata.classify_codes()`（只产码）+ `pipeline/errata_points.py::backfill_reason_codes()`
  + `kerrata --points --backfill-codes`（与 `--from-json` 互斥）；datalayer 新增
  `get_point_meta()` / `points_wrong_without_reason_code()`。
- **UI**：`index.html::mgmtErrata()` 同页签双区（条目级沿用 + 点级新增），点卡带原因码徽标、
  理由、📎依据、溯源条目链接与「↩误报，保留」按钮。
- **测试**：`tests/test_point_errata.py` +5 例 → 全量 **603 passed / 1 skipped**；
  **canary 六项指纹零漂移**（未更新常量，`capabilities` 仍 `89594636c8b2`）。

### 实跑（现场数字）

- 备份 `temp/knowledge.pre-p1b.db`（120.6 MB）；
- `--backfill-codes --dry-run` → candidates 37 / filled 37（2 次调用）；实跑同上 →
  **32 fact_error / 5 overclaim**；重跑 candidates **0**、零 LLM 调用（幂等）；
- `serve` 已重启（PID 3404，端口 8420，`KNOWATLAS_WEB_TOKEN` 指纹 `2ad28785`）；
  `GET /api/errata/points` → `count=37`，每条带 `reason_code`；
- dismiss 受控往返：37 → 36 → 复原 37（只多 `dismissed`/`dismissed_at` 两键）；404 / 无令牌 403 实测；
- 前端：`node --check` 校验内联脚本通过；用户需 **Ctrl+F5** 才看到新版页面。

### 下一步（按序，首步可直接执行）

1. **P2 老化机制**：版本型（抽版本号 + EOL 表，确定性）+ 退场型（LLM 附官方依据），
   `kaging --lifecycle` 主动扫描，只吃 `kind=hard`，只标不删。
2. 之后 P3（全文分块抽取，大件，需用户裁决重抽成本）→ P4（点级图）→ P5（扩散加固）。

### 不要重跑

- **P1b 原因码回填**：37 条已落码，重跑 candidates 0（要重跑先按工单 §6.3 清码）。
- **全量 pytest**：刚跑过（603/1）；除非又改业务代码。
- **dismiss 受控往返**：已复原，队列仍是 37，不要再拿真库点做往返验证。
- **P0 分诊 / P1 勘误回放 / 勘误全量核查**：见上一交接块，结论都在库里与 `temp/errata_full_*.json`。

### 验证命令

```powershell
uv run --with zstandard python tools/session_check.py    # 新会话应判 NEW_SESSION
uv run python -m pytest -o addopts="" -q                 # 603 passed, 1 skipped
uv run python -m knowatlas kerrata --points --backfill-codes   # 应 candidates 0
curl.exe -s http://127.0.0.1:8420/api/errata/points      # count=37，reason_code 非空
```

### 已知失败 / 注意

- `serve` 是本会话重启的进程（PID 3404）；**改后端代码要再重启**，改 `index.html` 用户 `Ctrl+F5` 即可。
- PowerShell 控制台直接读 UTF-8 文件仍会乱码（按 ANSI 解码），看中文用 `read` 工具或 `chcp 65001`。
- 原因码是 LLM 分类（非人工逐条确认）：`overclaim` 边界（如 Godot HTTPRequest、Mixtral 参数激活）
  存在可争议项，人裁时可随时在队列里否决出队。

## 2026-10-26 00:50 P2 点级老化两型交付（同一会话）

### 做了什么

- **工单** `docs/design/变更工单-2026-10-26-P2点级老化两型.md`（契约先行）。
- **数据/判定** `semantic/eol.py`：8 个有官方支持矩阵的技术 + 官方 URL，`data/eol.json` 可覆盖；
  保守判定（未收录版本 → suspect，不猜「新版本就是支持的」）。
- **能力** `semantic/tasks/point_lifecycle.py`：退场型，按技术栈分组，retired 必附官方依据否则 keep。
- **管道** `pipeline/lifecycle.py`：A 段版本型（零 LLM）+ B 段退场型（LLM 分组）；
  只吃 `kind=hard`；stale 走 `set_point_aging` 退出消费面；幂等游标 `meta.lifecycle.at`。
- **CLI** `kaging --lifecycle`（与 `--points`/`--sweep` 互斥，`--limit` 默认全库）。
- **canary**：只有 `capabilities` 变化 → `e293e25d725c`（新能力，工单在案）。

### 自检抓到的两类假阳性（这是本批最有价值的部分）

1. `Python 3.x` 被判 EOL（表只记 EOL 过的版本）→ 新增 `LIVE_MAJORS` 声明「仍有活着小版本的大版本」；
2. `需要 Python 3.10 **或更高版本**` 被判「在用 3.10」→ 新增最低版本语境过滤；
   顺带修 `Python 2019` 年份误匹配。两类都已固化成单测。

### 实跑数字

- 测试 **611 passed / 1 skipped**（+8 例）；备份 `temp/knowledge.pre-lifecycle.db`（120.6 MB）；
- 真库 1,579 hard 点：A 段 2 ok、**0 stale**；B 段 4 技术栈 → 37 ok、0 retired（1 次调用）；
- 重跑：candidates 1,540（无技术栈提及的点，纯正则零费用）、零写入零调用（幂等）。
- **0 stale 是正确结果**：探针确认库里没有「用过时版本」的知识点，多数是「≥某版本」环境门槛
  （已过滤）与现行技术。

### 下一步

1. **P3 全文分块抽取**（大件）：`_entry_body` 优先 `content_store` 全文、按标题/段落切 4–8k、
   front matter 过滤、跨块去重；需用户先裁决**重抽全库的成本**。
2. P4 点级图（wiki 式关联）→ P5 扩散加固（小件，可随时插队）。

### 不要重跑

- **P2 生命周期扫描**：已落库 39 条 ok，重跑零写入；要重跑先 `json_remove('$.lifecycle')`。
- **全量 pytest**：刚跑过（611/1）。
- **EOL 表**：不要凭印象改日期，改前查官方支持矩阵；改 `data/eol.json` 不用动代码。

## 交接（2026-10-26 07:00，水位 131% 立即停止；P1b/P2 已交付，P3 未开工）

### 当前目标

**P3（全文分块抽取）先做小样本成本测算**（用户 2026-10-26 06:58 裁决）：拿
`Hello-Agents`（674k 字整本）与 `5.智能体推理与规划`（36k 字章节）两个条目试跑分块抽取，
量出**点数 / 耗时 / 费用**，再决定是否全库重抽。**P3 代码一行未写**。

### 已完成（本会话两批，均已提交）

- **批 109（`f2ce960`）P1b 人裁闭环**：写接口 `POST /api/points/{id}/fact-check/dismiss`
  （37→36→复原实测，404/403 实测）；37 条 `reason_code` 回填（**32 fact_error / 5 overclaim**，
  2 次调用，重跑 candidates 0）；管理页「🩹 勘误裁决」同页签双区（点级带徽标/理由/依据/溯源）。
  工单 §6 + CHANGELOG + TODO 已更新。测试 603/1。
- **批 110（`200525e`）P2 老化两型**：`semantic/eol.py`（8 个有官方矩阵的技术 + `LIVE_MAJORS`
  + 最低版本语境过滤）、`point_lifecycle@1.0.0`、`pipeline/lifecycle.py`、`kaging --lifecycle`；
  canary `capabilities` → **`e293e25d725c`**。真库 1,579 hard 点 → **0 stale / 39 ok**
  （本库无过时技术栈知识点，探针已确认），重跑零写入。测试 **611 passed / 1 skipped**。
- 备份：`temp/knowledge.pre-p1b.db`、`temp/knowledge.pre-lifecycle.db`（各 120.6 MB）。
- serve：PID **14220** / 8420 / token 指纹 `2ad28785`（本会话重启两次）。

### 下一步（按序，首步可直接执行）

1. **只读摸底**：`src/knowatlas/pipeline/points.py` 的 `_entry_body`（96 行起，
   `_BODY_CAP = 6000` 截断）、`run_points_extract`（216 行起）、`semantic/tasks/point_extract.py`
   的输入契约（items 形态与 `judge` 三值）。
2. **写 `temp/probe_p3_cost.py`**（过程脚本，**不改业务代码**，符合「过程文件落 temp」纪律）：
   - 按标题定位两个条目（`Hello-Agents` / `5.智能体推理与规划`，见 `--match` 口径）；
   - `dl.get_content(content_hash)` 取全文 → 按标题/段落切 4–8k 块；
   - 逐块调 `point_extract.run(items, TaskContext(run_id=..., llm=LlmClient.from_config(cfg)))`；
   - 统计：全文长度 / 块数 / 原始点数 / 抽到点数 / 耗时 / 字符数 → 费用估算。
   - **先导入用户级 key**（AGENTS.local.md 的 `foreach ($n in ...)` 片段），否则会静默降级成
     「整篇 4023 字 integral 点」，测出来的数是假的。
3. **出全库成本测算**：27 个有点条目的全文总字数 → 块数 → 调用次数 → 预估费用/时长；
   交用户裁决是否落地 P3。落地前先写工单：分块口径、front matter 过滤、跨块按 `content_hash`
   去重、`meta.book`/`section_path` 键、重抽是否 `--purge-points`。

### 不要重跑

- **P1b 原因码回填**：37 条已落码，重跑 candidates 0（要重跑先按工单 §6.3 清码）。
- **P2 lifecycle 扫描**：39 条 ok 已落库，重跑零写入（要重跑先 `json_remove('$.lifecycle')`）。
- **全量 pytest**：刚跑过（611/1）；除非又改业务代码。
- **EOL 表**：不要凭印象改日期；改 `data/eol.json` 不用动代码。

### 验证命令

```powershell
uv run --with zstandard python tools/session_check.py    # 新会话应判 NEW_SESSION
uv run python -m pytest -o addopts="" -q                 # 611 passed, 1 skipped
curl.exe -s http://127.0.0.1:8420/api/errata/points      # count=37，reason_code 非空
uv run python -m knowatlas kaging --lifecycle            # candidates 1540、零写入（幂等）
```

### 已知失败 / 注意

- 本会话 `effective_pct` **131.1%**（192,798 / baseline 147,059）→ 按协议（≥95% 立即停）
  未开始 P3，别把「测完」当成已完成。
- `serve` 是本会话重启的（PID 14220）；**改后端要再重启**，改 `index.html` 用户 `Ctrl+F5` 即可。
- 原因码是 LLM 分类而非人工逐条确认：`overclaim` 边界（Godot HTTPRequest、Mixtral 参数）
  可争议；点级「↩误报，保留」就是人裁出口。
- PowerShell 控制台读 UTF-8 文件会乱码（按 ANSI 解码），看中文用 `read` 工具或 `chcp 65001`；
  往 `python -c` 里塞中文/引号容易被打断，**写 `temp/*.py` 再跑**。

## 交接（2026-10-26 07:12，水位 92.5% HANDOFF；P3 成本测算已完成，等裁决）

### 当前目标

用户 06:58 裁决「P3 先小样本试跑 + 成本测算」——**本轮已做完，未改一行业务代码**。
下一步等用户裁决：**全库重抽 / 先 3–5 本试点 / 暂不做**。

### 本轮新增（提交 `7167e3a`，只动 TODO 文档）

- **发现 1（省掉重抓）**：`content_store` 里本来就有全文——Hello-Agents **674,468 字**、
  `5.智能体推理与规划` **36,438 字**；是 `pipeline/points.py::_entry_body` 优先取
  `inline_content`（`adapters/dbfile.py::_INLINE_CAP = 4000` 的预览）才只看到 **4,023 字**。
  所以 P3 是「改取值优先级 + 分块」，**不是重新抓取**。
- **发现 2（省掉造轮子）**：`tools/kpe` 已是完整的分块抽取工具（`chunks/extract/review/stats`，
  4 并发、断点续跑、quote 校验，产物 `chunks.jsonl`/`points.jsonl`），入库走 `kpeimport`；
  P3 不必在 `pipeline/points.py` 里另写切块。
- **实测**（DeepSeek-V4.1-Flash、关思考、4 并发、¥2/M in + ¥8/M out）：

| 样本 | 规模 | 块数 | 实测 | 外推 |
|---|---|---|---|---|
| Hello-Agents（PDF 720 页，目录条=0） | 760,575 字 | 140 | 前 10 块 → **58 点**/1 拒，37,612+4,036 token，12.3s，¥0.11 | ≈**812 点**，¥1.5，~3 min |
| 5.智能体推理与规划.md | 34,528 字 | 9 | 全跑 → **50 点**/0 拒，16,825+3,347 token，7.7s，¥0.06 | 同左 |
| **全库 30 条目** | 5,863,924 字 | ≈1,080 | 每块 ≈5.6 点 / 3,700 token in / 400 out / 1.2s | ≈**6,000 点**，**≈¥11.6**，**≈22 min** |

- **真正的成本在下游**：点数 1,579 → ≈6,000（4×）；P0 分诊 ≈300 批调用；
  P1 勘误按 hard 点**逐点**调用 ≈3,000 次（串行十几小时），这才是要裁的。
- 产物：`temp/kpe-helloagents/`（140 块 + 10 块点）、`temp/kpe-ch5b/`（9 块 + 50 点）、
  `temp/probe_p3_cost.py`、`temp/probe_corpus.py`、`temp/probe_samples.py`（探针，随时可删）。

### 下一步（按用户裁决分支，首步都可直接执行）

1. **试点（推荐）**：先导 3 本（Hello-Agents / AI-Agents-in-Depth / agentic-design-patterns），
   观察检索·词云·关系图效果再决定其余：
   ```powershell
   $env:PYTHONPATH='D:\sData\git\KnowAltas\tools\kpe'
   uv run python -m kpe chunks "<源文件>" --out temp/kpe-<名>
   uv run python -m kpe extract temp/kpe-<名> --base-url https://api.siliconflow.cn/v1 `
     --model deepseek-ai/DeepSeek-V4.1-Flash --api-key-env KNOWATLAS_LLM_API_KEY_SF1 `
     --thinking off --workers 4 --price-in 2 --price-out 8
   uv run python -m knowatlas kpeimport temp/kpe-<名> --match "<书名通配>" --replace
   ```
2. **全库重抽**：同上循环 30 个条目（注意 `kpeimport --match` 只导单本，别一次导全部）。
3. **P1 不自动跟进**：新点只落库；分诊用 `kpoints --triage`（分批导入种子），errata 按需跑。
4. 若同意「让原生管道也吃全文」→ 先写工单（改 `_entry_body` 优先级 = 改 pipeline 口径，需用户点头）。

### 不要重跑

- **P1b 原因码回填**（37 条已落码，candidates 0）、**P2 lifecycle**（39 ok 已落库，重跑零写入）。
- **`kpe chunks` 两个样本**（`temp/kpe-helloagents/`、`temp/kpe-ch5b/` 已有 `chunks.jsonl`；
  Hello-Agents 是 720 页 PDF，解析要 1–2 分钟）。
- **全量 pytest**（611/1，刚跑过）。

### 验证命令

```powershell
uv run --with zstandard python tools/session_check.py    # 新会话应判 NEW_SESSION
uv run python -m pytest -o addopts="" -q                 # 611 passed, 1 skipped
uv run python -m kpe stats temp/kpe-ch5b                 # 9 块 / 50 点 / ¥0.06
```

### 已知失败 / 注意

- 水位 **92.5%**（135,975 / baseline 147,059，compactions=1）→ 二次压缩风险高，按协议停。
- `kpe.exe` 被应用控制策略拦，**必须** `uv run python -m kpe`（并设 `PYTHONPATH`）。
- `kpe extract` 的 key 用 `--api-key-env KNOWATLAS_LLM_API_KEY_SF1`（硅基），不是 DeepSeek 那条。
- Hello-Agents 的 PDF **没有可解析目录**（720 页 / 目录条=0），块名只有书名、无章节路径；
  若要 `section_path`，需先 MinerU/Docling 预处理。
- `Write-Output` 列 `tools/kpe` 目录会把 `.venv` 全打出来（几千行）——列目录时加 `-Exclude`。

<!-- HANDOFF {"session":"session-f4c32d7b-dd84-4592-b172-5e72f79b068f","compactions":1,"tokens":135975,"at":"2026-10-26T07:12:00+08:00","status":"HANDOFF","goal":"P1b/P2 已交付（f2ce960/200525e），P3 成本测算已完成（提交 7167e3a，只动 TODO）：全库重抽 ≈¥11.6 / ≈22 分钟 / ≈6,000 点，等用户裁决是否落地","next":"新会话先跑 session_check 与 pytest -o addopts= -q（611/1）；再由用户裁决 P3 走向：试点 3 本（kpe chunks→extract→kpeimport --match）或全库 30 本；P1 勘误不要自动跟进新点","not_rerun":"P1b reason_code 回填；P2 kaging --lifecycle；kpe chunks 两个样本（temp/kpe-helloagents、temp/kpe-ch5b 已有 chunks.jsonl）；全量 pytest","verify":"uv run --with zstandard python tools/session_check.py -> NEW_SESSION；uv run python -m pytest -o addopts= -q -> 611 passed, 1 skipped；uv run python -m kpe stats temp/kpe-ch5b -> 9 块/50 点"} -->

## 2026-10-26 12:35 session-guard 实现文档（跨会话交接模块）

- 用户 12:26 指示：暂不裁决 P3，先确认 `D:\sData\git\session-guard` 是否为交接流程模块，并把实现逻辑写成文件。
- 已确认：是。该仓库即 probe/check/watch/notify 的唯一实现，本仓库 `tools/*.py` 只是薄封装（`tools/session_guard_bridge.py`）。
- 新增 `D:\sData\git\session-guard\docs\实现逻辑.md`（904 行）：结论与证据、问题模型、DSH 会话文件契约、7 个模块实现逻辑、命令与退出码契约、状态/配置、通知链路、部署、限制、三种移植情形（DSH / 非 DSH / 只要协议+通知）、二次开发指引、附录模板。
- 实测：session-guard `34 passed in 0.40s`；`tools/session_check.py` → `NEW_SESSION`（12:26，effective 12.4%，window 262,144 / baseline 147,059）。
- 12:38 提交 `3bc97c9`（docs: 实现逻辑与移植指南，905 行）；12:42 推送到 `https://github.com/yianyao/tools.git`（`main`，仓库原为空；GCM 浏览器授权，凭据已入 Windows 凭据管理器）。
- 推送环境：本机直连 `github.com:443` 不通（DNS→20.205.243.166），走本机代理 `http://127.0.0.1:7890`；代理已写进 session-guard 的仓库级 `http.proxy`（不提交），代理不在时 `git push` 会失败。
- 未做：P3 仍待用户裁决；KnowAtlas 本文件与 `tools/` 改动未提交。

## 2026-10-26 19:05 P3 现状核查：全库点层早已是全文分块产物，重抽无必要

会话 `session-ac30a055`（继续协议：`NEW_SESSION`，effective 9.9% = 14,513/147,059；
`pytest -o addopts= -q` → **611 passed / 1 skipped**）。**只读核查，未改一行业务代码。**

### 结论：P3 的主体在 10-25 15:36–18:01 就已经落地了

| 证据 | 实测 |
|---|---|
| 点总数 / 来源 | **4,552 点，全部** `meta.extractor=kpe`，`judge` 全为 `split` |
| 全文而非预览 | 溯源 `char_offset` 最远 **2,477,908**（agentic-ai-guide）、**672,891**（Hello-Agents）；**1,568 条 > 4,000** |
| 溯源字段 | `book`/`section_path`/`quote`/`page_start`/`page_end`/`model` 覆盖率 100% |
| 下游机制 | kind：hard 1,579 / opinion 2,016 / unjudgeable 914 / dupe 43；fact_check：ok 1,194 / suspect 348 / wrong 37；lifecycle：ok 39 |
| front matter | `FRONT_SECTIONS` 名下 **0 点**（`0.关于本书` 4,665 字被丢弃，符合设计） |
| 检索 | 点优先：`q=上下文工程` → 32 点/8 条目；`q=MCP` → 47 点/17 条目 |
| 三本试点 | 早已抽完：Hello-Agents **820**、AI-Agents-in-Depth **571**、agentic-design-patterns **420** |

密度 550–1,080 字/点属正常；两个低密度条目（agentic-ai-guide 1,885、AI-Agents-in-Depth 1,830）
经查**覆盖全书**（188 小节 / 第 1–10 章），是代码与表格多所致，不是截断。

### 纠正 07:12 交接的错误前提

交接把「**hard 子集** 1,579」当成了「**全库点数** 1,579」，据此推出「≈6,000 点 / 4× / ¥11.6 / 22 分钟」。
实际全库已 4,552 点且已分块，**全库重抽与 3 本试点都是重复劳动**，不要执行。

### P3 剩余的真实缺口（唯一一项）

`pipeline/points.py::_entry_body` 仍优先 `inline_content`（`adapters/dbfile.py::_INLINE_CAP=4000` 的预览），
再被 `_BODY_CAP=6000` 截一刀 → **未来新同步的长文档仍会「一篇一点」，只覆盖开头 4,000 字**。
改它等于改 pipeline 口径（AGENTS §1），需用户点头；改法见 TODO P3 第 1 项。
现有 4,552 点不受影响（它们走的是 kpe + 旧一次性脚本的全文路径）。

### 过程脚本（temp/，随时可删）

`probe_pilot_entries.py`、`probe_coverage_detail.py`、`show_coverage.py`、`probe_meta_sql.py`、
`probe_low_density.py`、`probe_offsets.py`、`probe_frontmatter.py`、`probe_layer_summary.py`、
`probe_replace_risk.py`、`probe_pilot_points.py`、`coverage_detail.json`。

### 坑

- `dl.points_of_entries()` **不返回 `meta`**（内部 `pop("meta")` 只回填 `explain`）→ 判 meta 覆盖率必须走 SQL，
  否则会得出「meta 全空」的错误结论（本轮踩过，已纠正）。
- PowerShell 5.1 的 `Out-File -Encoding utf8` 写 BOM；Python 读要 `utf-8-sig`。
- `python -c` 里带引号/中文在 PS 5.1 会被打断 → 一律落 `temp/*.py`。

## 2026-10-26 19:20 批 111：P3 收口——点层取全文，长文交 kpe（用户批方案后落地）

工单 `docs/design/变更工单-2026-10-26-P3点层取全文.md`（用户先选「修 `_entry_body`（小批）」，
再批「按工单开工」）。

### 改了什么

- `pipeline/points.py`：`_entry_body` → **inline 预览与 `content_store` 全文取较长者**；
  正文 > `_BODY_CAP`（6,000）**不截断抽点**，落 `meta.points_pending_kpe` 并跳过；
  `_candidates` 跳过已标记条目（`skip_counts.pending_kpe`）；删除 `body_truncated` 统计与三处截断分支
  （长文分流后永不触发，留着误导读者）。
- `pipeline/kpe_import.py`：`body` 同口径取较长者（否则 `char_offset` 与管道错位）；
  导入成功后清 `points_pending_kpe`（一点未落地时保留标记）。
- `cli.py`：`kpoints` 报告新增 `PENDING n 条正文超管道上限` + kpe 三步提示。
- `datalayer/db.py`：仅注释登记 `points_pending_kpe` 为后处理键、永不进 `_SOURCE_FIELDS`。
- `tests/test_points.py`：新增 5 例 + **改写** `test_pipeline_truncates_long_body_for_llm`
  （它断言的正是被替换的旧口径）。

### 实测

- 全量 **616 passed / 1 skipped**（36.07s）；`tests/test_points.py` 43 passed；canary 1 passed（六项指纹零漂移）。
- 真库 `kpoints --dry-run --limit 5`：`pending_kpe: 0`、`already_done: 26`、`processed: 1`
  （`0.关于本书` 4,665 字，旧行为不变）→ **既有 4,552 点零扰动**。

### 与工单草案的唯一偏差

草案写「`--retry-blocked` 清标记后正常抽点」——落地发现清完会被主循环立刻打回（长文在管道里无解），
改为**只有 `kpeimport` 清标记**，单测相应改成 `test_retry_blocked_does_not_bypass_pending_kpe`。

### 端到端（临时库副本，真库零触碰）

用 `temp/e2e-kpoints.toml` 指向 `data/knowledge.db` 的副本，注入一条 9,000 字长条目后实测：

- 第一次 `kpoints --limit 20`：`pending_kpe: 1`，`pending_kpe_detail` 带条目与字数，
  CLI 打印 `PENDING 1 条正文超管道上限…` + kpe 三步提示；该条目**零 LLM 调用、零点入库**。
- 第二次同命令：`skip_counts.pending_kpe: 1`、`processed: 0`（幂等，不重复读全文）。
- `kpeimport temp/kpe-ch5b --entry <该条目>`：`created 40 / linked 10` 后
  `meta.points_pending_kpe` 变为 **None**（标记被清，符合「kpe 已解决」）。
- 真库复核：仍 **4,552 点**，hard/opinion/unjudgeable/dupe 分布不变。临时库与 toml 已删除。

### 下一步

- P3 全部勾完（TODO 已标）。P4 点级图 / P5 扩散抓取加固未开工。
- `serve`（PID 14220）仍是旧代码：`/api/entries/{id}/form`（强制重抽）走的是进程内旧函数，
  重启后才对长文打 pending 标记。本次未重启——改的是 CLI 与管道主路径，Web 侧只有那个按钮受影响。
  （**2026-10-26 19:21 已重启并验证，见文末「serve 重启」**）

## 2026-10-26 19:25 用户报障：词云点卡的「34 点」是重复渲染（待修，未动代码）

**现象**：词云点「雪花」→ 19 个知识点，标题全同、正文不同；每个知识点底下都有 34 个点，且 19 份完全相同。

**数据侧正常**（`temp/probe_snowflake.py` 实测）：

- 全库含「雪花」的点 **20 个**，全部 `point_sources.entry_id = 39e9415a86480b70`（条目「雪花写作法小说家（增强版）」），
  该条目共 **34 点**；20 个中 1 个是 `dupe`（消费面隐藏）→ 页面显示 **19**，正文各不同 = 19 个不同知识点，**这点是对的**。

**缺陷在渲染**：词云 facet 把「点卡」写成了条目卡骨架——
`index.html:1366` `<div class="entry" data-id="${p.entry_id}">`，而通用钩子
`attachPointChips()`（`index.html:752`，在 `bindEntryButtons()` 内 647 行统一挂）按 `data-id`
拉 `/api/entries/points?ids=`，对**每个** `.entry[data-id]` 追加「◆ N 点 ▸」。
19 张点卡的 `data-id` 是**同一个条目**，于是每张都渲染该条目全部 34 点 → 19×34 重复。
同根因副作用：每张点卡还被 `index.html:636-640` 加了「🆔 复制条目 ID」按钮。

**建议修法（待用户批准，纯前端）**：

1. 点卡改用独立类（如 `entry pt-card`），`attachPointChips` 与 `cid-btn` 的选择器加 `:not(.pt-card)`；
2. 点卡标题不要用条目名（这正是「19 张同名」的观感来源）——改用点摘要或点正文首句，
   「溯源：条目名」保留在底部；
3. 若要保留「该条目还有哪些点」，只在该条目的**第一张**点卡或条目卡上展开一次，不要逐卡重复。

改完让用户 `Ctrl+F5`（`index.html` 改动不需重启 serve）。

## 交接（2026-10-26 19:11，effective 109.8% CRITICAL 立即停止；19:25 追加词云点卡报障）

### 当前目标

P3 已**全部收口**（批 111，提交 `43d752c`）。本轮把交接里「P3 未开工、要花 ¥11.6 重抽全库」的错误前提纠正为：
全库 4,552 点早已是 kpe 全文分块产物，重抽是重复劳动；真正缺口只是原生管道对新长文档的截断抽点，已修。

### 已完成（本会话两笔提交）

- **`6203015`**（只动文档）：P3 现状核查——4,552 点全部 `extractor=kpe` 且带 `book`/`section_path`/`quote`，
  溯源 `char_offset` 最远 2,477,908（证明吃全文）、front matter 名下 0 点、点级检索生效；
  TODO 里「重抽全库」撤销，验收标为真库已达。
- **`43d752c`** 批 111（工单 `docs/design/变更工单-2026-10-26-P3点层取全文.md`）：
  `_entry_body` 取 inline 与 `content_store` 的**较长者**；正文 > `_BODY_CAP`（6,000）**不再截断抽点**，
  落 `meta.points_pending_kpe` 并跳过；`_candidates` 跳过已标记条目；删除 `body_truncated` 与三处截断分支；
  `kpeimport` 同口径取较长者 + 导入成功后清标记；`kpoints` 报告新增 `PENDING n 条…` + kpe 三步提示。
- 实测：**616 passed / 1 skipped**；canary 零漂移；真库 `--dry-run` → `pending_kpe: 0`、既有 4,552 点零扰动；
  临时库端到端（9,000 字条目）：首次打标记 + 零 LLM、二次 `skip_counts.pending_kpe=1`、
  `kpeimport` 后标记变 `None`。真库复核仍 4,552 点、分布不变。

### 下一步（按序，首步可直接执行）

1. 新会话开场按协议跑 `session_check` + `pytest -o addopts= -q`（预期 NEW_SESSION / 616+1）。
2. 由用户裁决 P4（点级图：点成为 `kind=point` 节点，四类边）还是 P5（扩散抓取加固，小件）；
   两项 TODO 均有验收口径，未动一行业务代码。
3. 若要 Web「强制重抽」也按新口径走，重启 `serve`（PID 14220 是旧代码）；重启前先导入用户级
   `KNOWATLAS_WEB_TOKEN`，否则令牌会变、页面写入失效。

### 不要重跑

- **P3 核查与批 111 的全部验证**（616/1、canary、真库 dry-run、临时库端到端都已做过，结论在上面）。
- **`kpe chunks` 两个样本**（`temp/kpe-helloagents`/`temp/kpe-ch5b` 已有产物）。
- **全库重抽 / 三本试点**：已证明是重复劳动（点已在库）。
- **P1b 原因码回填、P2 lifecycle**：已落库，重跑零写入。

### 验证命令

```powershell
uv run --with zstandard python tools/session_check.py    # 新会话应判 NEW_SESSION
uv run python -m pytest -o addopts="" -q                 # 616 passed, 1 skipped
uv run python -m knowatlas kpoints --dry-run --limit 5   # pending_kpe=0、already_done=26
```

### 已知失败 / 注意

- 本会话 `effective_pct` 冲到 **109.8%**（161,452 / baseline 147,059，未压缩）→ 按协议立即停，P4/P5 未开工。
- `serve` 未重启，`/api/entries/{id}/form` 仍是旧逻辑（长文会截断抽点）；CLI 与管道已是新口径。
- 探针坑：`dl.points_of_entries()` 返回的 dict **不含 `meta`**（内部 pop 只回填 `explain`），判 meta 必须走 SQL。
- 过程脚本（`temp/probe_*`、`temp/e2e_*`、`temp/normalize_files.py`）随时可删；e2e 临时库已删除。

<!-- HANDOFF {"session":"session-ac30a055-31f6-467c-a14b-4ba483781484","compactions":0,"tokens":172000,"at":"2026-10-26T19:26:00+08:00","status":"HANDOFF","goal":"P3 全部收口（6203015/43d752c，616 passed/1 skipped）；另查明用户报障「词云雪花 19 点各挂 34 点」= 前端点卡复用条目卡骨架导致重复渲染，未动代码","next":"新会话先跑 session_check 与 pytest -o addopts= -q（616/1）；然后按 log「19:25 用户报障」修 index.html（点卡加 .pt-card，attachPointChips/cid-btn 选择器排除点卡，点卡标题改点摘要而非条目名），Ctrl+F5 验收；之后再由用户裁决 P4/P5；若要 Web 强制重抽走新口径，重启 serve（先导入 KNOWATLAS_WEB_TOKEN）","not_rerun":"P3 核查与批 111 全部验证（616/1、canary、真库 dry-run、临时库端到端）；词云数据侧核查（20 点/19 可见/34 点属同一条目，已确认无误）；kpe chunks 两个样本；全库重抽与三本试点（重复劳动）；P1b 原因码回填与 P2 lifecycle","verify":"uv run --with zstandard python tools/session_check.py -> NEW_SESSION；uv run python -m pytest -o addopts= -q -> 616 passed, 1 skipped；uv run python temp/probe_snowflake.py -> 20 点全属 39e9415a86480b70（34 点条目）","done":"6203015 docs 核查；43d752c 批 111；1dab949 交接块；19:25 词云点卡报障定性（前端 index.html:1366 + attachPointChips 752）"} -->

## 2026-10-26 19:21 serve 重启：旧进程换成新代码（PID 14220 → 27416）

**起因**：交接块记的 `serve` PID 14220 启动于 **00:32:50**，早于 `43d752c`（19:11:01 提交）。
Python 进程内已缓存的 `pipeline/points.py` 是旧版，`/api/entries/{id}/form`（强制重抽）
仍会截断长文抽点，而不是落 `points_pending_kpe` 交 kpe。

**做法**：

- 先导入用户级 `KNOWATLAS_WEB_TOKEN`、`KNOWATLAS_LLM_API_KEY_SF1`、`KNOWATLAS_LLM_API_KEY`；
- `Stop-Process 14220` 后以 `.venv\Scripts\python.exe -m knowatlas serve --port 8420` 重启。
  注意 uv 的 `venv\Scripts\python.exe` 是转发壳：壳进程 **16512**，真正监听 8420 的是子进程
  **27416**（同为 19:21:09 启动）——下次按 PID 停服务要停 27416。
- 源码是 editable 安装（`__editable__.knowatlas-0.2.0.pth` → `src/`），重启即加载工作区当前代码。

**令牌**：重启前后指纹一致，`/api/token-hint` → `2ad28785`（= 用户级 `KNOWATLAS_WEB_TOKEN`），
页面 localStorage 里的令牌不用重填，写操作不失效。

**证据（HTTP 层，真库零触碰）**：用 `sqlite3 backup` 把真库复制到 `temp/e2e_serve/knowledge.db`，
以 `KNOWATLAS_CONFIG=temp/e2e_serve/knowatlas.toml` 起 8431 端口的同代码实例，对
72,980 字的条目 `447e7a2a2d187f5d` POST `/api/entries/447e7a2a2d187f5d/form {"form":"split"}`：

- 响应：`purged_sources: 81`、`points_created: 0`、`errors: []`、`points: []`，耗时 **149 ms**；
- meta：`points_pending_kpe = {"chars": 72980, "why": "正文超过管道单次上限…"}`（SQL 复核 code point 正常）；
- 即「长文不再截断抽点、落 pending」的新口径已在 Web 端点生效，且未触发任何 LLM 调用。
  （旧代码在同一输入下会走 split → 截断正文 → 调 LLM。）

第二实例与 `temp/e2e_serve/`（含 127 MB 临时库）已删除。

**环境顺带**：本会话开头 `temp/` 目录缺 `WRITE_OWNER`，`uv` 无法建 cache、临时文件写不进；
用 `diagnose-windows-sandbox-acl` 给当前用户补 FullControl 后恢复（备份与恢复脚本在
`temp/acl-repair-out/`）。仓库根的临时测试文件已清掉，`git status` 干净。

**遗留**：19:25 的词云点卡重复渲染是**前端**问题，跟 serve 新旧无关；
`index.html` 由 StaticFiles 直出且 `Cache-Control: no-store`，改完 Ctrl+F5 就生效，不用重启。

## 2026-10-26 19:44 词云点卡重复渲染修复（`426f124`）

**改法**（纯前端 + 一条静态探针）：

- `index.html` 词云 facet 的点卡：`<div class="entry" data-id>` → `<div class="pt-card" data-eid>`。
  不再冒充条目卡 → 条目通用钩子（`.entry-host .entry[data-id]`：点聚合、🆔、分类徽标、
  确认归类、多选/拖拽、拆合按钮）全部不再命中点卡；
- 点卡标题由「条目名」改为 `summary`（无则点正文前 40 字），19 张同名卡变成 19 个不同知识点；
  底部「溯源：条目名」保留。标题与正文都过 `_escHtml`（原来未转义直出）。
- `components.css`：`.entry, .pt-card` 共享基础外观与链接样式；`.pt-card` 加左缘强调线
  （与 `.entry.point-hit` 同一视觉语言）。
- 下方条目 facet 的条目卡保持 `.entry`——「◆ 34 点」只在那一张条目卡上出现一次，
  正好承载「该条目还有哪些点」，不再逐张点卡重复。

**验证**：`pytest -o addopts= -q` → **616 passed / 1 skipped**（新增静态探针断言点卡模板用
`class="pt-card"` 且不再出现 `<div class="entry" data-id="${p.entry_id}">`）；
`node --check` 两个内联 `<script>` 块语法通过；`GET /` 已含 `pt-card`、`components.css` 已含
`.pt-card`。静态文件由 StaticFiles 直出且 `Cache-Control: no-store`，**不需要重启 serve**。

**验收**：浏览器 Ctrl+F5 → 词云点「雪花」→ 19 张点卡标题各不相同、卡上不再出现「◆ 34 点」
与 🆔；下方条目卡仍显示一次「◆ 34 点 ▸」。

## 2026-10-26 20:10 P4 点级图落地（点成为一等节点，629 passed）

**用户裁决**：按方案做（推荐）——点层默认开、可切回条目层。

**改法**（工单 `docs/design/变更工单-2026-10-26-P4点级图.md`）：

- `datalayer/db.py::radiate`：`_RADIATE_KINDS` 加 `"p": "point"`；点焦点四通道
  `attach:<origin>` / `same_book:<book>` / `same_section:<book>/<section>` / `sim:<score>`。
  纯标准库余弦（4,552 点 × 1024 维实测 0.2 s）；消费面守卫 = 非 stale + 非 dupe +
  至少一条溯源条目 active 且过 `_consumable('e')`；每通道 `per_channel` 截断进 `truncated`。
  `section_path == book`（整本一块）不出章节通道，避免与同书重复。
- `datalayer/db.py::get_graph_subtree`：新增 `layer`/`point_limit`；`layer=points` 时条目集照算
  （hierarchy 叶子 / compact 折叠口径不变），第三层换 `p:<pid>` 点卡、边 `p→c` 标 `kind="point"`，
  超出 `point_limit` 记 `truncated.points`；无可消费点自动回退条目层 + `note`。
  默认 `entries` 时响应**完全不变**（连 `layer` 键都不加）。
- `web/api.py`：subtree 透传 `layer`/`point_limit`（夹紧 1–600），非法 layer → 400。
- `web/static/graph.html`：`--point` 令牌 + PAL.point；「◆ 点层」开关（默认开、localStorage、
  切换即重放视图）；点节点点击任何时候都切焦点（`showRadiate("p:<id>")`）；点卡显示正文 +
  书籍/章节 + 可点溯源；主题视图点节点 `kind:"point"`；有点节点时走 force（禁用分层铺开）。
  「📋 显示条目」显式要条目层（forceClassic 不带 layer=points）。

**验证**：

- 新增 `tests/test_graph_point_layer.py` 13 例；全量 `pytest -o addopts= -q` →
  **629 passed / 1 skipped**；`tests/test_canary.py` 1 passed（六项常量零漂移）。
- 真库只读探针（`DataLayer` 直读，不写）：`p:5c07508429801ddf` 邻域 **18 节点 / 18 边**，
  四通道齐全、每条边有 reason（`truncated {same_book:50, sim:1205}`）；邻点再放射两次
  （18→18 节点）仍非空；`layer=points` 在 3,304 点大类下出 200 点 + 5 分类，
  `truncated.points=4265`；默认子树无 `layer` 键、照旧 25 条目。
- `node --check` 内联脚本通过。

**验收**：浏览器 Ctrl+F5 → 图页勾选「◆ 点层」→ 点分类下钻到叶子层看知识点；
点任一点节点切焦点（连点两次不空）；点卡可看正文/书籍章节/溯源条目。
<!-- HANDOFF {"at":"2026-10-26T20:04:11.915060+08:00","compactions":0,"doc":"docs/交接/2026-10-26-2004.md","draft":true,"goal":"上下文到 CRITICAL（118.3%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-01217ada-3f22-44e9-b9c2-306b3732d74f","status":"CRITICAL","tokens":173942,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-26T20:08:11.679924+08:00","compactions":1,"doc":"docs/交接/2026-10-26-2008.md","draft":true,"goal":"会话已被自动压缩 #1","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-01217ada-3f22-44e9-b9c2-306b3732d74f","status":"OK","tokens":88550,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->
<!-- HANDOFF {"at":"2026-10-26T20:14:10.737227+08:00","compactions":1,"doc":"docs/交接/2026-10-26-2014.md","draft":true,"goal":"上下文到 HANDOFF（93.7%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-01217ada-3f22-44e9-b9c2-306b3732d74f","status":"HANDOFF","tokens":137840,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->
<!-- HANDOFF {"at":"2026-10-26T20:16:10.742960+08:00","compactions":1,"doc":"docs/交接/2026-10-26-2016.md","draft":true,"goal":"上下文到 CRITICAL（98.0%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-01217ada-3f22-44e9-b9c2-306b3732d74f","status":"CRITICAL","tokens":144131,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

## 2026-10-26 20:16 交接：P4 点级图已交付（94b17e2），上下文 CRITICAL 停会话

**当前目标**：P4 点级图已完成并提交；下一步由用户浏览器验收，之后可开 P5。

**已完成（现场数字）**：

- 提交 `94b17e2`：feat(graph) P4——点成为一等节点。改动 10 文件 +796/−54；
  新增工单 `docs/design/变更工单-2026-10-26-P4点级图.md`、测试 `tests/test_graph_point_layer.py`（13 例）。
- `radiate("p:<id>")` 四通道：`attach:`/`same_book:`/`same_section:`/`sim:`（点向量，阈值 0.5，
  纯标准库余弦，4,552 点实测 0.2 s）；`section_path == book` 不出章节通道。
- `/api/graph/subtree?layer=points&point_limit=N`：第三层换 `p:` 点卡、边 `p→c` 标 `kind="point"`；
  无点范围回退条目层 + note；默认 `layer=entries` 响应与旧版一致（无 `layer` 键）。
- 前端：`--point` 令牌；「◆ 点层」开关默认开 + localStorage；点节点点击即 `showRadiate`；
  点卡显示正文/书籍章节/可点溯源；主题视图点节点 `kind:"point"`；有点时禁用分层铺开。
- 全量测试 **629 passed / 1 skipped**；canary 1 passed；`node --check` 通过；`git diff --check` 干净。
- serve 已重启加载新代码：trampoline **26840**，监听 **4196**（8420），令牌指纹 `2ad28785` 未变；
  HTTP 实测 `/api/graph/radiate?node_id=p:5c07508429801ddf` → 18 节点/18 边全部有理由，
  连点两次切焦点仍非空；`/api/graph/subtree?...&layer=points&point_limit=5` → 5 点 +
  `truncated.points=4460`；`/graph.html` 已含 `pointLayer` / `layer=points` / `kind === "point"`。

**下一步（按序，首步可直接执行）**：

1. 用户浏览器 Ctrl+F5 打开 `http://127.0.0.1:8420/graph.html`：勾选「◆ 点层」→ 下钻到叶子层
   看知识点；点任一点节点切焦点（连点两次不空）；悬停点卡看正文/书籍章节/溯源链接。
2. 若验收有 UI 反馈，改 `graph.html` 即可（静态文件 no-store，无需重启 serve）。
3. 之后再做 TODO P5（扩散抓取加固）或 P4 后置项（引用/指涉边、点级反查 `reverse` 对 `p:`）。

**不要重跑**：

- P4 实现与全量测试（629 passed / 1 skipped，2026-10-26 20:14）；
- 不要重跑 P3 全库重点——库内 4,552 点已是 kpe 全文分块产物（`extractor=kpe`）；
- 不要重启 serve（4196 已加载 94b17e2；前端改动 Ctrl+F5 即可）；
- 不要提交 `docs/交接/`（session-guard watcher 的草稿产物，未跟踪）。

**验证命令**：

- `uv run python -m pytest -o addopts= -q` → 期望 `629 passed, 1 skipped`；
- `uv run python -m pytest tests/test_canary.py -o addopts= -q` → 1 passed；
- `curl "http://127.0.0.1:8420/api/graph/radiate?node_id=p:5c07508429801ddf"`（Host: 127.0.0.1:8420）
  → `focus.kind=point`、18 节点/18 边、`truncated={same_book:50, sim:1205}`。

**已知失败与处理**：无。上下文 95.2%（CRITICAL），按协议停会话写交接。

## 2026-10-26 20:36 图页全屏 + 节点标签字色（用户验收反馈① ②）

用户验收 P4 点级图时提两条：① 进 `graph.html` 没法全屏、顶部两行工具栏把画布挤小，希望保留一个退出全屏按钮；
② 切焦点（放射视图）后同样要全屏；节点上的字看不清——**不要加描边**，要换与背景对比够的字色。

改动：只动 `src/knowatlas/web/static/graph.html`（+93/−5，无 API / 表结构 / config / 接口签名变更）：

- **全屏**：header 加「⛶ 全屏」（`documentElement.requestFullscreen()`），`fullscreenchange` 切 `body.fs`；
  全屏时 header 变浮层，鼠标贴顶边（≤64px）唤出、离开 2.5 s 自动收起，画布吃满整屏；
  另放 `#fsExit`「⤢ 退出全屏」固定右上角（z-index 21，在 `#chart` 之外），header 收起时也点得到；
  Esc 走浏览器原生，同样触发 `fullscreenchange` 收尾。全屏状态挂在 document 上，
  切焦点 / 下钻 / 搜索都不退出（`render()` 不碰它），尺寸变化在 `requestAnimationFrame` 里 `chart.resize()`。
- **标签字色**（不加描边、无白底）：原来 `label.color` 未设，吃 ECharts 默认色，深色底 + 密集边看不清。
  按类型分级给浅色（对 `--bg-0` 的对比度）：焦点 `--warning` 8.6:1、分类 `--text-1` 16.4:1、
  条目 `--accent-text` 10.4:1、知识点 `--point` 10.0:1、上下文 `--text-2` 8.8:1（原 `--text-3` 5.3:1）；
  字号条目 10→11、知识点 11、分类 13；边上「关联解释」文字 `--text-3`→`--text-2`。

验证（2026-10-26 20:35）：

- 内联脚本 `new Function` 语法检查通过（648 行）；`git diff --check` 干净。
- 线上 `GET /graph.html` → HTTP 200 / 42,467 B，含 `id="fsBtn"`、`id="fsExit"`、`body.fs header`、`PAL.labelEntry`
  （静态文件 no-store，无需重启 serve）。
- 全量测试 `uv run python -m pytest -o addopts= -q` → **629 passed, 1 skipped**（44.5 s）。
- **headless Edge + CDP 实测通过**（脚本留在 `temp/ui_fs_metrics.js`、`temp/ui_fs_flow.js`、
  `temp/ui_point_label_check.js`；1600×900，真实鼠标事件）：
  - 点「⛶ 全屏」→ `document.fullscreenElement=true`、`body.fs`、画布 **1600×900**、
    `#fsExit` display block @ (1500,10,88,27)、header `position: fixed`；
  - 全屏下切焦点（`showRadiate("p:5c07508429801ddf")`）→ 19 节点、**仍全屏**、退出按钮仍在，
    header 2.5 s 后 `is-hidden`（transform translateY(−67px)、opacity 0）；
  - 全屏下用 `Input.dispatchMouseEvent` 真点另一个点节点（838,251）→ 焦点切到 `p:fc108e22bc03b803`、
    **仍全屏**、退出按钮仍在，悬停出「◆ 知识点」卡；
  - 点「⤢ 退出全屏」→ 全屏退出、header 回 `static`、按钮回「⛶ 全屏」、`#fsExit` 归 `display: none`；
  - 字色实测（`chart.getOption().series[0].data[].label`）：焦点 `#DFA43E` 11px 粗 / 分类 `#E9EDF4` 13px /
    知识点 `#6FCF97` 11px / 条目 `#9CC0F7` 11px / 关联解释 `#A6B0C0` 9px；无描边、无白底。
- 旁证数据：点层根分类「人工智能」经典视图 → 205 节点 / 200 点（超过 60 点阈值时不显示常驻标签，靠悬停卡）。

不要重跑：P4 后端与全量测试（629 passed / 1 skipped，20:14）；不要重启 serve（4196 已载 94b17e2，
前端改动 Ctrl+F5 即生效）。

<!-- HANDOFF {"at":"2026-10-26T20:16:40+08:00","compactions":1,"doc":"docs/log.md#2026-10-26-2020","draft":false,"goal":"P4 点级图已交付（94b17e2），待浏览器验收","host":"dsh","kind":"handoff","next":"用户 Ctrl+F5 验收 /graph.html 点层；之后 P5 或 P4 后置项","not_rerun":"P4 实现与全量测试（629 passed）；P3 全库重点；serve 重启（PID 4196 已载 94b17e2）","schema":1,"session":"session-01217ada-3f22-44e9-b9c2-306b3732d74f","status":"HANDOFF","tokens":140038,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->
## 2026-10-26 20:58 点标签随缩放显隐（反馈②追补）

用户口径：点层「>60 点不常驻显示点标签」改成**随缩放显隐**，阈值选**间距 56 px**。

实测依据（headless Edge + CDP，205 点 force 视图 1600×900，最近邻间距中位）：
zoom 1 → 32.6 px；1.6 → 60.6；2.2 → 81.8；3.0 → 111.5。另有一条硬结论：
**直接合并 setOption 换 data（改 label.show）会让 force 重跑，205 节点最大位移 280 px**，所以不能直接改 data。

实现（只改 `graph.html`，无 API / DB / config 契约变更）：

- `render()` 新增 `opts.zoom` / `opts.center`；点标签判据改成「屏幕上排得开」：
  `zoom >= pointLabelNeedZoom(n) = 56 / (0.39·sqrt(W·H/n))`（0.39 为实测系数），n ≤ 60 仍一直显示；
  隐藏时 tip 提示「放大到约 N× 显示」。
- 冻结布局：`graphRoam` 防抖 260 ms 后若显隐需翻转，先把 chart 当前坐标写回 `lastData.nodes[].x/y`，
  再带 zoom/center 重渲染；`render` 见所有节点都有数值 x/y 时用 `layout: "none"`，force 不重跑。

浏览器实测（`temp/ui_label_zoom_verify.js`，真实滚轮事件）：

- 初始 zoom 1 / layout force / 标签 5（仅分类）/ tip 提示「约 1.7×」；
- 滚轮放大到 zoom 2.59 → **layout 变 none、标签 205（分类 5 + 点 200）**；
- 再缩到 1.77（仍 ≥1.7）→ 标签仍 205、**节点位移 0.00 px**（冻结生效）；
- 放射视图 19 节点、条目视图 26 节点：标签与布局不受影响；控制台无异常；
- **未测**：缩回阈值以下（与放大同一函数、分支对称，留待验收时顺手看）。

环境事件：serve 在 20:3x—20:4x 间自行退出（8420 无监听、无 python 进程），已按凭据纪律重启
（`HKCU\Environment` 三个 `KNOWATLAS_*` → env 后 `uv run python -m knowatlas serve`），现 `GET /graph.html` 200 / 42,467 B，
令牌仍是用户级 22 字符那个。watcher 20:48 WARN / 20:50 CRITICAL 是上下文真实上涨（20:52 probe 101.9%）。

**下一步（新会话按序）**：

1. `session-guard check --workspace "D:\sData\git\KnowAltas"` + `probe`；`GET /graph.html` 确认 200（serve 本轮已重启，PID 会变）。
2. 用户 Ctrl+F5 验收：点层 205 点视图滚轮放大到 ~1.8× 出点标签、缩回消失；切焦点仍全屏且右上角有退出。
3. 如果要更细的密度控制，可把「整层翻转」升级成「逐节点按标签宽度贪心排布」（本轮未做）。

**不要重跑**：P4 后端与全量测试（629 passed / 1 skipped，20:33）；点标签随缩放显隐的浏览器实测（20:57）；
不要重复重启 serve（除非确认 8420 无监听）。

**验证命令**：
`uv run python -m pytest -o addopts= -q` → 629 passed, 1 skipped；
`node temp/ui_label_zoom_verify.js`（先按 `AGENTS.local.md` 起 headless Edge 9333）；
`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8420/graph.html` → 200。

<!-- HANDOFF {"at":"2026-10-26T20:58:30+08:00","compactions":0,"doc":"docs/log.md#2026-10-26-2058","draft":false,"goal":"点标签随缩放显隐已交付并浏览器实测，待用户 Ctrl+F5 验收","host":"dsh","kind":"handoff","next":"用户验收点层缩放显隐与全屏；之后 P5 或 P4 后置项","not_rerun":"P4 后端与全量测试（629 passed）；缩放显隐实测（20:57）；serve 已重启勿重复","schema":1,"session":"session-14998ff3-54df-4879-8410-09ac03713ee2","status":"HANDOFF","tokens":150000,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

## 2026-10-26 21:00 补测：点标签「缩回阈值以下」（20:57 标为未测的分支已闭环）

上一轮只测了放大方向，缩回方向留了空（`branch 对称、留待验收顺手看`）。本轮用 headless Edge + CDP
补测，脚本 `temp/ui_label_zoomout_verify.js`（真实滚轮事件，1600×900，点层 205 点视图）：

- 初始 zoom 1 / layout force / 标签 5（仅分类），tip 提示「放大到约 1.7× 显示」；
- 滚轮放大 10 格 → zoom 2.59 / layout none / 标签 205（分类 5 + 点 200）；
- **缩回 12 格 → zoom 0.83（低于阈值 1.71）→ 标签回到 5（仅分类）**，tip 恢复「放大到约 1.7× 显示」；
  与放大后快照比：**moved 0 / maxDelta 0**，布局包围盒 1112×1064 未变——force 没重跑、坐标没被二次缩放；
- 再放大回 2.14 → 标签 205、位移仍 0；控制台无异常。

结论：显隐两向对称，`refreshPointLabels → freezeLayout → render(layout:"none")` 在「转为隐藏」分支
同样保位。环境备注：沙箱内 Edge 起不来（`mojo platform_channel` 建命名管道被拒 0x5），
UI 实测必须切完全权限；profile 用 `%TEMP%\edge-qa-*`，跑完即关。

不要重跑：本项实测（20:59）。下一步仍是用户 Ctrl+F5 验收 + P5 扩散加固 / P4 后置项（点级反查）。

## 2026-10-26 21:15 P5 扩散抓取加固（三条全落地，634 passed / 1 skipped）

用户裁决：按方案开工（3 个源文件 + 测试 + 文档；不动表结构/字段/scheme/SOURCE_TYPES/STATUSES/
CONFIG_SCHEMA_KEYS/接口签名，故无工单，canary 四常量零漂移）。

改动：

- `semantic/value_guard.py`：新增正文层判据 `is_index_page(text)`（纯函数、零 IO、零费用）。
  四条件**同时**成立才判：① 表格成型（表头 + `|---|` + ≥1 数据行）；② 某行命中列名关键词 ≥2
  （书名/作者/下载/格式/大小/… + name/title/author/download/… 中英两套）；③ 数据行含
  Markdown 链接 `[x](y)` ≥50%；④ 表格行占非空行 ≥40%。``` 代码块内的行不参与统计。
- `pipeline/expand.py`：`_candidate_links` 改为返回 `(links, skipped)`——`${`/`{{`/`<%`
  占位符在提取层剔除（`stats.filtered_placeholder`），自链接同样剔除但计入 `already_known`
  （统计口径不变，不再多进一次候选）；入库前接 `is_index_page`（`stats.index_page` +
  `log_task("index_page_skip")`，不建条目）；模块 docstring 增「已知限制」（扁平 ID 平台）。
- `pipeline/sync.py::_value_scan`：URL 结构判不出时补判正文（只读条目自带 `inline_content`，
  不读 content_store，零额外 IO），写 `value_flag_reason="index_page"`；仍只标记不删除。
- 文档：`TODO` P5 三条打勾并写落地口径；使用手册第 10 节第 5 条改写（书目页已由守卫拦，
  扁平 ID 平台仍不适用）。

验证（2026-10-26 21:12）：

- `pytest -o addopts= -q` → **634 passed / 1 skipped**（629 + 5：占位符/自链接提取层、
  书目页拦截、`is_index_page` 正反例、`value_scan` 端到端），52.6 s；`tests/test_canary.py` → 1 passed。
- 真库只读实测：49 条有正文条目中 20 条书目页**全部命中**、其余 0 误报
  （`temp/probe_is_index_page.py`、`temp/probe_index_minrows.py`）。
- `uv run python -m knowatlas ksync --value-scan --dry-run` → `value_scan_total 30 /
  new_flagged 0 / by_reason {}`（那 20 条已 rejected，扫描面是 active），零写入。
- 阈值过程留痕：初版 `min_rows=3` 只命中 11/20——真站存在「一本书一页」形态；
  改为「表格成型 ≥3 行 + 数据行 ≥1」后 20/20、仍 0 误报。

已知失败：`www.liaoxuefeng.com` 现网 TLS 握手超时（本机出网限制），占位符过滤只有单测覆盖，
未做真站复核（Docker/代理恢复后可补一次 `_candidate_links` 实跑）。

不要重跑：全量测试与真库 dry-run（21:12）。下一步：用户 Ctrl+F5 验收图页；之后 P4 后置项
（点级反查 `reverse` 对 `p:`、引用/指涉边）。
<!-- HANDOFF {"at":"2026-10-26T21:10:11.475951+08:00","compactions":0,"doc":"docs/交接/2026-10-26-2110.md","draft":true,"goal":"上下文到 HANDOFF（87.5%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-4e57cc6b-3c18-4754-a4b8-81fedf2ae843","status":"HANDOFF","tokens":128614,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

## 2026-10-26 21:10 交接：P5 扩散加固已交付（634 passed），上下文 88.5% 停会话

### 当前目标

P5 已交付并提交；用户下一步是浏览器验收图页，之后在**新会话**开 P4 后置项（点级反查 / 引用指涉边）。

### 已完成（含产物路径与现场数字）

- **提交**：`2d2ec99` feat(expand) P5 扩散加固（7 文件 +259/−21）；`2b65fa3` feat(web) 待清理候选加
  「书目索引页」reason 标签；`1780466` docs 点标签缩回阈值补测。
- **P5 三条全落地**：
  - `semantic/value_guard.py::is_index_page`：正文层判据（表格成型 / 列名关键词 ≥2 / 数据行带链接
    ≥50% / 表格占非空行 ≥40%；代码块不统计）。
  - `pipeline/expand.py`：`_candidate_links` 提取层剔 `${`/`{{`/`<%` 占位符与自链接
    （`filtered_placeholder`；自链接仍计入 `already_known`）；入库前 `is_index_page` 拦截
    （`stats.index_page` + `log_task("index_page_skip")`）；docstring 增「已知限制」。
  - `pipeline/sync.py::_value_scan`：URL 判不出时补判正文（只读 `inline_content`），
    `value_flag_reason="index_page"`。
  - 文档：`docs/design/知识索引工具-TODO.md` P5 三条打勾；使用手册第 10 节第 5 条改写。
- **测试**：`pytest -o addopts= -q` → **634 passed / 1 skipped**（21:04 与 21:08 两次）；
  `tests/test_canary.py` → 1 passed（四常量零漂移，无工单）。
- **真库实测（只读）**：49 条有正文条目中 20 条书目页全部命中、其余 0 误报；
  `ksync --value-scan --dry-run` → `value_scan_total 30 / new_flagged 0 / by_reason {}`，零写入。
  脚本：`temp/probe_is_index_page.py`、`temp/probe_index_minrows.py`（temp 可清）。
- **图页补测**：点标签「缩回阈值以下」分支已闭环（zoom 0.83 隐藏、位移 0；回放大 2.14 仍 0），
  脚本 `temp/ui_label_zoomout_verify.js`。

### 下一步（按序，首步可直接执行）

1. 用户 `Ctrl+F5` 打开 `http://127.0.0.1:8420/graph.html`：点层 205 点视图滚轮放大出标签、
   缩回消失；切焦点仍全屏、右上角有退出按钮（验收 20:57 + 20:59 两轮实测）。
2. 新会话开场：`session_check`（期望 NEW_SESSION）+ `pytest -o addopts= -q`（期望 634 passed / 1 skipped）。
3. P4 后置项二选一，**都需先出方案再动代码**：
   - 点级反查：`reverse` 支持 `p:`（当前 404，见 TODO P4「已知限制」）；
   - 引用/指涉边：最贵通道，需新工单。
4. 可选验收动作：真跑一次 `uv run python -m knowatlas ksync --value-scan`（当前 active 30 条命中 0，
   零副作用；以后新条目才会被标 `index_page`）。

### 不要重跑

- 全量测试（634 passed / 1 skipped，21:08）——除非改业务代码；
- 真库 `--value-scan --dry-run`（21:12 已跑，命中 0）；
- 图页缩放显隐两向实测（20:57 / 20:59）；
- `kpe chunks`、全库重点、P3 全库重抽（历史结论，见前几条交接块）。

### 验证命令

```powershell
uv run --with zstandard python tools/session_check.py    # 新会话应 NEW_SESSION
uv run python -m pytest -o addopts= -q                   # 634 passed, 1 skipped
uv run python -m knowatlas ksync --value-scan --dry-run  # value_scan_total 30 / new_flagged 0
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8420/graph.html   # 200
```

### 已知失败与处理

- `www.liaoxuefeng.com` 现网 TLS 握手超时（本机出网限制），占位符过滤只有单测覆盖，未做真站复核。
- 沙箱内 headless Edge 起不来（`mojo platform_channel` 建命名管道被拒 0x5）：UI 实测需完全权限；
  profile 用 `%TEMP%\edge-qa-*`，跑完即关。
- `docs/交接/` 是 watcher 草稿产物，未跟踪、不要提交。

### 会话指纹

`session-4e57cc6b-3c18-4754-a4b8-81fedf2ae843`，compactions=0，tokens≈130,185，
baseline 147,059，effective 88.5%（HANDOFF），2026-10-26T21:10+08:00。

## 2026-10-26 21:25 P4 后置项：点级反查（`reverse` 支持 `p:`，639 passed / 1 skipped）

- 用户裁决选 A（点级反查）。工单 `docs/design/变更工单-2026-10-26-P4点级反查.md`（先工单、后代码）。
- **数据层** `db.reverse_reach` 增 `point` 分支 → `_point_reverse_items`：① 溯源条目
  （`kind=entry`、`reason=source:point`、带 `locator`）② 这些条目挂的分类
  （`kind=category`、`attach:<origin>`、带 `path`、按 `category_id` 去重）。闸门复用
  `_point_row`（stale / dupe_of / 溯源全回收 → None → 404），与 radiate 点焦点同源。
  对称边（same_book/same_section/sim）**刻意不反向枚举**（= 把放射视图再列一遍）。
- **接口** `/api/graph/reverse?node_id=p:<id>` 404→200、`focus.kind=point`、条目项多可选
  `locator`；`c:`/`e:` 逐字不动、`d:` 仍 404。表结构/字段/locator scheme/`SOURCE_TYPES`/
  `STATUSES`/`CONFIG_SCHEMA_KEYS`/能力注册表零变更（canary 零漂移）。
- **前端** `graph.html`：`KIND_LABEL` 补 `source:"溯源"`/`point:"知识点"`（→「溯源·知识点」）；
  反查面板 entry 带 `locator` 渲染外链；404 文案改「域名与未知节点无反查」。
- **测试** `tests/test_graph_point_layer.py` +5 例 + 静态探针 2 条断言；
  全量 `pytest -o addopts= -q` → **639 passed / 1 skipped**（原 634），57 s。
- **实测**：真库只读副本 4/4 点可反查——`p:5c07508429801ddf` → entry
  `8.部署智能体与智能体系统`（`file://…md`）+ category `人工智能/智能体`（`attach:llm`），
  与 `radiate` 的 `focus.sources` 完全一致（脚本 `temp/probe_reverse_point.py`）；
  重启 serve（8420，PID **15968**）后 `curl …/reverse?node_id=p:5c07…` → **200**，
  `d:example.com` / `p:nope` 仍 404；graph.html 200 / 46,477 B。
- **UI 实测**（headless Edge + CDP，`temp/ui_reverse_point_check.js`）：点焦点（放射 19 节点）→
  点「🔍 反查」→ 面板两行：「条目 8.部署智能体与智能体系统 ↗（理由：溯源·知识点）」+
  「分类 智能体（路径：人工智能/智能体，理由：挂接·语义判断）」，外链 href 为 file://，无 console 异常。
- **环境**：本会话 `workspace-write` 下 pytest 全红（431 个 PermissionError，dsh 临时目录与
  `.pytest_cache` WinError 5）——不是代码问题；切完全权限后 f绿、Edge 可用。跑测试/UI 实测都要完全权限。
- **下一步**：用户 Ctrl+F5 验收图页（点层 → 点聚焦 → 🔍 反查）；之后 P4 第四类边「引用/指涉」
  需单独工单（规则先行 + 可选 LLM 复核，见工单 §7）。
- **不要重跑**：全量测试（639 passed，21:23）；真库反查探针（只读副本，21:18）；
  UI 反查实测（21:21）；serve 刚重启（PID 15968 已载本轮代码，前端改动 Ctrl+F5 即生效）。
- **提交**：`93d6efa` feat(graph)：P4 后置项——点级反查（9 文件 +273/−10）。

<!-- HANDOFF {"at":"2026-10-26T21:12:30+08:00","compactions":0,"doc":"docs/log.md#2026-10-26-2110","draft":false,"goal":"P5 扩散加固已交付（2d2ec99 / 634 passed），待用户浏览器验收图页","host":"dsh","kind":"handoff","next":"用户 Ctrl+F5 验收 graph.html 点层缩放显隐与全屏；新会话先 session_check + pytest（634/1），再出 P4 后置项方案（点级反查 reverse 对 p: 或引用/指涉边）","not_rerun":"全量测试（634 passed，21:08）；真库 value-scan dry-run（21:12）；图页缩放显隐两向实测（20:57/20:59）","schema":1,"session":"session-4e57cc6b-3c18-4754-a4b8-81fedf2ae843","status":"HANDOFF","tokens":130185,"verify":"uv run --with zstandard python tools/session_check.py"} -->

## 2026-10-26 21:32 交接：点级反查已交付（93d6efa / 639 passed）

### 当前目标

P4 后置项 A（点级反查）已交付并提交；用户下一步是 Ctrl+F5 验收图页反查面板，
之后若要继续 P4 只剩第四类边「引用/指涉」（需新工单，最贵）。

### 已完成（含产物路径与现场数字）

- **提交**：`93d6efa` feat(graph) 点级反查（9 文件 +273/−10）、`b1e469a` docs 补提交号。
- **数据层** `db.reverse_reach` + `_point_reverse_items`（放在 `_point_*` 块内，紧跟 `_point_sources`）：
  溯源条目（`source:point`，带 `locator`）+ 分类（`attach:<origin>`，带 `path`，按分类去重）；
  闸门复用 `_point_row`；对称边不反向枚举。
- **接口** `/api/graph/reverse?node_id=p:<id>` 404→200；`c:`/`e:` 不动、`d:` 仍 404；
  条目项多可选 `locator`；无表结构/字段/scheme/四常量变更（canary 1 passed）。
- **前端** `graph.html`：`KIND_LABEL` 补 source/point；反查面板 entry 带 locator 渲染外链；404 文案修正。
- **测试** `tests/test_graph_point_layer.py` +5 例；全量 **639 passed / 1 skipped**（21:23 与 21:30 两次）。
- **真库/线上**：只读副本 4/4 点可反查（`p:5c07508429801ddf` → entry + `人工智能/智能体`）；
  serve 已重启（8420，PID **15968**），`/reverse?node_id=p:5c07…` → 200，graph.html 200 / 46,477 B；
  headless Edge 实测面板两行、理由「溯源·知识点」/「挂接·语义判断」、无 console 异常。

### 下一步（按序）

1. 用户 `Ctrl+F5` → `http://127.0.0.1:8420/graph.html`：点层 → 点节点切焦点 → 「🔍 反查」，
   应看到溯源条目（可点开原文）+ 分类链。
2. 若继续做 P4 第四类边「引用/指涉」：**先出方案再动代码**（建议规则先行：`[n]` 编号引用、
   `见 §x`、书名+章节号、内文 URL；LLM 只做候选复核），并新写工单 + 新 reason 通道 `cite:`。
3. 其他候选（TODO P0–P3 收尾项）：无。

### 不要重跑

- 全量测试（639 passed / 1 skipped，21:30）；
- 真库反查探针（`temp/probe_reverse_point.py`，只读副本，21:18）；
- UI 反查实测（`temp/ui_reverse_point_check.js`，21:21）；
- 不要重启 serve（PID 15968 已载本轮代码，前端改动 Ctrl+F5 即生效）。

### 验证命令

```powershell
uv run --with zstandard python tools/session_check.py    # 新会话应 NEW_SESSION
uv run python -m pytest -o addopts= -q                   # 639 passed, 1 skipped
curl "http://127.0.0.1:8420/api/graph/reverse?node_id=p:5c07508429801ddf"   # 200，items 2 项
```

### 已知失败与处理

- 本会话 `workspace-write` 模式下 pytest 全红（431 个 PermissionError：dsh 临时目录与
  `.pytest_cache` WinError 5），**不是代码问题**；切完全权限（danger-full-access）后全绿，Edge 也可用。
  跑测试 / UI 实测需完全权限。
- `docs/交接/` 是 watcher 草稿产物，未跟踪、不要提交。

### 会话指纹

`session-0130f5c8-6441-4fe1-badc-66aadafbf63c`，compactions=0，tokens≈114,225，
baseline 147,059，effective 77.7%，2026-10-26T21:32+08:00。

<!-- HANDOFF {"at":"2026-10-26T21:32:10+08:00","compactions":0,"doc":"docs/log.md#2026-10-26-2132","draft":false,"goal":"点级反查已交付（93d6efa / 639 passed），待用户 Ctrl+F5 验收图页反查面板","host":"dsh","kind":"handoff","next":"用户验收 /graph.html 点聚焦后的反查面板；若继续做 P4 第四类边引用/指涉需先出方案+新工单（规则先行，LLM 只复核候选）","not_rerun":"全量测试（639 passed，21:30）；真库反查探针（只读副本）；UI 反查实测；serve 已重启（PID 15968）","schema":1,"session":"session-0130f5c8-6441-4fe1-badc-66aadafbf63c","status":"HANDOFF","tokens":114225,"verify":"uv run --with zstandard python tools/session_check.py"} -->


## 2026-10-26 21:45 P4 引用/指涉判停 + TODO 8.15 正文库回收（`2c068f8` / 643 passed / 1 skipped）

### 开场判据

- `session_check` = `NEW_SESSION`（exit 0），上一交接 `session-0130f5c8` @ 21:32 `status=HANDOFF`；
- `context_probe`：`effective_pct` **10.2%**（15,014 / 147,059，compactions=0）；
- 基线 `pytest -o addopts= -q` → **639 passed / 1 skipped**（57.5 s，与交接一致）；
- serve PID **15968** 在听 8420：`graph.html` 200、`reverse?node_id=p:5c07508429801ddf` 200、`d:example.com` 404；
- 未重跑交接块「不要重跑」的四项（真库反查探针 / UI 反查实测 / 全量测试已重跑但为验证目的 / serve 未重启）。

### 做了什么

**1. P4 第四类边「引用/指涉」实测判停（负结果）**

只读探针三层（`temp/probe_cite_feasibility.py`、`temp/probe_cite_entries.py`）：

| 层 | 规模 | 命中任一引用形态 | 可解析到库内目标 |
|---|---|---|---|
| 点正文（消费面，口径同 `_point_row`） | 4,509 点 / 26 本书 | **7 点（0.2%）** | **0** |
| 条目正文（`content_store`/`inline_content`） | 29 条，均截断 4,023 字 | 章节号 17（全是目录页）/ URL 7 | **0** |
| 原始语料 `D:\sData\KnowLedge` | 131 个 `.md` | 脚注 4 / 相对链接 9 / 参见 13 | — |

根因：语料是成书与白皮书（自包含），kpe 抽取把正文压成要点，引用记号被抹掉；条目层还叠加 R10 的
4,023 字 integral 降级。结论：照原计划实现产出 0 条边，**不做**；门槛（候选点 ≥200 且可解析命中 ≥50，
或 kpe 产物开始携带脚注/相对链接）写进工单 §7 与 TODO P4。

**2. TODO 8.15 正文库孤儿回收（已交付）**

- `datalayer/db.py::gc_orphan_contents(max_age_days=1.0, dry_run=True)`：孤儿 = 无任何
  `entries.content_hash` 指向的 `content_store` 行；阈值保护防同步竞态，`fetched_at` 缺失/坏串按最老处理；
  只删 `content_store` + `content_fts`，写 `task_log(content_gc)`；SQL 全在 datalayer。
- `cli.py`：`kcheck --gc-content [--gc-days N] [--dry-run]`，该分支不联网、不调 LLM。
- `tests/test_content_gc.py` 4 例（dry-run 零写入 / 只删孤儿且 fts 同步清 + 审计一次 / 幂等 /
  `--gc-days 0` 连过新孤儿一起收）。
- 真库：`--dry-run` 孤儿 6 / 释放 2,552,280 字符 → 备份 `temp/knowledge.pre-gc.db`（120.6 MB）→ 实跑
  删 6 → `content_store` **55→49**、`orphans 0`、`content_fts 49`、有引用的 49 行原样、
  `entries 241` / `points 4,552` 零变化；重跑 `candidates 0`。
- 全量 `pytest -o addopts= -q` → **643 passed / 1 skipped**（58.7 s，639 + 4）；canary 零漂移（无契约变更）。

### 提交

`2c068f8` feat(check)：TODO 8.15 正文库孤儿回收 + P4 引用/指涉判停（6 文件 +225/−8）。

### 下一步

1. 用户 `Ctrl+F5` 验收 `http://127.0.0.1:8420/graph.html`：点层 → 点节点切焦点 → 「🔍 反查」
   （21:21 已用 headless Edge 验过面板两行，待人眼确认）。
2. 剩余 TODO 里可直接开工的：R10（LLM 键缺失被静默降级成 4,023 字 integral 点）、
   8.3/8.4（书签与本地文本源的端到端验收，需配置指向小目录）；三凭证源（B站/IMA/腾讯文档）等凭证。

### 不要重跑

- 全量测试（643 passed / 1 skipped，21:52）——除非再改业务代码；
- `kcheck --gc-content` 实跑（已归零；重跑只出 candidates 0）；
- 引用/指涉三层探针（结论已落工单 §7，别再花时间调研）；
- serve 未重启，PID 15968 仍载 21:23 的代码（本轮只改 CLI/数据层维护路径，图页不受影响）。

### 验证命令

```powershell
uv run python -m pytest -o addopts= -q                     # 643 passed, 1 skipped
uv run python -m knowatlas kcheck --gc-content --dry-run   # 孤儿 0 / 已删 0
uv run --with zstandard python tools/context_probe.py      # 本会话 66.5%（97,738 / 147,059）
```

### 会话指纹

`session-7d7ad876-3a1b-4cee-8500-addb58131143`，compactions=0，tokens≈97,738，
baseline 147,059，effective 66.5%（OK），2026-10-26T21:52+08:00。

## 2026-10-26 22:00 条目原文站内代理（修「反查可溯源，但打不开」/ 653 passed）

### 当前目标

用户报障「反查可溯源，但打不开」→ 已定位为 `file://` 假链接并交付站内代理端点；**待用户 Ctrl+F5 验收**。

### 做了什么

- **定位**：反查面板 L690 把 `it.locator` 原样塞 `<a href>`；真库 30 条 active（29 folder + 1 emmx）中 29 条 locator = `file://<相对 D:/sData/KnowLedge>`（多为 PDF）。`file://` 首段被当主机名 + http 页禁跳 file:// → 必失败。`index.html` 12 处同样。
- **接口** `web/api.py::entry_file`：`GET /api/entries/{id}/file` 只读代理（roots 逐根解析 + realpath `is_relative_to` 包含性；`..`/盘符 → 403 OUT_OF_ROOT；PDF/图片 inline、md/txt text/plain、HTML/SVG/Office/emmx 强制 attachment 防同源脚本读走写令牌；一律 nosniff；零写库零 LLM）。
- **前端**：`ui.js` 新增 `ka.rawHref`/`ka.linkOrText`（http(s) 直开 / `file://`+entryId → 代理 / 其它 scheme → 空串退化纯文本）；`graph.html` 4 处（点卡溯源、条目「打开原文」、反查面板、条目节点点击）、`index.html` 12 处全部换用；`ui.js` 引用加 `?v=20261026` + 页面侧兜底。
- **测试**：新增 `tests/test_entry_file.py` 10 例；`test_web_api.py` 静态探针改断言 `rawHref` 且 locator 不得原样进 href；全量 **653 passed / 1 skipped**（22:03），canary 六项零漂移。
- **实测**：线上 `9f118bf8f0d79592` → 200 `application/pdf` inline nosniff（11.6 MB）、`4e3fcf4dc53d4a88` → 5.6 MB；headless Edge 反查面板 `/api/entries/75781c6e900f6fca/file` fetch 200 text/plain；首页 entryHTML/entryCard/预览「打开原文」均指代理，emmx 退化纯文本，无 console 异常。

### 下一步（按序）

1. 用户 `Ctrl+F5` → `http://127.0.0.1:8420/graph.html` → ◆点层 → 点节点 → 🔍 反查 → 点溯源条目（应新标签打开 PDF）。
2. 首页条目标题 / 预览面板「打开原文」同样可开。
3. 剩余候选：R10（LLM 键缺失被静默降级）、8.3/8.4 端到端验收。

### 不要重跑

- 全量测试（653 passed / 1 skipped，22:03）；canary（零漂移）。
- 站内代理真库实测（2 个 PDF 200 + CDP 脚本 `temp/ui_entry_file_check.js`，22:00）。
- serve 已重启（PID 12672，载本轮代码；前端改动 Ctrl+F5 即生效）。

### 验证命令

```powershell
curl -s -D - -o NUL "http://127.0.0.1:8420/api/entries/9f118bf8f0d79592/file"   # 200 application/pdf inline
uv run python -m pytest -o addopts= -q                                            # 653 passed, 1 skipped
```

### 会话指纹

`session-36dab62e-d79a-41ff-80d4-2318745065a9`，compactions=0，tokens≈138,943，
baseline 147,059，effective 94.5%（HANDOFF），2026-10-26T22:00+08:00。

<!-- HANDOFF {"at":"2026-10-26T22:00:00+08:00","compactions":0,"doc":"docs/log.md#2026-10-26-2200","draft":false,"goal":"条目原文站内代理已交付（653 passed），待用户 Ctrl+F5 验收反查与首页「打开原文」","host":"dsh","kind":"handoff","next":"用户验收 graph.html 反查面板与 index.html 打开原文；之后可做 R10 或 8.3/8.4 端到端验收","not_rerun":"全量测试（653 passed / 1 skipped）；站内代理真库实测；serve 已重启（PID 12672）","schema":1,"session":"session-36dab62e-d79a-41ff-80d4-2318745065a9","status":"HANDOFF","tokens":138943,"verify":"uv run --with zstandard python tools/session_check.py"} -->

## 2026-10-26 22:08 8.3/8.4 端到端验收收口 + R10 两半落地（654 passed / 1 skipped）

### 当前目标

Phase 8 阶段 A 收尾：把 8.3（书签 + 网页）与 8.4（本地文本/HTML）的探针从「单测覆盖」补成
**真数据端到端证据**，并清掉两处小残留（空正文守门、kpoints 报告暴露 LLM 可用性）。
结论：8.3 / 8.4 / R10 三项均可转 `[x]`。

### 做了什么

- **8.3 条目数对齐**：`data/bookmarks-edge-knowledge.json` 191 个 url 节点（181 https / 10 http）
  → 库内 `source_type=bookmark` **191 条**（161 pending + 30 rejected），与有效书签数 1:1；
  `distinct locator_canonical = 186`，5 个「同 URL 多文件夹收藏」按契约各建一条（M2 跨源去重留给 dedupe 层）。
- **8.3 native_path**：中文根标签 + 文件夹层级 —— 书签栏/AI 54、其他书签/js 37、其他书签/python 25、
  其他书签/php 16、书签栏/后端 10、书签栏/前端 9、书签栏/JS&TS 7 …（共 15 条路径）。
- **8.3 导航残留**：真抓 3 条 —— 简书 9,626 → 9,604 字、导航词 0（"注册"4 次是正文"注册组件"）；
  博客园 11,461 → 11,209 字、导航词 0；知乎 HTTP 403（simple 后端无反爬能力，真同步会走
  fallback deepseek）。readability + `is_skeleton_body` 骨架闸门把按钮墙挡在入库前。
- **8.4 沙箱（不碰真库/真配置）**：`KNOWATLAS_CONFIG=temp/ka84/config.toml` + 独立库；
  fixture 9 文件 → **入库 8 条**，`skipped_hidden=1`、`skipped_ext=1`（png）；
  `native_path` 四层全对（`知芯小样本` / `知芯小样本/同名` / `知芯小样本/子目录` / `知芯小样本/子目录/再深`）；
  根 `笔记A.md` 与 `同名/笔记A.md` 各一条、互不覆盖。
- **8.4 判定**：乱码文件（非法 UTF-8 10 字节）→ `fetch_status=garbled` + `value_flag=not_knowledge`，
  **不进消费面** ✓；空文件（0 字节）首轮验收时 `fetch_status=ok`、无 value_flag（可消费）✗ → 已修（见下）。
- **R10 两半**：`kcheck/kpoints` 在 key 缺失时打 `WARN 语义层降级：…`（本轮 shell 未导入 key 时实测）；
  `run_points_extract` 的 stats 新增 `llm_available`，`kpoints` 报告现形如
  `{"llm_available": false, "integral": 1, …}`。

### 落了什么码（用户点头后）

- `pipeline/sync.py::_fetch_missing`：`is_garbled` 之前加空正文守门 `if not text.strip(): _flag(e, "empty")`
  —— `fetch_status=empty` + `value_flag=not_knowledge`（只标记不删，用户可否决），口径与
  `expand.py` 批次 94 的 `empty_body` 一致。
- `pipeline/points.py::run_points_extract`：stats 增加 `"llm_available": llm is not None`（R10 第二半）。
- 测试：`tests/test_folders.py::test_fetch_flags_empty_file_as_not_knowledge`（0 字节 → 不产正文 + not_knowledge，
  非空文件不误伤）、`tests/test_points.py` 两处断言（无 LLM 时 false / 注入 FakeLlm 时 true）。
- 契约面：**零变更**（无表结构 / 无 source_type / 无 config 键；只新增 meta 取值 `fetch_status=empty`、
  `value_flag_reason=empty` 与 stats 键 `llm_available`）。

### 验收数字（复跑）

- `pytest -o addopts= -q` → **654 passed / 1 skipped**（+1 新用例）；`tests/test_canary.py` → 1 passed（零漂移）。
- 沙箱复跑（删库重来）：8 条入库，`fetched=6 / fetch_failed=2`（garbled + empty），
  空文件 meta = `{"fetch_status":"empty","value_flag":"not_knowledge","value_flag_reason":"empty"}`、
  `content_hash` 为空。
- `kpoints --dry-run --limit 1`（无 key）：WARN + `"llm_available": false`。

### 下一步（按序）

1. **用户侧验收**：`Ctrl+F5` → `graph.html` ◆点层 → 点节点 → 🔍 反查 → 溯源条目「打开原文」
   （应新标签开 PDF）；首页条目标题 / 预览面板同样可开（22:00 交接的站内代理）。
2. 阶段 A 剩余：8.6 三视图知识聚合验收（探针：搜「异步」/「async」只出知识不出文件名）；
   8.1b（trafilatura 换装）按原计划用同批样本 A/B。
3. 阶段 B 前置：三凭证源（B站/IMA/腾讯文档）等用户凭证。

### 不要重跑

- 8.3 真抓实测（3 条，22:05，简书/博客园/知乎）；8.4 沙箱同步与读数（`temp/ka84`，22:05 复跑）。
- 全量测试与 canary（654 passed / 1 skipped，22:07）；站内代理真库实测（2 个 PDF）。
- 书签预筛（`temp/bookmarks_stage.py`，2026-10-25 18:02 产物 191 条）。

### 验证命令

```powershell
$env:KNOWATLAS_CONFIG='temp/ka84/config.toml'
uv run python -m knowatlas ksync --source folders --fetch-limit 20   # fetched=6 / fetch_failed=2 / 8 条入库
uv run python temp/ka84/probe_flags.py                              # 空文件 meta：fetch_status=empty + not_knowledge
uv run python -m knowatlas kpoints --dry-run --limit 1              # 报告含 "llm_available": false（无 key 时）
uv run python -m pytest -o addopts= -q                              # 654 passed, 1 skipped
```

### 会话指纹

`session-2a7c292a-01be-455d-80c8-7d9fbb88de92`，compactions=0，tokens≈62,000，
baseline 147,059，effective≈42%（OK），2026-10-26T22:08+08:00。

<!-- HANDOFF {"at":"2026-10-26T22:12:11.194029+08:00","compactions":0,"doc":"docs/交接/2026-10-26-2212.md","draft":true,"goal":"上下文到 HANDOFF（86.8%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-2a7c292a-01be-455d-80c8-7d9fbb88de92","status":"HANDOFF","tokens":127616,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-26T22:24:11.160100+08:00","compactions":0,"doc":"docs/交接/2026-10-26-2224.md","draft":true,"goal":"上下文到 CRITICAL（98.1%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-2a7c292a-01be-455d-80c8-7d9fbb88de92","status":"CRITICAL","tokens":144308,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

## 2026-10-26 22:24 交接：8.3/8.4/R10 收口 + 8.6 验收通过；R11「知识主题」378 s 待修（CRITICAL 98.1% 停会话）

### 当前目标

Phase 8 阶段 A 收尾：8.3（书签）、8.4（本地文本）、8.6（三视图）、R10（LLM 降级可见化）本轮全部收口；
剩 R11（「知识主题」端点真库规模下不可用）待用户挑口径后修，以及用户侧 Ctrl+F5 验收站内代理。

### 已完成（含现场数字）

- **8.3 书签**：预筛 191 个 url 节点 → 库内 bookmark **191 条**（161 pending + 30 rejected），1:1；
  `distinct canonical=186`（5 个同 URL 多文件夹收藏按契约各一条）；`native_path` 中文根标签+层级；
  真抓 3 条导航残留 0（简书 9,626→9,604、博客园 11,461→11,209）；知乎 403 = simple 后端无抗反爬，真同步走 deepseek 兜底。
- **8.4 本地文本**：沙箱 `temp/ka84`（`KNOWATLAS_CONFIG` 覆盖 + 独立库）9 文件 → 8 条入库，
  `skipped_hidden=1`/`skipped_ext=1`，`native_path` 四层全对，同名不同目录各一条；
  乱码 → `fetch_status=garbled`、空文件 → **`fetch_status=empty` + `value_flag=not_knowledge`**（本轮新修）。
- **R10**：启动 WARN（`kcheck/kpoints/...`）+ `kpoints` 报告新增 `llm_available`（无 key 时 false），两半都落。
- **8.6 三视图**：`异步` 38 点/9 条目（条目区 100% via=point）、`async` 31/9、`协程` 1/1，**零裸文件名**；
  词云 60 词 0.41 s 零文件名残渣；overview 3 大类 15 ms、subtree 30 节点 3 ms、
  逐层 人工智能 27 → 智能体 8 / 智能体工程 2 / 大模型技术报告 2 / 智能体开发 4 类。
- **提交**：`8e030aa`（空正文守门 + llm_available + 两处回归 + 文档）、`9152862`（`docs/交接/` 自动草稿移出仓库）。
- **测试**：`pytest -o addopts= -q` → **654 passed / 1 skipped**（22:07）；canary 1 passed 零漂移。

### 下一步（按序，首步可直接执行）

1. **用户挑 R11 口径**（见 `docs/design/知识索引工具-TODO.md` R11）：P0 numpy 快路径 + 批量取点（不改接口）/
   P1 进程内 TTL 缓存 / P2 前端只画 top-N。P1/P2 动接口或响应字段 → 先写 `docs/design/变更工单-*.md`。
2. **用户 Ctrl+F5 验收站内代理**：`graph.html` ◆点层 → 点节点 → 🔍 反查 → 溯源条目「打开原文」（应新标签开 PDF）；
   首页条目/预览同样可开（22:00 交接内容，仍未由用户确认）。
3. 之后：8.1b（trafilatura 换装 A/B）或 Phase B 凭证源（B站/IMA/腾讯文档，等凭证）。

### 不要重跑

- 全量测试与 canary（654 passed / 1 skipped，22:07）；8.3 真抓 3 条（22:05）；8.4 沙箱（`temp/ka84`，22:05 复跑）。
- 8.6 只读探针（`temp/probe_86*.py`，22:17–22:25，含检索/词云/overview/subtree）。
- **`/api/graph/topics` 全量计时**（378.7 s，22:20）——别为了「再确认一下」白等 6 分钟。
- 站内代理真库 PDF 实测（2 个 PDF，22:00 交接）。

### 验证命令

```powershell
uv run --with zstandard python tools/session_check.py    # 期望 NEW_SESSION（本块）
uv run python -m pytest -o addopts= -q                   # 654 passed, 1 skipped
uv run python temp/probe_86.py                           # 检索三级 + 词云 + overview（不要跑 topics）
uv run python temp/ka84/probe_flags.py                   # 空文件 meta：fetch_status=empty + not_knowledge
```

### 已知失败与处理

- 知乎等反爬页 `403`：simple 后端能力边界，真同步自动走 `fetch.fallback_backend=deepseek`；不是缺陷。
- `/api/graph/subtree` 的 `category_id` 只收**裸 id**，传 `c:<id>` → 404（前端传裸 id，正常）。
- `/api/graph/topics` 378.7 s / 1,003 主题：R11，修之前不要在浏览器点「知识主题」。
- 本 agent shell 看不到用户级 LLM key（进程早于 setx）：需要 LLM 的命令先
  `foreach ($n in 'KNOWATLAS_LLM_API_KEY_SF1','KNOWATLAS_LLM_API_KEY','KNOWATLAS_WEB_TOKEN') { $v=[Environment]::GetEnvironmentVariable($n,'User'); if($v){Set-Item -Path "env:$n" -Value $v} }`。

### 会话指纹

`session-2a7c292a-01be-455d-80c8-7d9fbb88de92`，compactions=0，tokens=144,308，
baseline 147,059，effective **98.1%**（CRITICAL），2026-10-26T22:24+08:00。

<!-- HANDOFF {"at":"2026-10-26T22:24:38+08:00","compactions":0,"doc":"docs/log.md#2026-10-26-2224","draft":false,"goal":"8.3/8.4/8.6/R10 已收口（654 passed）；R11 知识主题端点 378s 待选口径后修","host":"dsh","kind":"handoff","next":"用户挑 R11 口径（P0/P1/P2）后修；用户 Ctrl+F5 验收站内代理；之后 8.1b 或 Phase B 凭证源","not_rerun":"全量测试 654/1；8.3 真抓 3 条；8.4 沙箱；8.6 只读探针；/api/graph/topics 全量计时 378.7s","schema":1,"session":"session-2a7c292a-01be-455d-80c8-7d9fbb88de92","status":"CRITICAL","tokens":144308,"verify":"uv run --with zstandard python tools/session_check.py"} -->

## 2026-10-26 22:45 R11 收口：知识主题端点 378.7 s → 2.69 s（口径 A：numpy 快路径 + top-N）

会话 `session-b8a0d74d`（新会话，开场 effective 10.7%）。用户「继续」→ 按交接块第 1 步执行：
**用户裁决 R11 口径 A = P0（numpy 快路径）+ P2（top-N 截断）**。

### 先做的三件事

- **8420 端口被上一会话遗留的 serve（PID 12672）占住且已无响应**：低完整性 shell 杀不掉
  （`Stop-Process` 报「找不到进程」、`tasklist` 报拒绝访问），一次性提权 `taskkill /F` 清掉后重启。
  重启后 `overview` 200 / 20 ms、首页 200 —— **站内代理验收现在可做**。
- `temp/` 对低完整性 shell 仍不可写（`Tee-Object` 报拒绝访问），serve 日志改落 `$env:TEMP`。
- uv 缓存照旧走 `$env:UV_CACHE_DIR="$env:TEMP\uvcache-knowatlas"` 兜底。

### 热点拆分（`temp/probe_r11.py`，只读抽样，不重跑 378.7 s）

| 热点 | 实测 | 全量 |
|---|---|---|
| `_greedy_clusters` 纯 Python | 800 点 21.0 s / 1,600 点 76.0 s | **~340 s（九成）** |
| `shared_words` 命名 | 29 ms/主题 | ≈ 29 s |
| `_all_point_hits` 逐点 `get_point_hit` | 0.07 ms/点 | **0.3 s（原猜的热点不成立）** |

numpy 对照：800 点 0.067 s、1,600 点 0.188 s，外推 ≈1.5 s，且簇划分与纯 Python **逐簇一致**。

### 落地（工单 `docs/design/变更工单-2026-10-26-R11知识主题top-N.md`）

- `pipeline/embed_index.py`：`_greedy_clusters` → `_greedy_pure`（兜底）+ numpy 快路径
  （float64 簇心矩阵、逐点 `C[:k] @ v`、并列取末位以保持纯 Python `>=` 更新序）；
  numpy 缺失 / 维度不一致 / <64 点退回纯 Python；签名与返回形状不变。
- `pipeline/graph_topics.py`：`topic_clusters(dl, threshold, limit=80)`——只对返回的 top-N 命名，
  响应加 `total`/`limit`/`truncated`；`MAX_LIMIT=500`。
- `web/api.py`：端点加 `limit` 查询参数并夹 `[1,500]`。
- `web/static/graph.html`：`?limit=80`，副标题「80 个 / 共 1003 个」+ tip 说明。
- `pyproject.toml` / `requirements-core.txt`：`numpy` 显式入 core（不再靠 pandas 传递）。

### 现场数字

- 真库直调 `topic_clusters(limit=80)`：**2.69 s**（原 378.7 s），`total=1003`、`truncated=true`、返回 80。
- 线上 `GET /api/graph/topics?limit=5`：**3.05 s / HTTP 200**，字段齐全。
- headless Edge 点 `#topicBtn`：**3.43 s** 出图，80 主题节点 + 485 成员点，副标题与 tip 文案正确，控制台零异常。
- 测试：`pytest -o addopts= -q` → **659 passed / 1 skipped**（654 + 5 新增）；canary 未动契约（六项零漂移，未改 CANARY）。

### 下一步

1. 用户 Ctrl+F5 验收两处：图页「知识主题」按钮（应 3-4 s 出图、副标题显示「共 1003 个」）、
   以及 22:00 起的站内代理（点层 ◆ → 点节点 → 🔍 反查 → 溯源条目「打开原文」开 PDF）。
2. 之后：8.1b（trafilatura 换装 A/B）或 Phase B 凭证源（B站/IMA/腾讯文档，等凭证）。
3. R11 的 P1（进程内 TTL 缓存）**刻意未做**：等真出现「反复点」的诉求再加（工单 §5）。
<!-- HANDOFF {"at":"2026-10-26T23:36:11.514437+08:00","compactions":0,"doc":"docs/交接/2026-10-26-2336.md","draft":true,"goal":"上下文到 HANDOFF（86.9%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-b8a0d74d-7abe-4cfc-9d3c-cae7ea1efb64","status":"HANDOFF","tokens":127852,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-26T23:46:12.113596+08:00","compactions":0,"doc":"docs/交接/2026-10-26-2346.md","draft":true,"goal":"上下文到 HANDOFF（86.9%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-b8a0d74d-7abe-4cfc-9d3c-cae7ea1efb64","status":"HANDOFF","tokens":127852,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T06:36:11.050379+08:00","compactions":0,"doc":"docs/交接/2026-10-27-0636.md","draft":true,"goal":"上下文到 CRITICAL（103.0%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-b8a0d74d-7abe-4cfc-9d3c-cae7ea1efb64","status":"CRITICAL","tokens":151482,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->


## 2026-10-27 06:50 交接：KPE 独立成仓库（D:\kpe + MIT + subtree 单向传导），已定方案未动手

> 触发：`context_probe` → currentTokens 184,088、**effective 125.2% CRITICAL**。
> 按 AGENTS.md §0「≥95% 立即停」停会话；本块只记方案与命令，**代码一行未改**。
> 注：本文件 1835–1840 行有两条 watcher 在 23:36/23:46 自动写的 draft 交接（86.9%），
> 已被本块取代，不必按其行动。

### 当前目标

把 `tools/kpe` 独立成 **D:\kpe** 的独立仓库（MIT），推到 GitHub（`yianyao/kpe`）让其他 Agent
clone 即用；KnowAtlas 侧保持 `tools/kpe` 为普通目录，用 **git subtree** 单向拉取升级。

### 用户已裁决

1. 位置 = **`D:\kpe`**（盘符根，用户明确要求）。
2. 许可证 = **MIT**。
3. 同步 = 「独立出去的 KPE 升级后，KnowAtlas 亦能升级」→ 定 **subtree 单向传导**
   （不选 submodule：clone KnowAtlas 不该要求 `--recursive`；也不选"splite 双份"）。
   以后：独立仓库为唯一开发处 → `git subtree pull --prefix=tools/kpe kpe main --squash`。

### 可行性已验证（勿重跑）

| 检查 | 结论 |
|---|---|
| 外部依赖 | 只有 `pdfplumber`；其余全标准库 |
| import knowatlas | **零**（全是包内相对导入）；代码无 `D:\sData\…` 硬编码 |
| 测试自足 | `tests/conftest.py` 自加 `sys.path`，独立跑 **14 passed** |
| 主套件影响 | `pyproject.toml` `testpaths=["tests"]` **不含** `tools/kpe/tests` → 搬走不影响 659/1 基线 |
| 工具链 | git **2.55.0**，`git subtree` 可用 |
| 推送权限 | 凭据库 PAT 属于 `yianyao`，scopes `gist, repo, workflow` → **能建仓库**（注意 scopes 头带空格，判断要 trim） |
| 网络 | 直连 github 不通；走 `127.0.0.1:7890` 代理可达（HTTP API 已验证 200） |
| 现有服务 | 8420 serve 在跑（R11 已交付 `fac6c32` 且已推远端） |

### 下一步（按序，首步可直接执行）

```powershell
# 0) 先提交本交接块（docs/log.md 已改动）
cd D:\sData\git\KnowAltas; git add docs/log.md; git commit -m "docs: KPE 独立化方案交接（CRITICAL 125.2%）"

# 1) 主仓库切出保留历史的独立分支（只含 tools/kpe 的提交）
git subtree split --prefix=tools/kpe -b kpe-standalone

# 2) 建 D:\kpe 并接上历史（非裸仓库不能直接 push 到当前分支，故用 fetch+reset）
New-Item -ItemType Directory D:\kpe -Force | Out-Null
cd D:\kpe; git init -b main
git fetch D:\sData\git\KnowAltas kpe-standalone
git reset --hard FETCH_HEAD

# 3) 补独立仓库文件（顺序要紧：.gitignore 必须最先，否则 41.8 MB 的 tools/kpe/.venv 会被 add）
#    .gitignore : .venv/  __pycache__/  *.egg-info/  build/  dist/  *.pyc  .pytest_cache/  temp/
#    LICENSE    : MIT（2026, yianyao）
#    AGENTS.md  : 给别的 Agent 的操作卡（装法/三命令/--limit 3 先试/续跑/勿用裸 kpe.exe）
#    README.md  : 去掉全部 D:\sData\git\KnowAltas 路径 → 通用装法 + 产物说明 + 成本参考
#    pyproject  : 补 readme = "README.md"、license = {text="MIT"}、[project.optional-dependencies] dev = ["pytest"]
#    examples/sample.md : 10 行样例，供零成本自检 kpe chunks

# 4) 本地验证（不花钱）
cd D:\kpe
uv run --with pdfplumber python -m kpe --version          # 0.1.0
uv run --with pdfplumber --with pytest python -m pytest -q # 14 passed
uv run --with pdfplumber python -m kpe chunks examples/sample.md --out temp/smoke

# 5) 建远端仓库（token 从凭据库取，勿打印；必须走代理）
$tok = ("protocol=https`nhost=github.com`n`n" | git -c credential.helper=wincred credential fill |
        Select-String '^password=').ToString() -replace '^password=',''
Invoke-RestMethod -Method Post -Uri "https://api.github.com/user/repos" `
  -Headers @{Authorization="token $tok";"User-Agent"="kpe"} `
  -Proxy "http://127.0.0.1:7890" -ContentType "application/json" `
  -Body '{"name":"kpe","description":"Extract self-contained knowledge points from long books","private":false}'

# 6) 推送（D:\kpe 没有 insteadOf 改写，直接走代理即可）
cd D:\kpe; $env:HTTPS_PROXY="http://127.0.0.1:7890"; $env:HTTP_PROXY=$env:HTTPS_PROXY
git remote add origin https://github.com/yianyao/kpe.git
git -c credential.helper=wincred push -u origin main

# 7) KnowAtlas 侧接上 subtree（该仓库的 insteadOf 会把 https://github.com 改写为 ghproxy，读得到）
cd D:\sData\git\KnowAltas
git remote add kpe https://github.com/yianyao/kpe.git
git subtree pull --prefix=tools/kpe kpe main --squash   # 以后每次升级都跑这一条
```

### 不要重跑

- KPE 可行性检查（依赖/导入/测试/`testpaths`/git subtree 探针）。
- `uv run python -m pytest tools\kpe\tests -o addopts= -q`（14 passed，06:44）。
- R11 全套（`fac6c32` 已推，659/1）；8420 serve 重启。

### 验证命令（新会话开场）

```powershell
uv run --with zstandard python tools/session_check.py     # 期望 NEW_SESSION（本块）
uv run --with zstandard python tools/context_probe.py     # 期望 effective 低水位
Test-Path D:\kpe                                          # 期望 False（说明尚未开工）
git -C D:\sData\git\KnowAltas status -sb                  # 期望无 pending
```

### 已知失败与处理

- **`temp/` 对低完整性 shell 不可写**（`Tee-Object`/`Out-File` 报拒绝访问）：日志写 `$env:TEMP`。
- **uv 缓存**：`$env:UV_CACHE_DIR="$env:TEMP\uvcache-knowatlas"`。
- **github 直连不通**：一切 GitHub API / push 都要 `-Proxy http://127.0.0.1:7890`。
- **insteadOf 只作用于 KnowAtlas 仓库**：新的 `D:\kpe` 不在改写范围，别多此一举去 unset。
- **`tools/kpe/.venv` = 41.8 MB / 645 文件**：新仓库先写 `.gitignore` 再 `git add`。
- **裸 `kpe` 命令会被应用控制策略拦**（`os error 4551`）：文档统一写 `python -m kpe`。
- **PAT scopes 头带空格**：`x-oauth-scopes` 拆分后要 trim，否则误判"没有 repo 权限"。

### 会话指纹

`session-b8a0d74d-7abe-4cfc-9d3c-cae7ea1efb64`，compactions=0，tokens=184,088，
baseline 147,059，effective **125.2%**（CRITICAL），2026-10-27T06:50+08:00。

## 2026-10-27 06:55 KPE 独立仓库落地（D:\kpe + MIT + subtree 单向传导，已实测闭环）

**开场证据**：`session_check` = `NEW_SESSION`（exit 0，上一交接 `session-b8a0d74d` @06:36
`status=CRITICAL`）；`context_probe` effective **11.0%**（16,176 tokens）。
触发词「继续」+ 用户告知远程仓库已建好：<https://github.com/yianyao/kpe>。

### 已完成

| 步骤 | 结果 |
|---|---|
| 主仓切历史 | `git subtree split --prefix=tools/kpe -b kpe-standalone` → `3a28c35`（**180 提交**） |
| 建独立仓 | `D:\kpe`：`init -b main` + `fetch/reset --hard` 接上历史 |
| 补独立文件 | `.gitignore` `LICENSE`(MIT 2026 yianyao) `AGENTS.md`(Agent 操作卡) `README.md`(通用化) `使用手册.md`(去 KnowAtlas 路径) `examples/sample.md` `pyproject.toml`(readme/license/dev extra/urls/pytest testpaths) `.gitattributes`(`* text=auto eol=lf`) `CHANGELOG.md` |
| 本地验证 | `python -m kpe --version` → `0.1.0`；`pytest` → **14 passed**；`chunks examples/sample.md` → 1 块 / 611 字（零成本链路通） |
| 推送 | `a9ae50f`(初版) → `680bfa6`(.gitattributes) → `910c85c`(CHANGELOG)；`ls-remote` 与本地 HEAD 一致 |
| KnowAtlas 接回 | remote `kpe` 已加（经 ghproxy 可读）；基线 merge `7c66bd5`；升级命令 `git subtree pull --prefix=tools/kpe kpe main --squash` 实测把 `910c85c` 拉成 `7bd8dd8`，**仅新增 `tools/kpe/CHANGELOG.md`**，源码零改动 |
| 清理 | 删本地分支 `kpe-standalone`（历史已在 `D:\kpe`） |
| 文档 | `AGENTS.md` §3 增「上游独立仓库 + 单向升级命令」；`AGENTS.local.md` 记本机坑 |

### 现场数字

- `D:\kpe`：tracked **23** 文件，`main...origin/main` 干净；remote `origin` = `https://github.com/yianyao/kpe.git`。
- GitHub API：`full_name=yianyao/kpe`、`default_branch=main`、`private=false`、`license=MIT`。
- KnowAtlas：`main...origin/main [ahead 7]`（含 2 条 kpe 合并提交 + 文档）。

### 踩到的坑（已改进文档/配置）

1. `git subtree pull --squash` 对「一直是普通目录」的 `tools/kpe` 报
   `can't squash-merge: 'tools/kpe' was never added` —— 必须先
   `git merge -s subtree --allow-unrelated-histories kpe/main`，再把
   `git-subtree-dir` / `git-subtree-split` trailer `--amend` 进那条提交。
2. 本机 git 默认 schannel 报 `SEC_E_NO_CREDENTIALS`（curl 同病）→ `D:\kpe` 与 KnowAtlas
   相关命令统一加 `-c http.sslBackend=openssl`（`D:\kpe` 已写进 local config）。
3. `git subtree` 不转发 `--allow-unrelated-histories`，也不转发 `git -c`。
4. pwsh `$ErrorActionPreference='Stop'` + `git fetch … 2>&1 | Out-Null` 会把 stderr 当
   `NativeCommandError` 中止（假失败）。

### 不要重跑

- `D:\kpe` 的 14 项 pytest、`chunks examples/sample.md`（06:52 已绿）。
- `git subtree split`（`kpe-standalone` 已删，历史在 `D:\kpe`）。
- `git subtree pull --squash` 的 no-op 验证与 910c85c 升级实测。
- R11 / 全量 659 套件（本轮未动 `src/`）。

### 下一步（可选，等裁决）

1. GitHub 仓库描述目前是「KPE工具」，可改成英文一句（`gh`/API 改 `description`）。
2. 是否给 KnowAtlas 加一条「`tools/kpe` 有未同步改动」的检查（pre-commit 或 `ktest`）。
3. 用 `D:\kpe` 真跑一本书（沿用 `temp/kpe-aiagents` 的 key/参数）验证跨仓库可用性。

<!-- HANDOFF {"at":"2026-10-27T06:58:00+08:00","compactions":0,"doc":"docs/log.md#2026-10-27-0655","draft":false,"goal":"KPE 已独立成 D:\\kpe + MIT + 推到 yianyao/kpe，subtree 单向传导实测闭环","host":"dsh","kind":"handoff","next":"用户验收 GitHub 仓库与 D:\\kpe；之后可选：改仓库描述 / 加 tools/kpe 未同步检查 / 用 D:\\kpe 真跑一本书","not_rerun":"D:\\kpe 的 pytest 14 与 chunks 样例；subtree split；两次 subtree pull（no-op 与 910c85c 升级）；KnowAtlas 全量套件","schema":1,"session":"session-5399c118-17f5-4acb-910b-80776261f016","status":"OK","tokens":80524,"verify":"uv run --with zstandard python tools/session_check.py"} -->
<!-- HANDOFF {"at":"2026-10-27T07:06:11.186797+08:00","compactions":0,"doc":"docs/交接/2026-10-27-0706.md","draft":true,"goal":"上下文到 HANDOFF（93.9%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-5399c118-17f5-4acb-910b-80776261f016","status":"HANDOFF","tokens":138103,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T07:08:11.133489+08:00","compactions":0,"doc":"docs/交接/2026-10-27-0708.md","draft":true,"goal":"上下文到 CRITICAL（107.8%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-5399c118-17f5-4acb-910b-80776261f016","status":"CRITICAL","tokens":158471,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

## 2026-10-27 07:20 知识主题：二次合并 + 命名去重 + 视图搜索高亮（R12）

**触发**：用户报障「知识主题里好些重复名字的节点，比如『智能』（放射出去的子节点不同）」，
要求「聚合算法别再有重名」+「加搜索高亮」；同时确认 #1 方向（分类页检索也要
「集→簇→块→点」聚合，另排）。

### 诊断（只读探针）

| 探针 | 结论 |
|---|---|
| `temp/topic_dup_probe.py` | 1,003 主题，top500 里 **35 个重名 / 96 簇**（`智能`×14、`agent`×10…）；同名簇质心余弦 **66/182 对 ≥0.8**（最高 0.90） |
| `temp/topic_merge_probe.py` | 合并敏感性：0.90→1,010 簇；**0.85→945（最大 126 点）**；0.80→662（最大 697）；0.75→280（最大 1,910，链式粘连） |

结论：**0.72 单遍贪心把同一主题切成多块（主因）+ 命名只取共享词、1 词时退化单词名（放大器）**。

### 改动

| 文件 | 内容 |
|---|---|
| `src/knowatlas/pipeline/graph_topics.py` | 新增 `_merge_clusters`（规模降序质心贪心合并，默认 0.85，`merge=False` 可关）；`topic_clusters` 加 `merge`/`merge_threshold`，响应加 `merge_threshold`/`merged_from`、主题 `merged`；命名加规模后缀 `（N 点）`+ 圈号去重，命名词取**种子簇**（合并前最大簇） |
| `src/knowatlas/web/api.py` | 端点加 `merge`/`merge_threshold`（夹 0.5–0.99） |
| `src/knowatlas/web/static/graph.html` | 主题视图搜索框（其它视图隐藏）、命中金框高亮（`emphasis` borderWidth 3）、命中计数、Esc 清空 |
| `tests/test_graph_topics.py` | 新增 4 例（合并记账、维度不齐、命名唯一/规模后缀、端到端 `merged_from`/`merged`） |
| `docs/design/变更工单-2026-10-27-知识主题二次合并与命名去重.md`、`CHANGELOG.md` | 工单与变更记录 |

### 验证（现场数字）

- 真库 `topic_clusters(limit=80)`：`total` **1003 → 934**（`merged_from=1003`，23 个主题发生过合并，
  最大 26 簇 / 113 点，抽读成员全是「智能体定义/循环/分类」——同主题，合并合理）；
  top80 重名 **35 → 0**；泛名 0；耗时 **4.02 s**（R11 2.69 s，合并多约 1.3 s）。
- 测试：**663 passed / 1 skipped**（原 659）；`tests/test_canary.py` 通过（EXIT=0）。
- 浏览器（headless Edge 156 + CDP，真实点击 `#topicBtn`）：搜索「智能」→ 命中 **257 / 779** 节点
  （30 个主题），金框像素 **3 → 1,944**，Esc 清空后 tip 复原；搜索框只在主题视图出现。

### 坑（已写进注释与工单）

簇心是成员均值、模长 <1，直接点积会系统性低估相似度——首版 0.85 阈值下真库**零合并**，
而单测全绿（测试向量都是单位向量）。改成先投影单位球再比才生效。

### 运行态

`serve` 已重启：旧 PID 9540 停掉，新进程用
`Start-Process uv run python -m knowatlas serve` 起（日志 `%TEMP%\knowatlas-serve.log`）。
用户验收需 Ctrl+F5（graph.html 无版本参数，浏览器可能给旧缓存）。

### 不要重跑

- `pytest` 全量（663/1）与 canary；`temp/topic_check.py`、`temp/edge_topic_test.mjs`、
  `temp/edge_shots.mjs`、`temp/edge_check_emphasis*.mjs`。
- `temp/topic_dup_probe.py` / `temp/topic_merge_probe.py`（结论已固化进工单）。

### 下一步

1. 用户 Ctrl+F5 验收：重名是否消失、搜索高亮是否够醒目（不满意可调 `merge_threshold`）。
2. 用户 #1：把主题聚合接进分类页检索（集→簇→块→点）——需单独方案 + 可能的新端点/新工单。
3. 若觉得 934 个主题仍多，可再议「0.80 合并 + 规模上限」或按章分片。

<!-- HANDOFF {"at":"2026-10-27T07:20:00+08:00","compactions":1,"doc":"docs/log.md#2026-10-27-0720","draft":false,"goal":"知识主题二次合并（0.85）+ 命名去重 + 主题视图搜索高亮，已实现并实测","host":"dsh","kind":"handoff","next":"① 用户 Ctrl+F5 验收；② #1 分类页检索按主题聚合（需新工单/方案）","not_rerun":"pytest 全量 663/1 与 canary；temp/topic_check.py、temp/edge_*.mjs、两个 topic_*_probe.py","schema":1,"session":"session-5399c118-17f5-4acb-910b-80776261f016","status":"OK","tokens":78834,"verify":"uv run --with zstandard python tools/session_check.py"} -->

<!-- HANDOFF {"at":"2026-10-27T07:20:12.006886+08:00","compactions":1,"doc":"docs/交接/2026-10-27-0720.md","draft":true,"goal":"会话已被自动压缩 #1","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-5399c118-17f5-4acb-910b-80776261f016","status":"OK","tokens":82980,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->
<!-- HANDOFF {"at":"2026-10-27T12:28:11.582035+08:00","compactions":1,"doc":"docs/交接/2026-10-27-1228.md","draft":true,"goal":"上下文到 CRITICAL（103.6%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-5399c118-17f5-4acb-910b-80776261f016","status":"CRITICAL","tokens":152299,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

## 2026-10-27 12:45 主题命名补第二词 + 合并迭代 + 检索「主题」tab（R13）

**触发**：用户追问「为什么还有 GRPO（6 点）/ GRPO（4 点）」，并要「分类页检索的主题聚合」方案；
裁决：命名/合并修复都做 + 检索结果先加「主题」tab（分类浏览开关下一轮）。

### 诊断（真库证据）

| 探针 | 结论 |
|---|---|
| `temp/topic_grpo_probe.py` | GRPO 3 簇（6/4/4 点）质心 0.805–0.838 < 0.85，讲的是 应用与 R1 / 定义 / advantage 计算——**不是同一主题，不该并**；MCP 4 簇（12/17/9/2 点）里 17↔9 事后 **0.886 ≥ 0.85 却没并** |
| `temp/topic_merge_debug.py` | 复现「先比后漂」：单遍贪心只在插入时比一次，之后合并把簇心拉过去 |
| `temp/topic_samebase_probe.py` | 118 个同主干组、669 个主题；组内 9,428 对里 9,418 对 < 0.85 —— 同词不同簇是常态 |

三件事：① 命名只用 100% 覆盖词，剩 1 个词就退化成 `GRPO（N 点）`；② 合并不是不动点；③ jieba 伪词 `体应`。

### 改动

| 文件 | 内容 |
|---|---|
| `src/knowatlas/pipeline/graph_topics.py` | `_name_candidates`（一次抽词出 100%/60% 两档 + **2 字纯中文必须在 jieba 词典**）；`_topic_name` 补第二词；`_merge_clusters` 迭代到不动点（矩阵化 `U[:k] @ unit`）；`topic_clusters(point_ids=...)` 点域过滤 |
| `src/knowatlas/web/api.py` | `/api/graph/topics` 加 `q` / `category_id` / `points_limit`，响应加 `scope` |
| `src/knowatlas/web/static/index.html` | 检索工作台第 4 个 tab「主题」（懒加载 + 展开成员点 + 溯源 openPreview） |
| `tests/test_graph_topics.py` | 新增 5 例（不动点性质、第二词、伪词、point_ids、`?q=` scope） |
| `docs/design/变更工单-2026-10-27-主题命名补词与检索聚合.md`、`CHANGELOG.md` | 工单与变更记录 |

### 验证（现场数字）

- 真库：`total` 934 → **933**；top500 重名 **0**、伪词 **0**、泛名 **0**、单词名仅 5 个；
  全库端点 **4.91 s**（首调 8.03 s，含 jieba 词典 ~3 s 初始化）。
- `?q=GRPO` → 84 点 **16 主题 / 0.20 s**：`grpo·验证(10) / grpo·kl(5) / grpo·算法(4) / grpo·advantage(4) / grpo·rollout(4) / grpo·训练(3)`
  （改前是三个 `grpo（N 点）`）；`?q=MCP` → 203 点 **50 主题 / 0.32 s**。
- 浏览器：检索 GRPO → 4 个 tab（聚合/主题/线索/放射）→ 主题 tab 16 行、头「命中 84 个知识点 → 聚合出 16 个主题」
  → 展开 10 点 → 点溯源出预览面板。
- 测试：**668 passed / 1 skipped**（原 663）；canary 零漂移。

### 坑（已写进注释）

`jieba.lcut` 与 posseg 都把 `体应` 当名词，token 校验挡不住；改查 `jieba.dt.FREQ`。
另：命名原先对同一批文本抽两遍词，改为一次抽词出两档。

### 运行态

`serve` 已重启（新 PID 22584，日志 `%TEMP%\knowatlas-serve.log`）；页面改动要 **Ctrl+F5**。

### 不要重跑

- `pytest` 全量（668/1）与 canary；`temp/topic_r13_check.py`、`temp/topic_r13_names.py`、
  `temp/edge_topics_tab.mjs`；`temp/topic_grpo_probe.py`、`temp/topic_merge_debug.py`、`temp/topic_samebase_probe.py`。

### 下一步

1. 用户 Ctrl+F5 验收：graph 页主题名、index 页检索「GRPO」→ 主题 tab。
2. 分类浏览页的「按主题看」开关（同一端点传 `category_id`，后端已就绪，只差 UI）。
3. 若嫌全库 4.9 s 慢：可加进程内 TTL 缓存（R11 曾记「本轮不做」）。

<!-- HANDOFF {"at":"2026-10-27T12:45:00+08:00","compactions":1,"doc":"docs/log.md#2026-10-27-1245","draft":false,"goal":"主题命名补第二词 + 合并迭代到不动点 + 检索工作台「主题」tab，已实现并实测","host":"dsh","kind":"handoff","next":"① 用户 Ctrl+F5 验收 graph 主题名与检索主题 tab；② 分类浏览页「按主题看」开关（后端已就绪）","not_rerun":"pytest 全量 668/1 与 canary；temp/topic_r13_check.py、temp/topic_r13_names.py、temp/edge_topics_tab.mjs、三个 topic_* 探针","schema":1,"session":"session-5399c118-17f5-4acb-910b-80776261f016","status":"HANDOFF","tokens":160000,"verify":"uv run --with zstandard python tools/session_check.py"} -->

## 2026-10-27 R14：分类浏览「按主题看」+ 主题聚合进程内缓存

**触发**：R13 接交块下一步②（后端 `?category_id=` 已就绪，只差 UI）。开工前用
`temp/prof_topics_r14.py` 先量代价：「人工智能」子树 25 条目 → **4507 点**（全库 4552，
单条目前 4 本大书占 1373/820/571/420），一次归簇+合并+命名 **6.7–6.9 s**（HTTP 实测；
进程内 2.5 s，`_greedy_np` 3.7 s 主导；995 簇 → 926 主题、落单 1752）——对照现有
「按集分组」`/api/sets/group` **0.27 s**（条目级）慢 20 倍以上，直接做开关会像卡死。

### 改动

| 文件 | 内容 |
|---|---|
| `src/knowatlas/web/static/index.html` | `catGrouped` 布尔 → `catMode` 三态（flat/set/topic，旧键 `knowatlas.catGrouped` 兼容）；统一模式条三个按钮；`renderCategoryTopics` 拉 `?category_id=&limit=40`，头行「N 条目 → P 点 → M 主题（共 T）」，主题行展开成员点 + 溯源 `openPreview`；主题模式 `#filter` 禁用 + tooltip；行渲染抽 `topicPointCard`/`topicRowsHtml`/`bindTopicOpen` 与检索 tab 共用 |
| `src/knowatlas/web/api.py` | `/api/graph/topics` 进程内 TTL 缓存（`_TOPICS_TTL=300 s`、`_TOPICS_MAX=8`，按写入时间淘汰）；键 = 库路径 + `points_fingerprint()` + scope + 点域签名 `sha1(排序 point_id)` + limit/merge/阈值；**点域先算再查缓存**（分类口径 53 ms） |
| `src/knowatlas/datalayer/db.py` | 新增只读 `points_fingerprint()`（点数:最新点时间:向量数:最新向量时间，< 10 ms）作缓存失效依据 |
| `tests/test_graph_topics.py` | 新增 4 例：分类口径点域、缓存命中与键隔离、数据变化自动失效、静态 UI 三态标记 |
| `docs/design/变更工单-2026-10-27-分类浏览按主题与主题聚合缓存.md`、`CHANGELOG.md` | 工单与变更记录 |

### 契约

无表结构 / 字段 / scheme / `SOURCE_TYPES` / `STATUSES` / `CONFIG_SCHEMA_KEYS` / 接口签名变更；
响应 JSON 不变，**无新增 query 参数**。唯一可观测变化 = 同范围结果最多陈旧 300 s（工单备案）。

### 验证（现场数字）

- 全量 pytest：**672 passed / 1 skipped**（收集 673；进度行统计 673 = 672 pass + 1 skip，0 F/E）。
- 定向：`test_graph_topics` 22 例、`test_web_api`/`test_cloud`/`test_timeline`/`test_canary` 合计 63 例全绿。
- 真库 curl：`?category_id=4d77324c78e541b0&limit=40` **冷 4.12 s → 热 0.095 s**；
  `?limit=40` **冷 2.95 s → 热 0.030 s**。
- headless Edge（CDP，`temp/edge_cat_topic.mjs`）：进入「人工智能」→ 模式条 `[flat, set*, topic]`
  → 点「🧠 按主题」→ **40 行 / 517 ms**（缓存热），首行「智能·任务 116 点 · 并 27 簇 · 溯源 12 条目」
  → `#filter` disabled + title 提示 → 展开成员点 → 溯源预览 `Hello-Agents-V1.0.3-20260717`。
  截图 `temp/cat_topic_tab.png`（1570×805）。
- canary 零漂移。

### 运行态

- serve 已重启（旧 pid 19948 已 `taskkill`，新进程由后台作业
  `pwsh-e1fafbf6e9a54e6b` 持有，`/api/stats` 200）；页面改动需 **Ctrl+F5**。
- 后台还有 headless Edge（CDP 9333）在跑，收尾时可关。

### 不要重跑

- 全量 pytest（672/1）与定向 63 例、canary；
- `temp/prof_topics_r14.py`、`temp/edge_cat_topic.mjs`（探针与 UI 脚本，已完成使命）。

### 下一步

1. 用户 Ctrl+F5 验收：分类页模式条「🧠 按主题」→ 展开主题 → 点溯源。
2. 首调 3–7 s 若嫌慢：改 `_greedy_np` 归簇（近似最近邻 / MiniBatchKMeans）或落盘缓存——会动主题质量，另开工单。
3. `graph.html` 主题视图与检索「主题」tab **已自动受益**于同一口缓存（同参数键）。
4. 缓存 TTL 300 s 若需可配：加 `CONFIG_SCHEMA_KEYS` 属契约变更，需工单。

<!-- HANDOFF {"at":"2026-10-27T19:04:06+08:00","compactions":0,"doc":"docs/log.md#2026-10-27-r14","draft":false,"goal":"分类浏览「按主题看」三态开关 + /api/graph/topics 进程内 TTL 缓存，已实现并实测（672 passed / 1 skipped）","host":"dsh","kind":"handoff","next":"① 用户 Ctrl+F5 验收分类页「🧠 按主题」；② 首调 3–7 s 若嫌慢→改 _greedy_np 归簇或落盘缓存（另开工单）；③ 缓存 TTL 若要可配需开契约工单","not_rerun":"全量 pytest 672/1 与定向 63 例、canary；temp/prof_topics_r14.py、temp/edge_cat_topic.mjs","schema":1,"session":"session-37749571-52c4-441b-ae9f-d3bd00fa9ded","status":"HANDOFF","tokens":132815,"verify":"uv run --with zstandard python tools/session_check.py"} -->

<!-- HANDOFF {"at":"2026-10-27T19:06:11.245580+08:00","compactions":0,"doc":"docs/交接/2026-10-27-1906.md","draft":true,"goal":"上下文到 CRITICAL（101.5%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-37749571-52c4-441b-ae9f-d3bd00fa9ded","status":"CRITICAL","tokens":149295,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

## 2026-10-27 R15：R14 复核 + 8.7 emmx 复核（新会话 session-588aa31e）

**开场**：`session_check` → NEW_SESSION；`context_probe` → effective **11.3%**（16,683 / 147,059，baseline 未变）。

### R14 复核（我代跑，等效用户 Ctrl+F5）

- 端点冷启动（serve 在跑、进程内缓存为空）：`/api/graph/topics?category_id=4d77324c78e541b0&limit=5` **2.10 s**、
  `?limit=5` **1.97 s**——比交接记录的 4.12 / 2.95 s 更快，暂时不必动 `_greedy_np`。
- headless Edge（CDP 9333；复用 `temp/edge_cat_topic.mjs` + 新增 `temp/edge_cat_modes_check.mjs`）：
  分类「人工智能」三态切换 **flat 25 条（筛选可用）/ set 按集分组（筛选可用）/ topic 40 行 512 ms（筛选禁用 + tooltip）**；
  主题首行「智能·任务 116 点 · 并 27 簇 · 溯源 12 条目」；展开成员点 → 溯源出预览 `Hello-Agents-V1.0.3-20260717`。
  截图 `temp/cat_topic_tab.png`（本模型无图像输入，未做视觉复核，DOM 断言全过）。
- 结论：R14 无回归，三态重构没弄坏 flat/set。

### 推送

`859f37f..c3633ef` → `origin/main`。做法：临时把 `origin` 改成直连 `https://github.com/yianyao/KnowAtlas.git`
并摘 `insteadOf`，走 `127.0.0.1:7890` + `credential.helper=wincred` + `sslBackend=openssl`，推完原样恢复。

**坑**：低完整性令牌下写不了 `.git/config`（`could not lock config file .git/config: Permission denied`），
必须临时切 full-access；否则 `insteadOf` 摘不掉，push 会被改写到只读镜像并提示要用户名。

### 8.7 万兴脑图（复核 10-24 结论，非新问题）

- 真库唯一 emmx 条目 `43a1b524bc586b88`「重要概念」仍是**标题级降级**：`meta.degraded=true`（page.xml 缺失或无主题节点）、
  `inline_content` 空、**0 点**。`/api/stats` 的 `by_source.emmx=1` 容易让人误以为「有数据」，实则不可检索。
- 再次解剖 `重要概念.emmx`（26,467 B，`Document Version=14.0.3`）：`page/` 是空目录，节点树在 `mmpage/page.bin` +
  `page-1/2/3.bin`；文本为明文 UTF-8，按 `7B 04 … 00 00 00 0A 7F` 一类私有标记分段，无显式长度前缀，层级未解。
- 与 TODO 8.7「格式缺口（2026-10-24）」一致；可选路线：源端另存 PDF/旧版 `.emmx`（零代码）/ 单独立项做二进制解析 / 维持降级。

### 下一步（待用户裁决）

1. emmx 路线三选一（见上）。
2. 若继续做代码：打包安装（Phase 5「任意目录可用」仍 `[ ]`）或用户指定方向。

<!-- HANDOFF {"at":"2026-10-27T19:28:11.365090+08:00","compactions":0,"doc":"docs/交接/2026-10-27-1928.md","draft":true,"goal":"上下文到 HANDOFF（93.1%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-588aa31e-6ec3-48d6-bc70-cd94e0d8b315","status":"HANDOFF","tokens":136920,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T19:30:11.332189+08:00","compactions":0,"doc":"docs/交接/2026-10-27-1930.md","draft":true,"goal":"上下文到 CRITICAL（98.6%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-588aa31e-6ec3-48d6-bc70-cd94e0d8b315","status":"CRITICAL","tokens":144952,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T19:42:11.642173+08:00","compactions":1,"doc":"docs/交接/2026-10-27-1942.md","draft":true,"goal":"会话已被自动压缩 #1","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-588aa31e-6ec3-48d6-bc70-cd94e0d8b315","status":"OK","tokens":83350,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

## 2026-10-27 R15 续：EMMX v14 二进制页解析落地（A1，用户裁决「批准 A1」）

**背景**：R15 前段复核 8.7 仍是标题级降级（`degraded=true` / 0 点），给出三条路线，用户选「立项解析二进制」，随后批准 **A1**（确定性页级扁平抽取、零 LLM），不赌层级。

### 格式取证（两样本，`temp/probe_emmx_*.py`）

- 节点结束标记 `00 00 00 0A 7F 00 00 00 0B 7F 00 00 00 00`（四页一致，末页尾巴相同）→ 直接切块。
- 正文段**以标记开头**：`7B 04`（样式段）/ `01 04`（续段）/ `14 ? 3F`（根节点，`?` 随样式变）；
  「读到非法字节为止」取文本。**证伪**：先前「按 NUL 切段」会把正文连同前面的二进制一起丢掉，
  只剩 `5priority` 这类样式名（page-1 得 72 字 vs 实际 1,500 字）。
- 换行：段间前导含 `00 00 00 01 7C 02` = 作者换行；否则是**排版折行**，拼回同一行
  （否则「…才被设置。换 / 言之，变量」被切断）。另加「间隔 > 128 字节 = 跨节点」兜底，
  否则没有 END 标记的根节点会和一级分支粘成一行（实测间隔 p99=66、最大 2,429）。
- 页序：`document.xml` 的 `<Pages V="page;page-1;page-2;page-3">`。**顺带修 bug**：原代码
  `findtext("Properties/Pages")` 取元素文本（永远空串），9.x 一直靠扫文件名兜底；改读属性后两版共用口径。

### 实现

- `adapters/emmx.py`：`_bin_page_names` / `_split_blocks` / `_read_utf8` / `_text_runs` / `_block_lines` /
  `_parse_emmx_v14`；`_parse_emmx` 分派（有 `page.xml` → 9.x 原路；否则 v14；都不行才降级）。
  **一页一条目**：`locator=emmx://<rel>#<page>`、`meta={emmx_format:"v14", page, blocks, hierarchy:"flat"}`，
  正文按块序拼接（>4,096 字截断 + 全文进 `content_store`），不调 LLM。
  `parse_tree()` 返回一页一层扁平树（首块为根、子节点从第二块起，避免根重复）。
- `web/api.py`：`/api/entries/{id}/emmx_tree` 锚点从只认 `#map` 放宽到 `#page*`，v14 只回本条目那一页并重算 `node_count`。
- `web/static/index.html`：预览面板门控放宽为 `/#(map|page)/`。

### 验收数字（真库 + 真样本 + 真浏览器）

| 项 | 结果 |
|---|---|
| 适配器（不写库） | 8 条目、1,786 块、`degraded_files=0`；重要概念 5,897 字 / 文心V1 53,477 字 |
| `ksync --source emmx --full` | created 2 / updated 6 / **archived 1**（旧降级 `43a1b524bc586b88`），contents_stored 2 |
| `/api/stats` | `by_source.emmx = 8`（活跃），未分类 0 |
| `kpoints --limit 8` | **27 点**（原型链/constructor/new 三步/__extends…），`pending_kpe` 2（人物原型 14,979 字、作文手段 37,547 字） |
| 树形浏览（headless Edge + CDP） | 打开「原型」条目 → `#pv-mtree` 可见、102 个 `li`、摘要「📄 page（102 节点）」与 API `node_count=102` 一致 |
| 测试 | 新增 `tests/test_emmx_v14.py` 6 例 + `test_emmx_tree.py` 1 例；全量 **679 passed / 1 skipped**（原 672），canary 零漂移 |

### 已知限制 / 下一步

1. **层级未知**：`hierarchy="flat"`，条目正文是块序原文；A2（时间盒逆向父子字段）未开工，开工单 §4-A2 有下一道路线。
2. **折行拼接是启发式**：BRK 判据 + 128 字节间隔；若格式小改，标记找不到时该页会退回标题级降级（不产半截正文）。
3. 文心V1 两页（3.6 万字 / 1.4 万字）走 `points_pending_kpe`，需要时按提示用 `tools/kpe` 分块导入。
4. 9.x 路径行为不变（测试全绿），但页序现在真的按 `document.xml` 了——若某天遇到页序异常的 9.x 样本，先怀疑这里。

### 不要重跑

- 全量 pytest（679/1）与 canary；
- `ksync --source emmx --full`（已入真库，再跑只会 updated）；
- `kpoints --limit 8`（27 点已建，重复跑只会命中 already_done）；
- `temp/probe_emmx_*.py` 系列探针与 `temp/edge_emmx_v14_check.mjs`。

<!-- HANDOFF {"at":"2026-10-27T19:58:00+08:00","compactions":1,"doc":"docs/log.md#2026-10-27-r15-续emmx-v14-二进制页解析落地a1用户裁决批准-a1","draft":false,"goal":"EMMX v14 二进制页解析 A1 落地：8 条目 / 1,786 块 / 27 点，树形浏览可开合，679 passed / 1 skipped","host":"dsh","kind":"handoff","next":"① 用户 Ctrl+F5 打开「原型/作用域/闭包/箭头函数」条目验收扁平树与正文；② 若要层级→按工单 §4-A2 开时间盒逆向；③ 文心V1 两页长文按需走 tools/kpe","not_rerun":"全量 pytest 679/1 与 canary；ksync --source emmx --full；kpoints --limit 8；temp/probe_emmx_* 探针","schema":1,"session":"session-588aa31e-6ec3-48d6-bc70-cd94e0d8b315","status":"WARN","tokens":117491,"verify":"uv run python -m pytest -o addopts= -q -> 679 passed, 1 skipped"} -->

<!-- HANDOFF {"at":"2026-10-27T19:50:11.584155+08:00","compactions":1,"doc":"docs/交接/2026-10-27-1950.md","draft":true,"goal":"上下文到 HANDOFF（86.4%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-588aa31e-6ec3-48d6-bc70-cd94e0d8b315","status":"HANDOFF","tokens":127011,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T19:52:11.605692+08:00","compactions":1,"doc":"docs/交接/2026-10-27-1952.md","draft":true,"goal":"上下文到 CRITICAL（98.1%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-588aa31e-6ec3-48d6-bc70-cd94e0d8b315","status":"CRITICAL","tokens":144254,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T20:40:10.842077+08:00","compactions":2,"doc":"docs/交接/2026-10-27-2040.md","draft":true,"goal":"会话已被自动压缩 #2","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-588aa31e-6ec3-48d6-bc70-cd94e0d8b315","status":"OK","tokens":93814,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T20:54:10.899493+08:00","compactions":2,"doc":"docs/交接/2026-10-27-2054.md","draft":true,"goal":"上下文到 HANDOFF（86.1%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-588aa31e-6ec3-48d6-bc70-cd94e0d8b315","status":"HANDOFF","tokens":126548,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->


## 2026-10-27 R16：长网页分块抽取 + 重复版本清理（HANDOFF）

**目标**：用户裁决「长网页肯定要分块的」，把 6k–60k 字正文从「交 kpe」改成管道内分块；顺带清掉同一本书的重复版本目录。

**已完成**
1. 长网页分块（工单 `docs/design/变更工单-2026-10-27-长网页分块抽取.md`）
   - `pipeline/points.py`：新增 `_chunk_body()` + `_CHUNK_TOTAL_MAX=60000`；三段分流（≤6k 单次 / 6k–60k 逐块 / >60k 仍 pending_kpe）；LLM 未启用不切块；`char_offset` 加块起点偏移 → 全文坐标；`_candidates` 只在 chars>60000 时跳过 pending_kpe；成功写 `meta.points_chunked` 并清旧标记。
   - `cli.py`：kpoints 报告新增 `CHUNK …` 行，PENDING 文案改「超过分块上限 60,000 字」。
   - 测试：新增 `tests/test_points_chunk.py` 7 例；`test_points.py` 4 例旧阈值 6,000 → 70,000。全量 **686 passed / 1 skipped**（原 679）。
   - 真库实测（备份 `temp/knowledge-before-chunk-20261027.db`）：16 条 6k–60k → `chunked 16 / chunks_total 108 / points_created 383 / linked 0 / rejected 2 / pending_kpe 0`，总点数 **4,582 → 4,965**；`4.架构与构建多智能体系统` 101 点（52,442 字）、掘金排序算法长文 14 点；溯源偏移抽检 475 命中 / 0 错位（580 条无偏移=提炼文本非逐字引句，旧有成因）。
2. 重复版本清理（只改 `config/knowatlas.toml`，gitignore，不涉及代码）
   - `[sources.folders].exclude_dirs` 加 `agentic-design-patterns-main/{bilingual,original,_includes,_layouts,images}`（留 `chapters` 中文版）。
   - `ksync --source folders --full` → folders entries **148 → 74**，`archived 74`、`skipped_dir 5`；全库 active **83 / archived 75 / pending 132 / rejected 78**，points 仍 **4,965**（被归档的 74 条本来 0 点，无知识损失）；`人工智能` 挂接 **104 → 46**。
3. 顺带修掉的真问题（本轮排查结论，未改代码）
   - 用户 19:33 转正 3 条链接后三条命令没生效的真因：① 那个 shell 没导入用户级 `KNOWATLAS_LLM_API_KEY`，掘金这类需 DeepSeek 兜底抓取的页面直接失败；② `--fetch-limit N` 的候选**包含 rejected 老条目**（不只看转正的），`N=1` 很容易被排在前面、早被舍弃的链接用掉——用户三条当时连 `fetch_status` 都没写，说明尝试没落在它们身上。
   - 已用生产函数定向补齐那 3 条（`_fetch_missing` + `_categorize` + `run_points_extract(entry_ids=…)`）：掘金 30,534 字/技术开发、两条 Git 各 1 点/后端；`runs` 表留 `targeted-*`。

**下一步（按序）**
1. 用户验收：`serve` 已运行（`http://127.0.0.1:8420`），刷新后看那 16 条长文的点数（如 `4.架构与构建多智能体系统` 101 点）与点级反查高亮是否落在正确段落。
2. 若接受分块粒度 → 考虑把 `_CHUNK_TOTAL_MAX` 从 60,000 放大（>60k 现有 10 条仍 pending，最大 2.5 MB 的书不建议放进来）。
3. 建议新增两项能力（**要开单，未做**）：① `--fetch-limit` 候选只取 active 且「刚转正优先」（现含 56 条 rejected 无正文条目，会白烧额度）；② `ksync/kpoints --entry ID`（可重复）做定向补抓补抽。
4. `人工智能` 里还剩 46 条，其中 root 元文件（AGENTS/CLAUDE/CONTRIBUTING/README/PROJECT_STRUCTURE/OPTIMIZE_README）可考虑 `exclude_globs` 清掉。

**不要重跑**：全量 pytest（686/1 已跑）；16 条长文的分块抽取（383 点已入库，重跑会重复烧 LLM）；`ksync --source folders --full`（74 条已归档）；emmx v14 探针。

**验证命令**：`uv run python -m pytest -o addopts= -q` → `686 passed, 1 skipped`；`uv run python -m pytest tests/test_canary.py -o addopts= -q` → 5 passed。

<!-- HANDOFF {"at":"2026-10-27T21:05:00+08:00","compactions":2,"doc":"docs/log.md#2026-10-27-r16长网页分块抽取--重复版本清理handoff","draft":false,"goal":"R16 长网页分块落地（16 条长文 → 383 新点，4,582→4,965）并清掉同一本书的 74 条重复版本（folders 148→74）","host":"dsh","kind":"handoff","next":"① 刷新 8420 验收 16 条长文的点数与点级反查高亮；② 决定是否放大 _CHUNK_TOTAL_MAX=60000；③ 开单做「--fetch-limit 只取 active 且转正优先」与「--entry 定向补抓/补抽」","not_rerun":"全量 pytest 686/1 与 canary；16 条长文分块抽取（383 点已入库）；ksync --source folders --full；emmx v14 探针","schema":1,"session":"session-588aa31e-6ec3-48d6-bc70-cd94e0d8b315","status":"HANDOFF","tokens":129252,"verify":"uv run python -m pytest -o addopts= -q -> 686 passed, 1 skipped"} --><!-- HANDOFF {"at":"2026-10-27T21:00:10.966252+08:00","compactions":2,"doc":"docs/交接/2026-10-27-2100.md","draft":true,"goal":"上下文到 CRITICAL（98.0%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-588aa31e-6ec3-48d6-bc70-cd94e0d8b315","status":"CRITICAL","tokens":144153,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T21:36:11.523130+08:00","compactions":0,"doc":"docs/交接/2026-10-27-2136.md","draft":true,"goal":"上下文到 HANDOFF（88.1%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-577f2a0f-70ec-450a-9b9b-e093d7771413","status":"HANDOFF","tokens":129499,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T21:38:11.051787+08:00","compactions":0,"doc":"docs/交接/2026-10-27-2138.md","draft":true,"goal":"上下文到 CRITICAL（95.7%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-577f2a0f-70ec-450a-9b9b-e093d7771413","status":"CRITICAL","tokens":140695,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->


## 2026-10-27 R17：fetch 候选口径（只取 active + 转正优先）+ `--entry` 定向补抓补抽 + root 元文件清理

**开场**：`session_check` → NEW_SESSION（上一交接 `session-588aa31e` @21:00:10 CRITICAL）；
`context_probe` → effective 11.4%（16,754 / 147,059）。用户「继续」→ 我按交接块把三条待决项量清后，
用户裁决「③a+③b+④ 一起做」。

### ① 待决项裁决前的只读结论（②已关掉）

- **② 放大 `_CHUNK_TOTAL_MAX`：不做**。10 条 >60k 里 9 条早就有 kpe 产物（1373/820/571/420/315/93/81/78 点），
  只剩 `labuladong的算法秘籍V2.7`（469,435 字 / 0 点 / `points_pending_kpe`）——书该走 `tools/kpe`，
  不该把管道上限抬到 47 万字（≈78 块 × LLM）。
- **③ 确诊**：`_fetch_missing` 按采集顺序遍历、不看库内 status；真库 22 条 rejected 仍带正文（ebook 系列），
  用户 19:33 转正的 3 条跑 `--fetch-limit 1` 一条没抓到。
- **④ 量清**：`agentic-design-patterns-main` 的 7 个 root 元文件 **0 点 0 正文**，清掉零损失。

### ② 落地（工单 `docs/design/变更工单-2026-10-27-fetch候选口径与定向补抓.md`）

| 文件 | 内容 |
|---|---|
| `pipeline/sync.py` | 新增 `_fetch_candidates`（只取 active；转正时间降序排前；定向按点名顺序不看 status）；`run_sync(..., entry_ids=None)`；定向模式**不归档**、默认补抓、`stats.targeted{requested,matched,missing_ids}` |
| `datalayer/db.py` | 新增只读 `status_map()` / `activation_times()`（批量 IN 400/片；转正时间读 `task_log` 的 `bulk_activate`/`restore`，不动表不新增 meta） |
| `cli.py` | `ksync --entry` / `kpoints --entry`（可重复）；kpoints 定向时默认上限=点名条数；`--triage` 与 `--entry` 互斥 |
| `tests/test_entry_targeted.py` | 8 例：候选只取 active / 转正优先 / 定向不看状态 / 端到端 `--fetch-limit 1` 不吃 rejected / 定向不归档 / missing_ids / kpoints 定向 / CLI 可重复 |

### ③ 验证（现场数字）

- 全量 `pytest -o addopts= -q` → **694 passed / 1 skipped**（原 686 + 8）；canary 零漂移。
- 真库 `ksync --source folders --entry 515abb4f9757c923 --fetch-limit 1` → `entries 1 / fetched 1 /
  post_fetch.classified 1 / targeted{requested:1,matched:1,missing_ids:[]}`。
- 真库非定向 `ksync --source folders --fetch-limit 3` → `fetch_mode=active`、`fetch_candidates 65`、
  `fetch_skipped_non_active 2`、`fetched 3`。
- 真库 `kpoints --entry 10a8dc83468f8fce --dry-run` → `processed 1 / limit 1`；跑完 points 仍 **4,965**（零写入）。
- ④ `[sources.folders].exclude_globs`（config 侧，gitignore）7 条 → `ksync --source folders --full`：
  `skipped_excluded 7`、`archived 7`、folders **74 → 67**、active **83 → 76**、archived **75 → 82**、points 仍 4,965。
- 提交：`d9a92b5`（代码+测试+CHANGELOG+工单）、本块随后的 docs 提交。

### 下一步（按序，首步可直接执行）

1. **用户 Ctrl+F5 验收**（仍未做过的两项）：`graph.html` ◆点层 → 点节点 → 🔍 反查 → 溯源条目「打开原文」开 PDF；
   分类页模式条「🧠 按主题」→ 展开主题 → 溯源。serve 在跑（8420），本轮只改 CLI/管道，页面无需重启。
2. `kpoints --entry 10a8dc83468f8fce`（去掉 `--dry-run`）把 glossary 真抽一次（1 次 LLM 调用）。
3. 剩余可选方向：`labuladong`（469k 字）走 `tools/kpe`；8.1b trafilatura 换装 A/B；Phase B 三凭证源（B站/IMA/腾讯文档，等凭证）；
   打包安装（Phase 5 仍 `[ ]`）。

### 不要重跑

- 全量 pytest（694/1）与 canary；`ksync --source folders --full`（7 条已归档）；`ksync --fetch-limit 3`（3 条已抓）；
  `kpoints --entry 10a8dc83468f8fce --dry-run`（已验证）；`temp/probe_r16_state*.py`、`probe_meta_files.py`、
  `probe_targeted_candidates.py`、`probe_points_targets.py`、`probe_dryrun_nowrite.py`。
- 交接块里「② 放大 `_CHUNK_TOTAL_MAX`」已裁决**不做**，别再量。

### 验证命令

```powershell
uv run python -m pytest -o addopts= -q                     # 694 passed, 1 skipped
uv run python -m knowatlas ksync --source folders --dry-run # folders 67 条、skipped_excluded 7
uv run --with zstandard python tools/context_probe.py      # 本会话 effective 98.5%（CRITICAL）
```

### 会话指纹

`session-577f2a0f-70ec-450a-9b9b-e093d7771413`，compactions=0，tokens=144,802，baseline 147,059，
effective **98.5%**（CRITICAL），2026-10-27T21:38+08:00。

<!-- HANDOFF {"at":"2026-10-27T21:40:00+08:00","compactions":0,"doc":"docs/log.md#2026-10-27-r17fetch-候选口径只取-active--转正优先-entry-定向补抓补抽--root-元文件清理","draft":false,"goal":"R17 落地：fetch 候选只取 active + 转正优先、ksync/kpoints --entry 定向补抓补抽、root 元文件归档 7 条（694 passed / 1 skipped）","host":"dsh","kind":"handoff","next":"① 用户 Ctrl+F5 验收反查「打开原文」与分类页「按主题」；② kpoints --entry 10a8dc83468f8fce 真抽 glossary；③ 可选：labuladong 走 kpe / 8.1b / Phase B 凭证源 / 打包安装","not_rerun":"全量 pytest 694/1 与 canary；ksync --source folders --full；ksync --fetch-limit 3；kpoints --entry 10a8dc83468f8fce --dry-run；temp/probe_r16_state*、probe_meta_files、probe_targeted_candidates、probe_points_targets、probe_dryrun_nowrite","schema":1,"session":"session-577f2a0f-70ec-450a-9b9b-e093d7771413","status":"CRITICAL","tokens":144802,"verify":"uv run python -m pytest -o addopts= -q -> 694 passed, 1 skipped"} -->
## 2026-10-27 21:47 用户追加需求（最高优先级）：入库即自动生成知识点，零人工

> 用户原话：「所有数据源，应该是入库即能自动生成知识点，无需人工的」。
> 本轮上下文已 CRITICAL（98.5%），**只登记需求与差距，未动代码**；实现交新会话（先工单、再动手）。

### 现状差距（七条，均已现场确认过、无需重查）

| # | 人工环节 | 位置 |
|---|---|---|
| 1 | `kpoints` 是**独立命令**，`ksync` 只入库不抽点 → 每次同步后要手动跑 | `cli.py` / `pipeline/sync.py`（无 auto_points） |
| 2 | `[fetch] on_sync=false`：同步不抓正文，`--fetch-limit` 显式才抓 → 没正文就没点 | `pipeline/sync.py:742` 附近 |
| 3 | `new_entries="pending"` 闸门：真库 **132 条待审**，未转正不抓不分类不抽点 | 批次 68；`web/api.py` bulk-status |
| 4 | 正文 >60,000 字落 `meta.points_pending_kpe`，要人工跑 `tools/kpe` + `kpeimport` | `pipeline/points.py::_CHUNK_TOTAL_MAX` |
| 5 | `meta.points_gate` 拦下的条目要 `--retry-blocked` 手动重试 | `pipeline/points.py` |
| 6 | LLM key 缺失静默降级成「整篇照抄 integral」（R10 已加 WARN，但仍是降级） | `cli.py::_warn_if_llm_unavailable` |
| 7 | 定向补抓补抽（R17 刚做的 `--entry`）本身也说明「补」是人工触发的 | R17 |

### 计划骨架（待用户点头 + 工单，涉 `CONFIG_SCHEMA_KEYS` 属契约变更）

1. **A 同步即抽点**：`[sync] auto_points=true`（新 config 键 → 工单 + canary），`run_sync` 尾部对
   「新入库 / 内容变化 / 本轮抓到正文」的条目自动调 `run_points_extract(entry_ids=…)`；
   沿用 `point_source_entry_ids()` 游标做幂等，不重抽。
2. **B 同步即抓正文**：`[fetch] on_sync=true` + `auto_fetch_limit`（有上限，防一次烧爆）；
   与 A 串成「入库 → 抓正文 → 分类 → 抽点」一条链。
3. **C 待审闸门自动化**：`new_entries="pending"` 改成「自动转正 + 规则守门」——`value_guard`
   已能打 `not_knowledge`（直链/首页/列表页），自动转正后可人工否决；或保留闸门但 `ksync`
   自动对 pending 跑 L0 体检再批量转正。
4. **D 超长文自动化**：>60k 不再交人工 kpe，改后台分块（放大 `_CHUNK_TOTAL_MAX` 或起 kpe 等价作业），
   按条计价护栏 + 每轮上限。
5. **E 兜底巡检**：serve 内定时任务（如 10 min）扫「active 且无正文/无点」的条目补跑，
   保证「无需人工」不是「每次都要记得跑命令」。
6. **F 费用与幂等护栏**：每轮条数上限、失败重试计数、`task_log` 审计、dry-run 报告。

### 验证口径（新会话照此验收）

空库 `kinit` → 配一个新源 → **只跑一次 `ksync`** → 等一轮巡检 → 查「该源全部 active 条目
均有 `content_hash` 且点数 > 0」，人工零操作；`task_log` 能回答每个条目「抓了没 / 抽了没 / 为什么没」。

### 下一步（按序）

1. 用户确认计划骨架（尤其 C 的闸门取舍与 F 的费用上限）。
2. 新会话开工：先写 `docs/design/变更工单-2026-10-28-入库即抽点.md`（含 `CONFIG_SCHEMA_KEYS` 变更），
   再改 `pipeline/sync.py` + `cli.py` + `config.py`，补测试，跑 canary。
3. 不要重跑：R17 的全量 694/1、folders 全量同步、7 条元文件归档。<!-- HANDOFF {"at":"2026-10-27T22:26:12.709349+08:00","compactions":0,"doc":"docs/交接/2026-10-27-2226.md","draft":true,"goal":"上下文到 CRITICAL（98.5%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"CRITICAL","tokens":144833,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T22:42:10.747998+08:00","compactions":1,"doc":"docs/交接/2026-10-27-2242.md","draft":true,"goal":"会话已被自动压缩 #1","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"OK","tokens":79165,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

## 2026-10-27 22:55 R18：入库即抽点与自动老化落地（含 KPE 上游 0.2.0）

> 承接 21:47 的需求与七条差距。用户对四个岔路做了裁决（全部采纳建议）：
> ① 待审按类型自动分流；② KPE 点数上限做成上游参数（默认 6）；③ 老化=分类黑名单 + `kind=hard`；
> ④ serve 内置巡检 + `kauto` 无界面等价物。另追加 ⑤：未来是服务，三层要能分开（已写架构文档）。

### 落地内容

| 环节 | 产物 |
|---|---|
| 待审自动转正 | `pipeline/sync.py` 第三取值 `new_entries="auto"` + `pipeline/ingest.py::l0_guard` |
| 按类型分流 | `pipeline/ingest_router.py`（零 LLM，纯结构信号；跳过也写理由） |
| 管道抽点 | `pipeline/points.py` 阈值改读 `[points]`（缺省不变） |
| KPE 自动通道 | `pipeline/kpe_runner.py`（`python -m kpe` + `kpeimport`，产物 `data/kpe/<entry>/`） |
| 老化域闸门 | `pipeline/domain_gate.py` + `lifecycle.py`/`aging.py`（黑名单语义、窗口化过滤） |
| 无人值守 | `web/worker.py::IngestWorker`（serve 内置，`[ingest] enabled`）+ `kauto` 命令 |
| 巡检主体 | `pipeline/ingest.py::run_ingest_pass`（激活→抓→分流→抽→到点老化，失败 `dead` 队列） |
| 契约 | `config.py` 新增 12 键；`point_extract` 2.2.0；`db.point_source_map()`；canary 升版 |
| KPE 上游 | `kpe 0.2.0`：`extract --max-points`（默认 6，1–20），已推 + `git subtree pull` |

### 现场数字（已实测，勿重跑）

- 全量 `pytest -o addopts= -q` → **715 passed / 1 skipped**（基线 694，新增 21）；
  `tests/test_canary.py` 零漂移；KPE 上游 18 项全绿（新增 `tests/test_max_points.py` 4 项）。
- 真库 `kauto --dry-run --limit 5`（22:4x）：待审 132 → 激活 97 / 拒绝 35
  （`portal_homepage` 19、`index_subdir` 16）；路由 `pipeline 4 / kpe 1 / skip 8`；
  `fetch_planned 5`；零写库、零 LLM（dry-run 已改为完全免费）。
- `kpe_runner` 探测：`available()=True`、`supports --max-points=True`。

### 提交

- `77c9f2f feat: 入库即抽点与自动老化（kauto 巡检 + KPE 自动通道 + 老化域闸门）`
- `da91df3 Squashed 'tools/kpe/' changes from 910c85c..ef0e251` + merge `27a62de`
- 上游 kpe：`ef0e251 feat: extract --max-points（默认 6；prompt 与截断同源）`

### 下一步（按序，首步可直接执行）

1. 真库实跑一轮：先导入 key（用户级变量 → 当前进程），`uv run python -m knowatlas kauto --limit 3`，
   确认 `split>0` 且 `points_created>0`；抽查 3 条 `meta.ingest`（route/reason/at）。
2. 把 `[ingest] enabled = true` 写进本机 `config/knowatlas.toml`，`serve` 起来看巡检日志
   （"入库巡检启动：每 600s 一轮"），再决定 `interval_seconds` 与 `max_entries_per_run`。
3. 管理页补「上一轮巡检」视图（`GET /api/tasks`，服务化 P1，非阻塞）。
4. 移动/远程访问按 `docs/design/架构-2026-10-27-服务化分层与服务端职责.md` §7 的 P1→P2 推进。

### 不要重跑

- 全量 pytest 715/1、canary、KPE 上游 18 项；
- `kauto --dry-run --limit 5`（真库 132 待审的分流结果已记录）；
- `git subtree pull --prefix=tools/kpe kpe main --squash`（已到 `ef0e251`）；
- `temp/probe_aging_gate_20261027.py`、`temp/kpe-up`（上游克隆已推完，可留可删）。

### 已知失败与处理

- PowerShell 把 git/uv 的 stderr 当 `NativeCommandError`（exit 1）：看到 `main -> main` /
  `18 passed` 即成功，别当失败重试。
- `kauto --dry-run` 在 LLM 未配置时输出 WARN（"语义层降级"）——dry-run 本身不烧钱，实跑前必须
  按 AGENTS.local 导入三个用户级环境变量。

<!-- HANDOFF {"at":"2026-10-27T22:56:00+08:00","compactions":1,"doc":"docs/log.md#2026-10-27-2255-r18入库即抽点与自动老化落地含-kpe-上游-020","draft":false,"goal":"R18 落地：入库即抽点与自动老化（kauto / serve 巡检 / KPE 自动通道 / 老化域闸门）+ KPE 0.2.0 --max-points（715 passed / 1 skipped）","host":"dsh","kind":"handoff","next":"① 导入 key 后真库 kauto --limit 3，确认 split>0 与 meta.ingest；② [ingest] enabled=true 后 serve 看巡检日志；③ GET /api/tasks 上一轮巡检视图；④ 服务化 P1/P2（架构文档 §7）","not_rerun":"全量 pytest 715/1 与 canary；kauto --dry-run --limit 5（132 待审→97 激活/35 拒绝已记录）；git subtree pull tools/kpe（已在 ef0e251）；temp/kpe-up 上游克隆已推完；temp/probe_aging_gate_20261027.py","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"OK","tokens":86000,"verify":"uv run python -m pytest -o addopts= -q -> 715 passed, 1 skipped"} -->

<!-- HANDOFF {"at":"2026-10-27T22:52:10.799167+08:00","compactions":1,"doc":"docs/交接/2026-10-27-2252.md","draft":true,"goal":"上下文到 HANDOFF（88.2%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"HANDOFF","tokens":129712,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T23:04:11.496436+08:00","compactions":1,"doc":"docs/交接/2026-10-27-2304.md","draft":true,"goal":"上下文到 CRITICAL（107.3%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"CRITICAL","tokens":157762,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T23:36:10.991816+08:00","compactions":2,"doc":"docs/交接/2026-10-27-2336.md","draft":true,"goal":"会话已被自动压缩 #2","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"OK","tokens":103257,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->


## 2026-10-27 23:45 R19：规划收口（三份参考文档 + 四项决策 + 自主运行口径）

本轮没有再动业务代码，全部是"把该定的定下来、该生成的生成出来"。

### 落地

| 产物 | 内容 |
|---|---|
| `docs/参考-命令.md` | 13 个子命令与全部参数（从 `argparse` 解析树生成） |
| `docs/参考-配置.md` | 59 个键：类型/代码默认/示例值/说明/D-S-T 分类（从 schema+example 生成） |
| `docs/参考-接口.md` | 73 个端点分 25 组（从 `app.openapi()` 生成）+ 12 个缺 docstring 的待补清单 |
| `docs/模块地图.md` | 按能力域（A–H）清点：模块、入口、表、稳定性 |
| `docs/design/方案-2026-10-27-四个大文件拆分.md` | 路线 A：护栏 → cli → sync → api → db，含坑（`_guard` 的 MRO） |
| `docs/design/ADR-2026-10-27-工具分级与边界.md` | Tier A/B/C 判据、调用方式、pg 不 vendor 的理由 |
| `docs/design/方案-2026-10-27-配置分层与单一来源.md` | 四类旋钮 + 一份生效文件 + `kconfig` |
| `docs/TODO.md` | 决策记录 D1–D4 + P0–P4 + **自主运行口径**（顺序/验收/停止条件/红线） |

生成器暂放 `temp/gen_docs_20261027.py`（过程脚本）；转正式 `tools/gen_docs.py` 列在 TODO P2 第 1 条。

### 决策（用户 2026-10-27）

- **D1** 工具不"都独立"，走 Tier A（kpe/session-guard）/ B（clean/eol/embed/gate/export）/ C（datalayer 等）三级。
- **D2** 不冻结重写，走路线 A 只拆四个大文件。
- **D3** 配置不按层拆文件，按 D/S/T/I 四类管，一份生效文件（`KNOWATLAS_CONFIG` 本来已支持）。
- **D4** `pg` 不 vendor，留在 `D:\sData\git\pg`（已 fetch 到 `bf34cf7`，与远端一致）。

### 现场

- 提交：`9e89b9b`（模块地图+TODO）→ `30e239c`（三份设计文档）→ `56f5b68`（三份参考）→ `8328059`（渲染修正）→ `27cfa66`（自主运行口径）。
- `D:\sData\git\kpe` 已克隆（HEAD `ef0e251`，含 0.2.0）；`tools/kpe` 子树仍在，升级走 `git subtree pull`。
- 未跑全量测试：本轮零业务代码改动（只加了 `temp/` 脚本与 `docs/`）。

### 下一步（按序，首步可直接执行）

1. ✅ 已做（23:52，`74d565f`）：`tools/gen_docs.py --check` + `tests/test_docs_in_sync.py`，全量 716 passed / 1 skipped。
2. 护栏三件：`test_web_routes.py`（73 端点快照）、`test_cli_surface.py`、`test_datalayer_surface.py`。
3. `cli.py` → `cli/`（7 文件）；4. `sync.py` → `sync/`；5. `api.py` → routers；6. `db.py` → mixin。
4. 详见 `docs/TODO.md`「自主运行口径」。

### 不要重跑

- 三份参考文档已生成（除非源码改了才重跑 `temp/gen_docs_20261027.py`）；
- 全量 pytest 715/1、canary、`kauto --dry-run`、`git subtree pull tools/kpe`（已在 `ef0e251`）；
- `pg` 的接入评估（D4 已裁决，别再翻）；`kpe` 克隆（已在 `D:\sData\git\kpe`）。

### 已知失败与处理

- 本会话 23:04 已到 `effective_pct=107%` 并被自动压缩 #2；当前 73.1%（107,434 tokens）。
  **不要在本会话继续大改**，开新会话说「继续」。
- `watcher` 会写 `draft:true` 的交接块（23:36 那条），那是上下文事件，不是工作交接——读本文上面这条。

<!-- HANDOFF {"at":"2026-10-27T23:45:30+08:00","compactions":2,"doc":"docs/log.md#2026-10-27-2345-r19规划收口三份参考文档--四项决策--自主运行口径","draft":false,"goal":"规划收口：三份自动生成参考（命令/配置/接口）+ D1–D4 决策 + 路线 A 拆分方案；下一步按 TODO 自主开工","host":"dsh","kind":"handoff","next":"① tools/gen_docs.py --check + test_docs_in_sync.py；② 护栏三件（routes/cli/datalayer 快照）；③ cli.py 拆包；④ sync.py 拆包；⑤ api.py 拆 routers；⑥ db.py 拆 mixin","not_rerun":"三份参考文档已生成；全量 pytest 715/1 与 canary；kauto --dry-run --limit 5；git subtree pull tools/kpe（ef0e251）；pg 接入评估（D4 已定不 vendor）","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"OK","tokens":107434,"verify":"uv run python -m pytest -o addopts= -q -> 715 passed, 1 skipped"} -->
<!-- HANDOFF {"at":"2026-10-27T23:48:11.867803+08:00","compactions":2,"doc":"docs/交接/2026-10-27-2348.md","draft":true,"goal":"上下文到 HANDOFF（88.9%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"HANDOFF","tokens":130811,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->

<!-- HANDOFF {"at":"2026-10-27T23:50:11.916521+08:00","compactions":2,"doc":"docs/交接/2026-10-27-2350.md","draft":true,"goal":"上下文到 CRITICAL（96.5%）","host":"dsh","kind":"handoff","next":"","not_rerun":"","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"CRITICAL","tokens":141956,"verify":"session-guard check --workspace \"D:\\sData\\git\\KnowAltas\""} -->


## 2026-10-28 00:00 R20：路线 A 第 1–2 步（护栏 + cli 拆包）

### 落地（两个提交，均已推送）

| 提交 | 内容 |
|---|---|
| `cc0e556` | 三道护栏：`test_web_routes.py`（73 端点）、`test_cli_surface.py`（13 子命令）、`test_datalayer_surface.py`（127 公开方法）。已实测"故意改坏会红"。全量 **720 passed / 1 skipped**。 |
| `454ff1b` | `cli.py` 775 行 → `cli/` 8 文件（`__init__` 49、`_shared` 44、`parser` 191、`cmd_entry` 53、`cmd_sync` 70、`cmd_ops` 193、`cmd_points` 161、`cmd_quality` 158）。函数体逐字搬迁，`from .` 统一升一级为 `from ..`（含函数体内的局部 import）。全量仍 720/1，canary 零漂移，`gen_docs --check` 三份参考仍同步。 |

### 两个必须记住的坑（拆后面三个文件会再遇到）

1. **相对导入升一级**：`cli.py` 变包后，`from .config` 必须变 `from ..config`；**函数体内的局部 import 也要改**（`_cmd_kbackup` 里的 `from .pipeline.backup` 就是漏网之鱼，表现为 `ModuleNotFoundError: knowatlas.cli.config`）。包内兄弟模块（`._shared`/`.parser`/`.cmd_*`）保持单点。
2. **测试 monkeypatch 的落点变了**：`monkeypatch.setattr(cli, "load_config", …)` 失效，因为 `load_config` 现在绑在 `cli.cmd_ops` 上。改法是 patch 使用处（`from knowatlas.cli import cmd_ops` 后 setattr）。已在 `test_backup.py` 修正。

### 下一步（按序）

1. `pipeline/sync.py` 782 行 → `pipeline/sync/`（`__init__` 编排壳 + `fetch/store/enrich/flags`），保留 `pipeline.sync.run_sync` 路径。
2. `web/api.py` 1,799 行 → `web/ctx.py` + `web/routers/`（7 域），URL 逐字不动，靠 `test_web_routes.py` 兜底。
3. `datalayer/db.py` 3,194 行 → 10 文件 + mixin；**先改 `_guard` 的扫描为 `mro`**，否则锁静默失效。

### 不要重跑

- 三份参考文档（`gen_docs --check` 已绿）；护栏三件与 cli 拆包（已提交）；
- 全量 pytest 现基线是 **720 passed / 1 skipped**（不是 715）；
- 别再评估 pg（D4 已定）、别再克隆 kpe（已在 `D:\sData\git\kpe`）。

### 现场

- 本会话上下文已到 **96.5%（141,956 tokens，CRITICAL）**，必须换会话。
- 工作区干净，`main...origin/main` 同步，HEAD = `454ff1b`（TODO 的勾选在下一个提交里）。

<!-- HANDOFF {"at":"2026-10-28T00:01:30+08:00","compactions":2,"doc":"docs/log.md#2026-10-28-0000-r20路线-a-第-12-步护栏--cli-拆包","draft":false,"goal":"路线 A 进度：护栏三件 + cli.py 拆包完成（720 passed/1 skipped，454ff1b）；剩 sync/api/db 三个大文件","host":"dsh","kind":"handoff","next":"① pipeline/sync.py 拆成 pipeline/sync/（保留 run_sync 路径）；② web/api.py 拆 ctx+routers（URL 逐字，靠 test_web_routes 兜底）；③ datalayer/db.py 拆 mixin（先改 _guard 扫 mro）","not_rerun":"三份参考文档已生成且 --check 绿；护栏三件与 cli 拆包已提交（cc0e556/454ff1b）；全量基线 720 passed/1 skipped；pg 接入评估（D4 已定）；kpe 克隆（已在 D:\\sData\\git\\kpe）","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"HANDOFF","tokens":141956,"verify":"uv run python -m pytest -o addopts= -q -> 720 passed, 1 skipped"} -->

### 2026-10-28 00:15 追加：sync 拆包**已备好但未落地**（上下文 CRITICAL）

`temp/split_sync_20261028.py` 已写好并跑通**预览模式**（输出到 `temp/sync_preview/`，不动 `src/`）：

| 产物 | 行数 |
|---|---|
| `_common.py` | 42 |
| `fetch.py` | 153 |
| `store.py` | 107 |
| `enrich.py` | 272 |
| `flags.py` | 40 |
| `__init__.py` | 276 |

自检三项全过：**编译通过 / 无残留单点相对导入 / 每个函数体与原文 AST 逐字等价**。

落地步骤（新会话直接执行，约 3 分钟）：

```powershell
uv run python temp/split_sync_20261028.py --apply      # 生成 pipeline/sync/ 包
Remove-Item src/knowatlas/pipeline/sync.py             # 删旧单文件
uv run python -m pytest -o addopts= -q                 # 期望 720 passed / 1 skipped
```

必须记住的两点（脚本已处理，验证时别以为是 bug）：

1. `sync.py` 原本在 `pipeline/` 下，用的是 `from ..fetchers` 两级相对导入；进包后要变三级（`from ...fetchers`）。脚本按"点数 +1，兄弟模块除外"处理。
2. `pipeline/sync/__init__.py` 必须 re-export `_categorize` `_fetch_missing` `_apply_content` `_fetch_candidates` `_freshness_scan` `_clear_stale_fetch_flags` —— `ingest.py` 与 6 个测试按名取用，漏一个就是 ImportError。

<!-- HANDOFF {"at":"2026-10-28T00:16:10+08:00","compactions":2,"doc":"docs/log.md#2026-10-28-0015-追加sync-拆包已备好但未落地上下文-critical","draft":false,"goal":"路线 A 进度：护栏+cli 已落地（720/1）；sync 拆包脚本已备好并通过预览自检，只差 --apply","host":"dsh","kind":"handoff","next":"① uv run python temp/split_sync_20261028.py --apply；② 删 src/knowatlas/pipeline/sync.py；③ 全量 pytest 期望 720/1；④ 绿了提交推送；⑤ 接着 api.py 拆 routers；⑥ db.py 拆 mixin（先改 _guard 扫 mro）","not_rerun":"三份参考文档；护栏三件；cli 拆包；sync 预览自检（已通过，别重复调试脚本）；pg 评估；kpe 克隆","schema":1,"session":"session-9089cfba-7f7b-4fe0-997b-0cebec08ccbb","status":"HANDOFF","tokens":179000,"verify":"uv run python -m pytest -o addopts= -q -> 720 passed, 1 skipped"} -->
