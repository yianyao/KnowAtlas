# TODO（KnowAtlas，2026-10-27 重排）

> 排序原则：**能让人少操作 > 能让数据更对 > 能让代码更好改 > 能让界面更好用**。
> 每条都有「判据」——不写「优化性能」这种没有验收口径的条目。
> 现状与模块归属见 `docs/模块地图.md`；未来形态见
> `docs/design/架构-2026-10-27-服务化分层与服务端职责.md`。

## 自主运行口径（2026-10-27 夜，用户授权「做好 todo 后自己开工」）

**执行顺序**（每步 = 一个 commit + 推送，跑完全量再进下一步）：

1. ✅ 生成器转正（2026-10-27 23:50）：`tools/gen_docs.py`（`--check` 只比对不写）+
   `tests/test_docs_in_sync.py`；全量 **716 passed / 1 skipped**。`temp/gen_docs_20261027.py` 可删。
2. ✅ 护栏（2026-10-28 00:0x）：`test_web_routes.py`（73 端点）、`test_cli_surface.py`（13 子命令）、
   `test_datalayer_surface.py`（127 个公开方法）；全量 **720 passed / 1 skipped**，且已验证"故意改坏会红"。
3. `cli.py` → `cli/`（7 文件）。
4. `pipeline/sync.py` → `pipeline/sync/`（5 文件）。
5. `web/api.py` → `ctx.py` + `routers/`（7 域）。
6. `datalayer/db.py` → `datalayer/`（10 文件 + mixin；**先验证 `_guard` 的 MRO 扫描**）。

**每步固定验收三条**：

```powershell
uv run python -m pytest -o addopts= -q          # 期望 715 passed / 1 skipped（新增护栏后条数会增加）
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

## P3 · 重构（已定路线 A，详见拆分方案）

按 `docs/design/方案-2026-10-27-四个大文件拆分.md` 执行，先后顺序即下方顺序：

- [ ] 护栏：`test_web_routes.py`（71 条路由快照）、`test_cli_surface.py`、`test_datalayer_surface.py`。
- [ ] `cli.py` 775 → `cli/`（7 文件）。
- [ ] `pipeline/sync.py` 782 → `pipeline/sync/`（5 文件）。
- [ ] `web/api.py` 1,799 → `web/ctx.py` + `web/routers/`（7 域）。
- [ ] `datalayer/db.py` 3,194 → `datalayer/`（10 文件 + mixin；**注意 `_guard` 的 MRO 扫描坑**）。

次要重构：

- [ ] 配置层：四类标注 + `kconfig check|show|docs`（见配置方案 §6 步骤 1–5）。
- [ ] `kpe_runner` 子进程契约化：`--version` 探测 + 可选 extra 依赖 + 失败码表。
- [ ] `kpe_import` 与 `kpe_runner` 产物解析去重（两处都在读 manifest/points.jsonl）。
- [ ] `docs/design/` 建索引页；已交付的工单移入 `archive/`（40+ 篇已影响检索）。

## P2 · 文档自动化（三份参考已有初版，2026-10-27）

已产出（由 `temp/gen_docs_20261027.py` 生成）：`docs/参考-命令.md`（13 子命令）、
`docs/参考-配置.md`（59 键）、`docs/参考-接口.md`（73 端点）。

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

## 附：判定为"不做但记录"的问题（来自真实数据）

| 现象 | 为什么先不做 |
|---|---|
| 82 条 archived、78 条 rejected 长期不动 | 物理删除有 30 天冷却与人裁出口，属正常蓄水池 |
| 2,016 条 opinion 点 | 观点不需要勘误/老化，保留就是价值 |
| 914 条 unjudgeable | 分诊结论本身是信息；重判要看 LLM 口径变更，不划算 |
| 分类只有 3 个一级 | 分类树是人工资产，扩树应跟随真实使用，不为"整齐"造分类 |