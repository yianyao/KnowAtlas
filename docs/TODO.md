# TODO（KnowAtlas，2026-10-27 重排）

> 排序原则：**能让人少操作 > 能让数据更对 > 能让代码更好改 > 能让界面更好用**。
> 每条都有「判据」——不写「优化性能」这种没有验收口径的条目。
> 现状与模块归属见 `docs/模块地图.md`；未来形态见
> `docs/design/架构-2026-10-27-服务化分层与服务端职责.md`。
>
> 本文件 2026-10-27 重排；**2026-10-29 已把 R29（检索热路径）/ R30（dedupe 误并）/ R31（超大书分卷）
> 三项回勾**。设计与决策档案的导航见 `docs/design/README.md`，逐轮的现场数字见 `docs/log.md`。

## 自主运行口径（2026-10-27 夜，用户授权「做好 todo 后自己开工」）

**执行顺序**（每步 = 一个 commit + 推送，跑完全量再进下一步）：

1. ✅ 生成器转正（2026-10-27 23:50）：`tools/gen_docs.py`（`--check` 只比对不写）+
   `tests/test_docs_in_sync.py`；全量 **716 passed / 1 skipped**。`temp/gen_docs_20261027.py` 可删。
2. ✅ 护栏（2026-10-28 00:0x）：`test_web_routes.py`（73 端点）、`test_cli_surface.py`（13 子命令）、
   `test_datalayer_surface.py`（127 个公开方法）；全量 **720 passed / 1 skipped**，且已验证"故意改坏会红"。
3. ✅ `cli.py` → `cli/`（2026-10-28 00:0x，`454ff1b`）：8 文件（`__init__/parser/_shared/cmd_entry/cmd_sync/cmd_ops/cmd_points/cmd_quality`），
   最大 193 行；函数体逐字搬迁，`from .` 统一升一级为 `from ..`；全量仍 **720 passed / 1 skipped**。
4. ✅ `pipeline/sync.py` → `pipeline/sync/`（2026-10-28 01:3x）：6 文件（`__init__` 276 / `enrich` 273 /
   `fetch` 155 / `store` 108 / `_common` 42 / `flags` 40）；函数体逐字搬迁，`run_sync` 与 5 个私有入口路径不变；
   坑：兄弟模块符号要显式 import，否则运行期 `NameError`（已在脚本里加第四道自检）。全量仍 **720 passed / 1 skipped**。
5. ✅ `web/api.py` → `web/ctx.py` + `web/routers/`（2026-10-28 01:4x）：7 域（`entries` 665 / `threads` 363 /
   `knowledge` 361 / `discovery` 226 / `graph` 190 / `admin` 168 / `categories` 124），`api.py` 只剩 103 行
   façade + 安全层。URL/响应逐字不变（路由清单 73→73 逐条比对），函数体 AST 逐字等价。全量仍 **720 passed / 1 skipped**。
6. ✅ `datalayer/db.py` → `datalayer/`（2026-10-28 02:0x）：`core.py` 113 行（组合/连接/事务/迁移）+
   10 个 mixin（`entries` 579 / `graph` 726 / `points` 518 / `views` 333 / `threads` 323 / `categories` 302 /
   `search` 264 / `vectors` 112 / `content` 107 / `ops` 97）+ `_common.py` 90 + `db.py` 12 行 façade；
   **先改 `_guard` 扫 MRO 并补锁护栏测试**（`adb544c`，实测改回 `vars(type(self))` 会有 124 个公开方法失锁、
   护栏测试变红）。SQL/方法名/签名/事务边界逐字不动，AST 等价 + 字符串常量多重集校验通过；
   全量仍 **721 passed / 1 skipped**，canary 零漂移。

**每步固定验收三条**：

```powershell
uv run python -m pytest -o addopts= -q          # 期望 721 passed / 1 skipped（2026-10-28 基线）
uv run python -m pytest -o addopts= -q tests/test_canary.py   # 期望零漂移
git status -sb                                   # 期望只有本步改动
```

**停止条件（遇到即停，不硬撑）**：

