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
