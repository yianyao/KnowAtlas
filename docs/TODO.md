# TODO（KnowAtlas，2026-10-27 重排）

> 排序原则：**能让人少操作 > 能让数据更对 > 能让代码更好改 > 能让界面更好用**。
> 每条都有「判据」——不写「优化性能」这种没有验收口径的条目。
> 现状与模块归属见 `docs/模块地图.md`；未来形态见
> `docs/design/架构-2026-10-27-服务化分层与服务端职责.md`。

## 0. 待你决策（阻塞后续规划，先别动代码）

### D1 工具是否都按 kpe 模式独立成仓库？

**建议：不要"都独立"，按三条判据分级。**

| 判据（同时满足 ≥3 条才独立） | 命中的候选 |
|---|---|
| ① 有独立消费者（脱离主库也能用） | kpe ✅、session-guard ✅、清洗器（可能） |
| ② 依赖重/可选/平台相关（不该拖累主装） | kpe（pdfplumber）✅、embedding 后端（可能） |
| ③ 输入输出是文件/HTTP，不是 Python 对象 | kpe ✅、导出器（可能） |
| ④ 有独立发布节奏与版本语义 | kpe ✅、session-guard ✅ |
| ⑤ 可离线单测（零 DB、零主配置） | kpe ✅、clean ✅、eol 表 ✅ |

结论（**Tier 策略**，写进后续规范）：

- **Tier A 独立仓库**（现在就两个）：`kpe`、`session-guard`。以后只增「文件进文件出 + 重依赖」的。
- **Tier B 内部包但禁反向依赖**（保留在主仓库，用 `__init__` 暴露稳定 API、测试隔离）：
  `clean`、`semantic/eol`、`semantic/embed`、`point_gate`、`domain_gate`、`export`。
- **Tier C 核心不动**：`datalayer`、`models`、`ids`、`errors`、`config`、`pipeline` 编排。

「脚本调脚本很乱」的真实原因不是目录，而是**三种调用方式混用**：Python import、子进程、
薄封装桥接。规范化为：核心走 import；外部工具走**子进程 + 显式版本契约**（`kpe --version` 探测、
不支持的能力自动降级）；桥接层只允许出现在 `tools/`。

### D2 冻结当前项目、参照它重做一个新的？

**建议：不冻结、不重写；用「绞杀者模式」逐域抽薄。**

- 重写会丢掉**只能从真实语料里长出来**的东西：清洗阈值（5.9 M 字符量出来的）、
  闸门口径（裸名词/截断的边界）、EOL 表判据、4,965 个真实点背后的分类树与勘误结论。
- 现有资产是可继承的：16.5k 行、687 个测试函数（715 例）、10 个迁移、canary 契约。
- 真正"乱"的只有 4 个巨型文件（`db.py` 3,194 / `api.py` 1,799 / `sync.py` 782 / `cli.py` 775），
  占全库 36%。**只拆这四个**，不动领域逻辑，收益最大风险最低。

若你仍想"新项目"，建议形态是**同一仓库内的 v2 垂直切片**：新目录 `src/knowatlas2/`
只复用 `datalayer`（通过复用同一 DB）+ 测试，先实现「读路径」，跑通后再迁移写路径。
这比"新建仓库复制粘贴"安全，也比"原地重构"激进——但它需要 2–3 周，且期间功能冻结。

**需要你选一个**：A 只拆四个大文件（推荐，1–2 天/个）｜B 原地分层重构（按域抽包，1–2 周）｜
C v2 垂直切片（2–3 周，功能冻结）｜D 冻结重建（不推荐）。

### D3 是否把「工具边界规范」写成 ADR？

建议：在 `docs/design/` 加一篇《ADR-工具边界与独立判据》，把 D1 的三条判据与 Tier 策略
固定下来，以后新工具照此裁决，避免又长出一个"脚本调脚本"。

## P0 · 正确性与风险（本周内）

- [ ] **真库实跑一轮巡检**：导入三个用户级 key → `kauto --limit 3` → 确认 `split>0`、
      `points_created>0`，抽查 3 条 `meta.ingest`（route/reason/at）。
      判据：3 条都有正文 hash + 点；无 `dead`；`task_log` 有 `kauto` 记录。
- [ ] **待审 132 条落定**：先 `kauto --activate-only --dry-run` 复核名单（97 激活 / 35 拒绝），
      再实跑 `kauto --activate-only`。判据：pending 归零；35 条 `value_flag_reason` 可解释。
- [ ] **打开 serve 巡检**：`config/knowatlas.toml` 加 `[ingest] enabled = true`，
      `serve` 后确认日志「入库巡检启动：每 600s 一轮」。判据：跑满两轮无异常、无双写冲突。