- 全量测试变红 → 不修第二遍：回滚该 commit（`git revert`），把现象写进 `docs/log.md` 再停。
- `effective_pct ≥ 85%` → 写交接块，停，让用户换会话。
- 任何一步需要改契约（表/字段/scheme/接口签名/config 键）→ 停下写工单，不自裁。

**红线**：不改 SQL 逐字、不改 URL、不改公开方法名与 CLI 参数、不夹带新功能、不碰 `tools/kpe`。

## 0. 决策记录（2026-10-27 已定）

### D1 工具是否都按 kpe 模式独立成仓库？

**已定：不"都独立"，按三级策略（Tier A/B/C）执行。**
落地文件：`docs/design/ADR-2026-10-27-工具分级与边界.md`（判据 C1–C5、各层职责、
调用方式、新增/升级流程、复查触发条件）。

- Tier A（独立仓库）：`kpe`、`session-guard`。以后只增"文件进文件出 + 重依赖"的。
- Tier B（内部包、禁反向依赖）：`clean`、`eol`、`embed`、`point_gate`、`domain_gate`、`export`、`kpe_import`。
- Tier C（核心不动）：`datalayer`、`models`、`ids`、`errors`、`config`、`registry`、`pipeline` 编排。

### D2 冻结当前项目、参照它重做一个新的？

**已定：不冻结、不重写；走路线 A——只拆四个大文件。**
落地文件：`docs/design/方案-2026-10-27-四个大文件拆分.md`
（四道护栏测试、四个文件的逐文件拆分结构、顺序与工时、回滚、明确不做）。

顺序：护栏 → `cli.py` → `sync.py` → `api.py` → `db.py`，合计 4–4.5 个工作日，每步一 commit。

### D3 配置要不要按层拆成多个文件？

**已定：不按层拆文件；按"四类旋钮"分层，一份生效文件 + 自动生成的配置参考。**
落地文件：`docs/design/方案-2026-10-27-配置分层与单一来源.md`
（D 部署 / S 秘密 / T 领域阈值 / I 实现常量；`kconfig show|check|docs`；
`KNOWATLAS_CONFIG` 多环境；客户端零配置）。

### D4 `pg`（项目规范母版）要不要像 kpe 一样装进本仓库？

**已定：不 vendor，保持在 `D:\sData\git\pg` 独立维护**（已同步到 `bf34cf7`）。
理由写在 ADR §6：pg 是"被复制的规范"（`bootstrap` + `SPEC_VERSION` + `upgrade_spec`），
不是"被调用的工具"；subtree 会造成两套 `AGENTS.md` + `tools/` 撞车，并废掉
"规则评审后才升级"的设计前提。

可选接入（按收益排序，均未开工）：

- [ ] 借 `gen_docs.py` 思路做 `kconfig docs`（已在配置方案 §5，推荐）；
- [ ] 借 `guard.py` 统一 `tools/session_*.py` 与计划任务接线（可选）；
- [ ] 若要"所有项目统一规范"，再对 KnowAtlas 跑 `bootstrap.py` + 评审合并 core 区（1–2 天）。

## P0 · 正确性与风险（本周内）

- [ ] **真库实跑一轮巡检**：导入三个用户级 key → `kauto --limit 3` → 确认 `split>0`、
      `points_created>0`，抽查 3 条 `meta.ingest`（route/reason/at）。
      判据：3 条都有正文 hash + 点；无 `dead`；`task_log` 有 `kauto` 记录。
- [ ] **待审 132 条落定**：先 `kauto --activate-only --dry-run` 复核名单（97 激活 / 35 拒绝），
      再实跑 `kauto --activate-only`。判据：pending 归零；35 条 `value_flag_reason` 可解释。
- [ ] **打开 serve 巡检**：`config/knowatlas.toml` 加 `[ingest] enabled = true`，
      `serve` 后确认日志「入库巡检启动：每 600s 一轮」。判据：跑满两轮无异常、无双写冲突。
