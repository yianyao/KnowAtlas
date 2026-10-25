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