- [ ] **R17 界面验收**（一直挂着）：Ctrl+F5 后看「打开原文」与分类页「按主题」是否正常。

## P1 · 功能补全（两周内）

- [ ] **`GET /api/tasks`**：上一轮巡检/老化的时间、条数、错误数；管理页加一块"任务"卡片。
      判据：巡检跑完后页面 10 秒内可见，不需要翻日志。
- [ ] **点层补作业**：413 条无 `kind` 的点跑 `kpoints --triage`；hard 1,579 条跑
      `kaging --lifecycle`（A 段零费用）。判据：无 kind 点 < 50；`aging_flag` 不再全空。
- [ ] **点质量抽检**：随机 30 条点看「能否脱离原文读懂」。判据：合格率 ≥ 80%，
      不合格样本进回归集。
- [ ] **KPE 实跑验收**：挑一本真 PDF 走 `kauto` 的 KPE 通道（`kpe_max_chars` 内），
      确认 `--max-points 6` 生效、`chunk_count` 与点数写入 `meta.ingest`。
- [ ] **配置示例同步**：`config/knowatlas.example.toml` 已加 `[ingest]/[points]/[aging]`，
      补一句「kauto 与 serve 巡检共用同一组键」到 SOP。

## P2 · 服务化与多端（按架构文档 §7 推进）

- [ ] **P1 局域网访问**：`server_host` 放开 + 白名单加内网段 + 固定 token + 登录页存 localStorage。
      判据：手机同网段打开首页、检索、点详情；写操作仍被 token 拦。
- [ ] **P2 远程访问**：反向代理 TLS + 只读/可写两种 token + 限来源网段。
      判据：外网 HTTPS 可读；无 token 写操作 403。
- [ ] **PWA 壳**：manifest + 图标 + 离线只读缓存。判据：手机主屏启动，断网能看上次的内容。
- [ ] **桌面壳跨平台**：目前仅 Windows 实测；macOS/Linux 打包另开条目。

## P3 · 重构（选 D2 的路线后再排期）

不论选哪条，这四件事优先级最高（都是"拆大文件"，行为不变、测试兜底）：

- [ ] `web/api.py` 1,799 → `web/routers/{entries,categories,points,graph,threads,search,write}.py`
      + `web/deps.py`。判据：每个 router < 400 行；`test_web_api.py` 不改断言全绿。
- [ ] `datalayer/db.py` 3,194 → 按表分 `datalayer/{entries,categories,points,vectors,threads,content,runs}.py`，
      `DataLayer` 组合 mixin，公开方法签名与 SQL 逐字不变。判据：canary 零漂移、全量测试全绿。
- [ ] `pipeline/sync.py` 782 → `sync/{walk,fetch,categorize,archive}.py`，`run_sync` 留编排壳。
- [ ] `cli.py` 775 → `cli/{entries,points,aging,ops}.py` + 一个注册表。
- [ ] （配套）`tests/` 同步拆；大文件测试是重构时最容易变成瓶颈的地方。

次要重构：

- [ ] 常量收口：`points.py`/`aging.py`/`clean.py` 里的阈值逐步进配置（已有 `[points]/[aging]` 先例）。
- [ ] `kpe_runner` 子进程契约化：`--version` 探测 + 可选 extra 依赖 + 失败码表（现在是"探测失败就省略参数"）。
- [ ] `kpe_import` 与 `kpe_runner` 产物解析去重（两处都在读 manifest/points.jsonl）。
- [ ] `docs/design/` 建索引页；已交付的工单移入 `archive/`（40+ 篇已影响检索）。

## P4 · 明确不做（防止反复讨论）

- 多用户/账号/权限矩阵——个人知识库，token 即身份。
- 客户端本地库 + 双向同步——多事实来源是净损失。
- 把 `clean` 的阈值做成可配置——那会让人把"洗不干净"调成默认。
- 用 Celery/Redis 替换内置 worker——单机单用户，拷一个 db 文件就能恢复是优势。
- 为移动端另写一套前端——同一套 SPA + 响应式 + 深链。

## 附：判定为"不做但记录"的问题（来自真实数据）

| 现象 | 为什么先不做 |
|---|---|
| 82 条 archived、78 条 rejected 长期不动 | 物理删除有 30 天冷却与人裁出口，属正常蓄水池 |
| 2,016 条 opinion 点 | 观点不需要勘误/老化，保留就是价值 |
| 914 条 unjudgeable | 分诊结论本身是信息；重判要看 LLM 口径变更，不划算 |
| 分类只有 3 个一级 | 分类树是人工资产，扩树应跟随真实使用，不为"整齐"造分类 |