- [ ] **R17 界面验收**（一直挂着）：Ctrl+F5 后看「打开原文」与分类页「按主题」是否正常。
      2026-10-29 用 headless Edge 先跑了一遍：搜「算法」105 个链接里 57 条「打开原文」走
      `/api/entries/{id}/file`、1 条 http、47 个 `#` 按钮；分类页「按主题」= 5 条目 → 81 点 → 12 主题。
      **剩你自己在真浏览器 Ctrl+F5 复看一次**（headless 不算界面验收）。
- [x] **dedupe「模板同构」误并**（2026-10-28 实证，**2026-10-29 R30 已修**）：`dedup_points` 阈值 0.92 对
      「同书同模板、只差一个限定词/否定词」的句子会误并。**修法不是提阈值**——实测真重复最低余弦 0.9174、
      误并最高 0.9607，区间重叠（提 0.95 仍会并掉那对，0.97 等于废掉全库去重）。改为「规则挑边界对
      （数字 token / 否定词 / 长度比）+ `point_dupe_judge` LLM 裁定」：真库实跑 `dupes 0 / risky 5 /
      vetoed 5`，6 对误并全拦住。工单 `变更工单-2026-10-29-dedupe误并裁定.md`。

## P1 · 功能补全（两周内）

- [x] **`GET /api/tasks`**（2026-10-28，R25）：上一轮巡检/老化的时间、耗时、条数、错误数、试跑/未完成；
      管理页「数据管理」页签加任务卡片（替换原先只有 kind 的徽标）。
      判据：巡检跑完后打开页签即见，不需要翻日志 —— 已用真库 + headless Edge 实测
      （`入库巡检 2026-10-27 22:46 · 激活 97 · 拒绝 35 · 试跑 · 共 3 轮`，`增量同步 … 未完成 1`）。
      工单 `docs/design/变更工单-2026-10-28-任务视图API.md`。
- [x] **点层补作业**（2026-10-28 12:5x 实跑）：413 条无 `kind` → `kpoints --triage` 全部落库
      （hard 106 / opinion 265 / unjudgeable 42，14 次 LLM 调用），**无 kind 点 = 0**；
      `kaging --lifecycle` 全库 1,643 候选：A 段版本型 **0 命中**（hard 点里没有「Python 3.8」这类写法，
      39 条老的已在 10-26 判过），B 段 2 个技术栈分组 → 1 次 LLM → 15 点 `ok`、0 `stale`。
      **`aging_flag` 仍全空**：判据的后半句改口径——没有 stale 就没有 flag，不是漏跑（见 log 2026-10-28 12:5x）。
- [x] **点质量抽检**（2026-10-28，`temp/probe_point_quality_20261028.py`，种子 20261028）：随机 30 条
      逐条判「能否脱离原文读懂」→ 26 条清楚、4 条偏弱（多为 `unjudgeable`：脱离上下文的实验数字/轶事/
      具体代码细节）。**合格率 86.7% ≥ 80%**，不达标样本不进回归集（弱的是"缺上下文"，不是"错"）。
- [x] **KPE 实跑验收**（2026-10-28 20:35–20:39 真库实跑）：`kauto --limit 1` 打 labuladong
      （469,435 字 / 0 点）→ 吃 **PDF 原件**分块 **93 块 / 715 页**；`--max-points 6` 生效
      （KPE `stats.json` 的 `max_points=6`，93 块出 547 点，≈5.9/块）；
      **547 点入库**，`meta.ingest = {route: kpe, reason: pdf_book_or_large, chunks: 93, points: 547}`，
      点 meta 带 `extractor=kpe` / `book` / `section_path` / `quote`（518/547 quote 命中）。
      耗时 153 s、tokens 324k in + 39k out（`deepseek-chat`；硅基 key 余额 402 后 failover）。
      过程修了 5 处缺陷：路由后缀 / 原件解析 / key 池 / 预算分配 / 后端 failover + 产物绝对路径，
      见 `docs/design/变更工单-2026-10-28-PDF原件解析与书目路由.md`。
- [ ] **PDF 目录识别（上游）**：labuladong 715 页解析出 **0 条目录** → 该书的点 `page_start=0`、
      `section_path` 退化成书名。属 `tools/kpe` 上游 `parse_toc`/`window_sections` 能力，
      本仓库不动子树；要做先改上游再 `git subtree pull`。
- [ ] **配置示例同步**：`config/knowatlas.example.toml` 已加 `[ingest]/[points]/[aging]`，
      补一句「kauto 与 serve 巡检共用同一组键」到 SOP。
- [x] **检索热路径 numpy 快路径**（2026-10-28 实测，**同日 R29 已修**）：`semantic/embed.py::top_similar`
      纯 Python 余弦 → numpy/BLOB 直连快路径（缺 numpy/维度不齐回落），5,607×1,024 实测 510 ms → **7 ms**；
      同批修了 `_search_like` 的 FTS JOIN 计划（3.1 s → 25 ms）与 `qvec` 复用（encode 2→1）。
      真库 `/api/search` hybrid **4.9 s → 0.18 s**。工单 `变更工单-2026-10-28-检索热路径提速.md`。
- [x] **超大书（正文 > `kpe_max_chars`）重抽堵死**（**2026-10-29 R31 已修**）：`run_kpe_for_entry` 改为
      「先整本切块、再决定单卷/多卷」，按章装箱成 `v001..` 逐卷抽取 + 逐卷导入，卷内/卷间断点续跑；
      真数据 259 块 / 776,043 字 → 2 卷，真 LLM 冒烟 2 卷 18 点、重跑零抽取。
      工单 `变更工单-2026-10-29-超大书分卷摄取.md`；口径核实见 `调研-2026-10-29-PDF取文口径.md`。

## P2 · 服务化与多端（按架构文档 §7 推进）

- [~] **P1 局域网访问**：`server_host` 放开 + 白名单加内网段 + 固定 token + 登录页存 localStorage。
      判据：手机同网段打开首页、检索、点详情；写操作仍被 token 拦。
      **2026-10-29（批 98）先落了前端这一半**：820 px 断点（底部标签条 / 分类抽屉 / 预览浮层）+
      viewport —— 手机浏览器已经能用；**剩服务端三件**（`server_host`、白名单加内网段、固定 token）。
      注意：内网 `http://` 不是安全上下文，SW 在那条路上不注册（见下一行 PWA 的限制）。
- [ ] **P2 远程访问**：反向代理 TLS + 只读/可写两种 token + 限来源网段。
      判据：外网 HTTPS 可读；无 token 写操作 403。**这条也是手机离线 PWA 的前置（TLS 才有 SW）。**
- [x] **PWA 壳**：manifest + 图标 + 离线只读缓存。判据：手机主屏启动，断网能看上次的内容。
      2026-10-29 批 98 落地（`变更工单-2026-10-29-响应式与PWA壳.md`）：manifest/图标/favicon +
      `sw.js` 三策略（只读 API 网络优先+缓存回落、原文代理不进缓存、非 GET 直通）+ 顶栏「离线只读」徽标。
      实测 390×844：SW 注册、缓存 12 个外壳文件、把网络断在 SW target 上重载后页面照常打开、
      `/api/tree` 走缓存回 200、未缓存端点回 503 `{offline:true}`。**限制**：`http://<内网 IP>`
      下浏览器不注册 SW（只有「添加到主屏 + 全屏」），离线要等 P2 的 TLS。
- [ ] **桌面壳跨平台**：目前仅 Windows 实测；macOS/Linux 打包另开条目。

## P3 · 重构（已定路线 A，详见拆分方案）

按 `docs/design/方案-2026-10-27-四个大文件拆分.md` 执行，先后顺序即下方顺序：

- [x] 护栏：`test_web_routes.py`（73 条路由快照）、`test_cli_surface.py`、`test_datalayer_surface.py`（`cc0e556`）。
- [x] `cli.py` 775 → `cli/`（8 文件，`454ff1b`）。
- [x] `pipeline/sync.py` 861 → `pipeline/sync/`（6 文件，2026-10-28 01:3x）。
- [x] `web/api.py` 1,952 → `web/ctx.py` + `web/routers/`（7 域，2026-10-28 01:4x；`api.py` 103 行）。
- [x] `datalayer/db.py` 3,462 → `datalayer/`（2026-10-28 02:0x）：10 mixin + `core.py` + `_common.py`，`db.py` 12 行 façade；`_guard` 先改 MRO 扫描（`adb544c`）。路线 A 至此完成。

次要重构：

- [ ] 配置层：四类标注 + `kconfig check|show|docs`（见配置方案 §6 步骤 1–5）。
- [ ] `kpe_runner` 子进程契约化：`--version` 探测 + 可选 extra 依赖 + 失败码表。
- [ ] `kpe_import` 与 `kpe_runner` 产物解析去重（两处都在读 manifest/points.jsonl）。
- [ ] `docs/design/` 建索引页；已交付的工单移入 `archive/`（40+ 篇已影响检索）。
- [ ] `kaging --lifecycle --dry-run` 在存在技术栈分组时只打 `SKIP llm 未启用`，把 A 段统计一起吞了
      （2026-10-28 实跑踩到）：改成「打印统计 + 一行说明 B 段试跑不连 LLM，退出码仍 SKIP」。

## P2 · 文档自动化（三份参考已有初版，2026-10-27）

已产出（由 `temp/gen_docs_20261027.py` 生成）：`docs/参考-命令.md`（13 子命令）、
`docs/参考-配置.md`（59 键）、`docs/参考-接口.md`（73 端点，2026-10-28 加 `/api/tasks` 后 74）。

- [x] **把生成器提升为 `tools/gen_docs.py`**：带 `--check`（只比对不写，CI 用），
      并加 `tests/test_docs_in_sync.py` 断言三份文档与源码一致（2026-10-27 完成，716 passed）。
- [ ] 12 个端点缺 docstring（列表见 `docs/参考-接口.md` 文末），补一行说明即可。
- [ ] 三份参考接进 `docs/README.md` 索引与 README 的「参考」小节。
- [ ] 配置参考里的 I 类常量表随代码核对一次（`CleanThresholds`、`EOL` 的位置是否还准确）。

## P4 · 明确不做（防止反复讨论）

- 多用户/账号/权限矩阵——个人知识库，token 即身份。
- 客户端本地库 + 双向同步——多事实来源是净损失。
- 把 `clean` 的阈值做成可配置——那会让人把"洗不干净"调成默认。
- 用 Celery/Redis 替换内置 worker——单机单用户，拷一个 db 文件就能恢复是优势。
- 为移动端另写一套前端——同一套 SPA + 响应式 + 深链。
- **借 Cognee 的知识图模型 / OWL 本体 / 三库并置**（2026-10-28 调研裁决）：它把知识结构落成
  `Document→Chunk→Entity` 持久实体层，靠"先图后向量 + 回滚账本"兜一致性；正撞上我们 2026-10-21
  否掉的方向（实体层是"无底洞"，单 SQLite 单事务是优势而非欠账）。它的实体抽取成本是每 chunk 2 次 LLM，
  我们只在长文走 KPE 且 `--max-points` 封顶。
- **借 Cognee 的 `memify` / feedback 学习型权重**：它自己 `feedback_influence` 默认 0、memify 已标弃用、
  `TRIPLET_COMPLETION` 已删；我们维持"人工裁决 + 可解释否决"，不做学习型边权。
- **Cognee 那三条小改进**（`runs.stats` 记 tokens / 检索加 `thread_id` 过滤 / 边理由白名单）：
  2026-10-28 裁决 **不做**——三条都要动契约或新增机制，而当前 P1 判据（点层质量、KPE 实跑、巡检）
  都用不上；哪天真要做，单独开单，别夹带进别的批次。

## 附：判定为"不做但记录"的问题（来自真实数据）

| 现象 | 为什么先不做 |
|---|---|
| 82 条 archived、78 条 rejected 长期不动 | 物理删除有 30 天冷却与人裁出口，属正常蓄水池 |
| 2,016 条 opinion 点 | 观点不需要勘误/老化，保留就是价值 |
| 914 条 unjudgeable | 分诊结论本身是信息；重判要看 LLM 口径变更，不划算 |
| 分类只有 3 个一级 | 分类树是人工资产，扩树应跟随真实使用，不为"整齐"造分类 |