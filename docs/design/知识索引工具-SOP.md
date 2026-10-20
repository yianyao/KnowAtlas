---
title: 个人知识统一索引与分类导航工具 · SOP
summary: 环境准备、日常同步与备份、手动添加链接（kadd）、新增知识源/语义任务/分类校正/LLM 切换/数据导出的标准操作流程、常见故障处理、新机器迁移与变更管理纪律
date: 2026-10-19
status: 定稿
reader: 操作者（人）与承接 agent
---

# 个人知识统一索引与分类导航工具 · SOP

配套文档：handoff/知识索引工具-设计方案.md（为什么这么做）、handoff/知识索引工具-完整方案.md（工程契约定稿，编码依据）、handoff/知识索引工具-TODO.md（建设任务）。

本 SOP 中所有路径均为项目根相对路径；`<project-root>` 指本工具自身的代码仓库根目录。机器相关路径一律走配置文件，换机只改配置不改代码。

## 0. 章节 ↔ 里程碑可用性映射（2026-10-19 补）

本 SOP 是**运维手册**，不承担"最小实现"的规划——最小实现路径在 TODO Phase 0.5（M0.5 垂直切片）与完整方案 §12 步骤 1–8。本节只回答一个问题：**进行到哪个里程碑，SOP 的哪些章节可用**，避免在早期阶段照着后期章节操作踩"命令还不存在"。

| SOP 章节 | 最早可用里程碑 | 说明 |
|---|---|---|
| §10 变更管理纪律 | Phase 0 起 | 全程生效（不依赖工具本体） |
| §1 环境准备 | M0.5 | 骨架建成即有；此时 ksync 仅覆盖 manual 源 |
| §2.4 kadd（手动链接） | M0.5 | 第一个垂直切片的核心入口 |
| §2.1 增量同步 / §2.3 健康检查 | M0.5 | ksync 骨架即有；删除检测等完整语义 M1 起逐源生效 |
| §3 新增知识源（SOP-A） | M1 起 | 每接入一个新源走一遍 |
| §4 新增语义任务（SOP-B） | 规则级 M0.5 / LLM 级 M4 | classify_coarse 的 L1/L2（先验/规则）在 M0.5 已有最小实现；LLM 兜底 M4 |
| §5 分类校正（SOP-C） | M1 | 人工校正 UI 与分类树同批交付 |
| §6 LLM 配置切换（SOP-D） | 云端 M2 / 完整三模式 M4 | 云端 API 配置 M2 可先接；本地模型与纯规则降级 M4 |
| §7 数据导出（SOP-E） | M5 | 三个导出格式均在 Phase 5 |
| §2.2 备份与恢复 | M5（自动）/ M0.5（手动兜底） | kbackup 与同步前自动快照在 Phase 5；此前手动拷 `data/` 兜底（停服务后拷） |
| §8 常见故障处理 | 随各源/能力接入逐行生效 | 每行标注的能力可用后才可能触发 |
| §9 迁移到新机器（SOP-F） | M0.5 起 | 每个里程碑后重验一次 |

---

## 1. 环境准备

### 1.1 前置条件

- 单用户本地使用；Python 3.13；能访问 127.0.0.1。
- 各知识源凭证（IMA Client ID/API Key、腾讯文档 OpenAPI 应用、IMAP 账号、PostgreSQL 连接串、DeepSeek API key、B站 SESSDATA、公众号扫码登录等）先准备好，但**不要**写进任何代码或文档。

### 1.2 创建隔离环境并装依赖

```bash
# 在 <project-root> 下执行
python -m venv .venv
# Windows: .venv/Scripts/python.exe -m pip install -r requirements-core.txt
# macOS/Linux: .venv/bin/python -m pip install -r requirements-core.txt
.venv/Scripts/python -m knowatlas kinit   # 初始化数据层：建表 + 注册内置能力
```

（命令形态以完整方案 §7 为准：`python -m knowatlas <子命令>`；`kinit` 一条命令完成建表与内置能力注册。）

依赖分组（requirements 分文件，按需安装，避免默认拖入重依赖）：

- `requirements-core.txt`：fastapi、uvicorn、httpx、jieba、readability-lxml、markitdown、pdfplumber、pytest
- `requirements-optional.txt`：sentence-transformers、psycopg[binary]（本地 embedding / PostgreSQL 源启用时才装）
- 微信聊天记录、公众号扒取：外部工具（WeChatMsg/MemoTrace 活跃 fork、wechat-article-exporter），不走 pip，按其项目文档独立部署，产物落固定目录后由主工具扫描

### 1.3 配置文件

- 位置：`config/knowatlas.toml`（完整方案 §6 已定稿 TOML 格式）。
- 内容：各源的根目录/路径、凭证占位、LLM 端点、抓取后端（simple / deepseek）、备份目录。
- 纪律：
  - 配置文件入 `.gitignore`；仓库内只提交 `config/knowatlas.example.toml`（占位符版本）。
  - 凭证只从环境变量或本地配置文件读取，支持 `KNOWATLAS_*` 环境变量覆盖，便于换机。
  - 任何机器特定路径（用户目录、盘符）禁止硬编码，一律由"配置根目录 + 相对路径"推导。

### 1.4 首次全量同步

```bash
.venv/Scripts/python -m knowatlas ksync --full
```

预期：`data/` 下生成 SQLite 数据层；日志显示每个适配器的条目数；`task_log` 有首次导入记录。任何适配器报错不影响其他适配器（隔离原则）。

---

## 2. 日常操作

### 2.1 增量同步

```bash
.venv/Scripts/python -m knowatlas ksync --incremental
```

两类同步策略（完整方案 §3.6 定稿）：**全量遍历型源**（书签/文件夹/脑图/B站/AI 会话/数据文件/微信产物）每次全量拉取 + 幂等差分 + **删除检测**——源侧已删的条目标记 archived 进归档区，不物理删除；**游标型源**（邮件/IMA/腾讯文档）按各自游标增量。建议频率：每周一次手动，或按需；不追求实时——本工具是索引层，不是同步引擎。

### 2.2 备份与恢复

- 自动：每次同步前对 SQLite 做快照（**VACUUM INTO**，禁止直接拷主库文件——WAL 模式下可能丢已提交事务），`data/backups/` 下保留最近 10 份，超出轮换删除。
- 手动：

```bash
.venv/Scripts/python -m knowatlas kbackup --snap
```

- 恢复：停服务 → 用快照覆盖 `data/` 下数据层文件 → **删除同目录 `-wal` / `-shm` 文件**（旧 WAL 回放会污染新库）→ 重启 → 跑 `--incremental` 校验条目数与快照时一致。

### 2.3 健康检查

```bash
.venv/Scripts/python -m knowatlas ksync --dry-run
```

每个适配器只探测"源是否可达、凭证是否有效、格式是否仍可解析"，不写数据。新增源或换机后先跑此项。

### 2.4 手动添加链接（kadd）

看到一篇好文章，直接把它丢进工具，不等同步周期：

```bash
.venv/Scripts/python -m knowatlas kadd https://example.com/article   # 单条
.venv/Scripts/python -m knowatlas kadd url1 url2 url3               # 多条
```

抓取纪律（K1）：**同步默认不抓正文**（`fetch.on_sync=false`）——标题级已能进树和检索；正文只在 kadd、用户点"抓取"、或 `ksync --fetch-limit N` 时获取，避免几千条书签一次性烧完抓取配额与计费。

行为链：建条目（source_type=manual）→ 入"未分类"暂存区 → 调 http 获取器抓正文（默认 simple 后端，失败/正文过短自动升 DeepSeek Fetch）→ 跑语义分类 → 出现在分类树对应分支。已收藏过的 URL（canonical 规范化后命中 `locator_canonical`）自动合并，不重复建条目。

Web UI 同等功能：首页输入框粘贴 URL 即可；浏览器 bookmarklet（在页面上拖动到书签栏）可把当前页面一键送入本地服务——no-cors POST 需带 token（query 参数 `?token=`，值取 `KNOWATLAS_WEB_TOKEN`）。手动入口与书签走完全相同的抓取 → 归类链路，不新增任何机制。

### 2.5 串联工作区（主题聚合 + 线索，0.2.0 第三十二批）

痛点场景：「知道要什么，但相关知识散落在书签/文件/脑图多个源里，串不起来」。

入口：Web UI 侧栏「🧵 串联工作区」（`/thread.html`）；首页检索结果下方有「🧵 固化为线索」按钮。

两类用法：

1. **主题召回**（不知道散落在哪）：在工作区输入主题词（如 `Python 异步`）→ 多路召回
   聚合相关条目，每条带关联解释徽标——`全文命中` / `同分类:<路径>` / `同站点:<host>` /
   `同线索:<线索名>`；也支持节点 id 输入（`c:<分类id>` 焦点分类子树 / `e:<条目id>` 焦点条目）。
   召回是纯规则、零费用，不调 LLM。
2. **线索编排**（把散落的串成有序路径）：对命中条目点「＋加入线索」，或把任何检索结果
   「固化为线索」。线索内可：调顺序（↑↓）、设条目间关系（顺承/因果/前置/对比）、
   写备注、`✨ LLM 建议排序`（按「概念→步骤→注意事项」给初始序，可改；[llm] 未配置时
   自动原序降级，不阻塞）。

数据与审计：线索落 `threads` / `thread_items` 表（thread_type=curated；source 型预留
给邮件/AI 会话线程还原），增删移全部写 `task_log`（task_name=threads）。线索只引用条目
（entry_id），删线索不影响条目本身；删条目后线索内显示「（条目已不存在）」占位。

迁移说明：本批起 schema 支持多迁移按序应用（002_threads）——旧库首次打开自动升级，
无需手工操作；若见 `user_version 高于代码` 报错，说明库由更新版本创建，需升级 knowatlas。

---

### 2.6 关系图放射导航（探索发现，0.2.0 第三十三批）

痛点场景：「知道大概方向，想顺着线索探索发现遗漏的关联」。

入口：Web UI 侧栏「🕸️ 知识关系图」（`/graph.html`）。三视图主干不变（大类总览 →
搜索子图 → 分类下钻），其上叠加放射能力：

1. **放射模式**（勾选「放射模式」开关，默认关）：点任意节点出「焦点一跳邻域」——
   焦点黄标居中，每个邻域节点带关联解释（悬停可见）：`挂接:<来源>` / `父分类` /
   `子分类` / `同站点:<host>` / `同线索:<线索名>`；域名节点点击恒走放射。
   放射视图内点邻域节点可持续下钻；没解释的关联不会出现。
2. **面包屑**：总览/搜索/子树/放射统一压栈，顶栏面包屑任一级可回跳（防迷路）。
3. **展开更多**：每通道默认出 8 条，超出显示「N 条未显示」，点「展开更多」×3 扩容
   （封顶 40）——防毛球，不一次拉全。
4. **🔍 反查**：对当前焦点列出「哪些焦点能到达它」——分类（带路径，点击可跳）、
   域名、线索（跳串联工作区）。
5. **🏷 关联解释**开关：在边上常驻显示理由（默认关防噪，悬停 tooltip 恒显）。
6. **🧵 固化为线索**：把当前视图的条目一键存成线索，跳串联工作区继续编排
   （写操作，服务配置了 `KNOWATLAS_WEB_TOKEN` 时须携带令牌）。

数据边界：全部 relation_reason 由规则生成（共现/同源/显式关联），零 LLM 费用；
语义相似边随 M4 embedding 接入。空邻域（如无挂接的空分类）会明示「没有可放射的
邻域」，不造空节点。

---

### 2.7 统一入口工作台（检索三视图，0.2.0 第三十四批）

痛点场景：检索、串联、放射探索三个入口分散，要在三个页面间手动搬上下文。

入口不变：首页（`/index.html`）搜索框。输入主题词回车后，主区变成**工作台三视图**
（顶部切换条，模式是视图切换不是启动分叉）：

1. **聚合结果**（默认）：全文检索 ∪ 主题多路召回，按条目去重合并；每条带关联解释
   徽标（`全文命中` / `同分类:<路径>` / `同站点:<host>` / `同线索:<线索名>`），
   悬停可见原始 reason；右上「🧵 固化为线索」对合并后全量条目生效。
2. **线索**：当前结果所属线索聚合（名称 + 含当前结果 N 条，点击进串联工作区）；
   都不在任何线索里时明示并指路固化按钮。
3. **放射**：以命中第一条为焦点（或点「🎯 放射」自选），邻域按通道分组列表
   （挂接/同站点/同线索…各带解释），点「🎯 切焦点」持续下钻；
   「🕸️ 在图中打开」深链关系图直达放射（`graph.html?node=` 也支持手工拼）。

数据边界：聚合零新增 LLM 调用（复用 FTS 与 topic_recall 规则产物）；不建新表。
分类浏览/暂存区/待清理候选等既有视图不受影响——只有检索走工作台。

### 2.8 消费面守卫（0.2.0 第三十六批）

**判据**：条目要出现在知识消费页（关系图总览/子树下钻/搜索子图/放射/反查/路径固化、
首页检索与工作台、串联工作区），必须同时满足：`status='active'` +
`meta.value_flag != 'not_knowledge'`（非待清理）+ `meta.link_status != 'dead'`
（非永久失效；error=疑似临时不判死）。统一实现在 `db.py _consumable()` SQL 片段。

**空类剪枝**：总览只出子树内可消费条目 >0 的一级大类；子树下钻与放射 child 通道
剪无可消费条目的子类（焦点根与祖先链上下文保留）。

**不受影响的页面**：待清理候选、失效链接、归档/舍弃检索等管理页照常全量列出——
守卫只挡「消费」，不挡「管理」。条目被否决（value_flag=ok）或修好链接后自动回到消费页。

### 2.9 跨源去重（0.2.0 第三十八批）

**判据（确定性）**：canonical URL 五步规范化一致，或 content_hash（规范化文本）一致。
simhash 近似与 embedding 余弦后置（误合成本高于漏合，待真实需求驱动）。

**合并模型（只标不删）**：组内最早的可消费条目为主条目；副条目 locator 附挂到主条目
（`entry_locators`，双 locator 均可跳转）+ meta 打 `dedupe_master=主id`。副条目保留在库、
照常参与同步（meta 合并语义保标），消费面由 `_consumable` 统一隐藏；删掉两个 meta 键即恢复。

**两个入口**：
- 自动：每次 ksync 入库后对新/更条目判重（stats 里 `deduped` / `post_fetch_deduped`）；
- 手动存量扫描：`uv run python -m knowatlas ksync --dedupe-scan`（加 `--dry-run` 只出
  报告不写库）。扫描同时摘「死标」——主条目被舍弃/待清理/归档后，副条目自动回归消费面。

### 2.10 邮件源（maildir，0.2.0 第三十九批）

**接入方式（不碰邮箱凭证）**：先用外部同步工具（如 offlineimap）把邮箱落成本地
maildir，再在 `config/knowatlas.toml` 配置：

```toml
[sources.mail]
enabled = true
accounts = { work = { path = "D:/Mail/work" } }   # maildir 根目录
```

支持标准 maildir（cur/new/tmp）与一层子文件夹（文件夹名入 meta.mailbox），兼容
目录直落 .eml 的导出形态。报错「maildir 路径不存在/没找到 mailbox」时检查该 path。

**行为**：每封邮件 = 一个条目（source_key = 账号:Message-ID，重同步幂等）；正文双轨——
增量正文（剥引用后，检索/摘要干净）进 inline_content，全量正文进 content_store（FTS
完整）；同会话邮件（In-Reply-To/References 链或 Subject 归一一致）自动还原为
thread_type='source' 的会话线程（串联工作区可见，📮 前缀命名）。

**故障处理**：解析失败的邮件跳过并计数（stats.skipped_parse），不中断同步；单源上限
5000 封（超出计 stats.truncated，提高上限需改适配器 _MAX_MESSAGES）。

### 2.11 书签扩散抓取（0.2.0 第四十批）

**用途**：对一篇系列文章/教程目录里的书签，一把抓下**同一目录**的其余页面
（同一目录页同一主题）。

**用法（显式触发，不自动跑）**：

```bash
uv run python -m knowatlas ksync --expand <entry_id>            # 默认每轮最多 20 条
uv run python -m knowatlas ksync --expand <entry_id> --expand-limit 5
```

entry_id 可从条目详情/URL 里拿。种子必须是 http(s) 条目（书签/手动收录均可）。

**规则（纯规则可解释）**：只收种子页内链接中与种子**同目录**者（同协议+域名+父目录
路径）；整站同域名链接不收（防变成全站爬取）。候选依次过：canonical 去重（含种子自身
与已入库条目，重复扩散零新建）→ L0 价值守卫（站点首页/列表子页/资源直链不抓）→
上限截断。新条目 source_type='expand'（UI 徽标「扩散」），meta 带 seed_entry_id
（可回溯种子）与 expand_reason='series_same_dir'（关联解释），正文进
content_store 并照常走分类链路。

---

## 3. 新增一个知识源（SOP-A）

原则：新源 = 一个新文件 + 一条注册，不改主流程。

1. **建适配器文件**：`src/adapters/<source>.py`，实现统一输出：条目列表（字段见设计方案 §5.2）。
2. **定 locator scheme**：若源产生新的定位类型，新增 scheme 并在 fetchers 注册对应 handler（按需，可后补）。
3. **写 fixture 测试**：`tests/fixtures/<source>/` 放样本原始文件（脱敏）+ 期望条目数/字段断言。
4. **小批量试跑**：`--source <source> --limit 50`，人工抽查 10 条：title/locator/native_path 是否正确。
5. **先验映射**：在 `src/semantic/priors.py` 的映射表补该源的 native_path → 分类分支规则。
6. **全量跑一次**，对账：源侧条目数 = 数据层条目数。
7. **登记与提交**：更新 TODO 的源清单状态；提交前跑仓库 pre-commit 与字节扫描（见 §10）。

验收：条目全部进数据层；先验路径映射正确；`task_log` 有导入记录；适配器抛错不影响其他源。

---

## 4. 新增一个语义任务（SOP-B）

1. **实现 processor**：`src/semantic/tasks/<task>.py`，签名遵循注册表契约（输入"标题 + 正文（可空）"，输出分类路径/标签/摘要）。
2. **注册**：在 Semantic Task 注册表登记 name / input_contract / output_contract / version。
3. **小批量试跑 + 人工抽样**：抽 20 条看结果，记录错误类型。
4. **回归**：用回归测试集（人工确认的 50-100 条）跑通过率，未达阈值不上全量。
5. **全量跑**：每次调用写 `task_log`（task_name、输入摘要、输出），保证可回溯、可重放。

验收：输出可复现（同输入同输出）；回归集通过率记录在案；日志完整。

---

## 5. 分类校正（SOP-C，人工回路）

1. 在分类树选中类目 → 右侧条目列表。
2. 对错误条目：拖拽改类 / 批量改类 / 合并重复分类（`merge_categories`）/ 移动分类位置（`move_category`）/ 挂接多父（`attach_parent` / `detach_parent`）——均有 DataLayer 方法，UI 只是薄封装。
3. 保存即写 `task_log`（action=retag/merge/move/attach_parent，detail 含前后值）。
4. 每周导出本周校正记录 → 挑选典型样本补进 few-shot 与回归集 → 更新规则库。
5. 对"未分类"暂存区：每周清一次，要么归类，要么明确归档（status=archived）。

纪律：校正只改数据层，不改原始源；任何分类结构变更必须可从 task_log 复现。

---

## 6. LLM 配置切换（SOP-D）

三种模式，只改配置、重启任务，不动数据层：

| 模式 | 配置 | 适用 |
|---|---|---|
| 云端 API（默认） | `llm.base_url = <云端 OpenAI 兼容端点>` + API Key 走环境变量（与 DeepSeek Fetch 可共用同一 key） | 默认模式（2026-10-19 定稿） |
| 本地模型 | `llm.base_url = http://127.0.0.1:11434/v1`（Ollama）+ `embedding.model = 本地 bge-m3 路径` | 数据不出本机时切换；需装 requirements-optional |
| 纯规则 | `llm.enabled = false` | LLM 不可用时的降级；先验 + 规则仍产出基础分类 |

切换后先跑回归集（`python -m knowatlas ktest regress`），通过再全量。

---

## 7. 数据导出（SOP-E）

```bash
.venv/Scripts/python -m knowatlas kexport --format json     # 全量 JSON（Schema 版本化）
.venv/Scripts/python -m knowatlas kexport --format obsidian # 条目笔记 + 分类 MOC 笔记
.venv/Scripts/python -m knowatlas kexport --format opml     # 书签类条目往返格式
```

导出是数据层的投影，不碰原始源。Obsidian 导出后可直接用现有笔记工具打开，作为防锁定出口。

---

## 8. 常见故障处理

| 现象 | 原因 | 处理 |
|---|---|---|
| IMA 同步失败，提示凭证无效 | Client ID/API Key 过期或失效 | 按官方渠道重新获取，更新配置后 `--dry-run` 验证 |
| 腾讯文档同步报 429 | 触发频率限制（约每分钟 100 次） | 自动队列降速已内置；持续失败则临时调大间隔，日志记录跳过条目下次补 |
| DeepSeek Fetch 报 429 | 账号级 5 QPS 或域名级限制 | 指数退避重试；已抓内容按 hash 缓存不重复计费；持续失败自动降级 simple 后端 |
| B站同步失败，报 72010002 或 -403 | SESSDATA 过期或失效（有效期约 30 天） | 浏览器登录 B站 → F12 → 应用 → Cookies → 复制 SESSDATA 新值 → 更新对应环境变量 → `--dry-run` 验证；旧条目保留不删 |
| kadd 粘贴的链接抓不到正文 | 页面需登录或反爬 | 该条目标记 fetch_failed，标题级入树；simple 与 DeepSeek 均失败的 URL 记录到日志，供人工补内容 |
| 公众号扒取中断，提示登录态失效 | wechat-article-exporter 扫码登录过期 | 重新扫码登录后重跑；主流程不受影响（独立脚本隔离） |
| 微信聊天记录导出失败 | 所选 fork 与微信版本不匹配 | 换活跃 fork 或对应版本；产物目录契约不变，主工具按文件源扫描不受影响 |
| 微信收藏（链接路线）拉取失败 | exporter 登录态失效或防盗链 | 独立脚本问题，主流程不受影响；修复后重跑；收藏条目本身不依赖解密，始终可用 |
| .emmx 解析不出节点文本 | 节点在 page.bin 二进制中 | 该文件降级为标题级条目，日志标记 `degraded=true`；不阻塞同步 |
| 中文全文搜索不准 | FTS5 分词问题 | 确认 tokenize=trigram；关键词统计走 jieba；两者不混用 |
| 条目数对不上 | 源侧变更未被增量捕获 | 对该源单独 `--full` 重导，比对前后差异 |
| task_log 缺失某次分类 | 直接改库绕过接口 | 属防腐化纪律违例；查代码路径，改为走数据层接口 |
| 条目突然进了归档区 | 源侧已删除该书签/收藏（删除检测置 archived，detail 记 `missing_in_source`） | 非故障；确认源侧确实删除即可；误判可手动恢复 status=active |
| Web 写操作返回 403 | Host/Origin 不在白名单，或缺 `X-KnowAtlas-Token` 头 | 从 `http://127.0.0.1:<port>` 访问（勿用其他主机名/IP）；确认环境变量 `KNOWATLAS_WEB_TOKEN` 已设置且请求带了 token |

---

## 9. 迁移到新机器（SOP-F）

判据（铁律）：换一台新机器 + 新用户名，按本节能原样跑起来。

1. 克隆项目到新机任意路径（无硬编码路径依赖）。
2. 按 §1.2 建 venv 装依赖（按需装 optional 组）。
3. 复制配置文件模板，按新机实际位置填写各源根目录与凭证（唯一需要人工改的东西）。
4. `python -m knowatlas ksync --dry-run` 验证各源可达。
5. `python -m knowatlas ksync --full` 全量同步，与迁移前条目数对账。
6. 需要历史数据时，拷贝 `data/` 下 SQLite 文件与 `content_store`，再跑 `--incremental` 补齐。

若上述任一步需要改代码，即为违反可迁移铁律，记录到 TODO 并修复。

> **换机前必读**：`docs/迁移踩坑清单.md`——本机实踩过的依赖/Windows/代理/并发/
> LLM 密钥坑（含 markitdown 裸装导致 Office 解析全废、uv venv 无 pip、全局代理
> 劫持 localhost 请求等），每条都是真实踩过的，换机会原样再踩。

---

## 10. 变更管理纪律

1. **改文件先写工单**：旧 → 新摘要 + 复检探针，逐条落盘即时改状态（中断可恢复）。
2. **改后探针复检**：全命中才关单。
3. **落盘格式**：UTF-8 无 BOM + LF；收尾扫描确认无 CRLF。
4. **提交前**：跑仓库 pre-commit；不跳过钩子。
5. **关联件同步**：更新任一文件前先扫其关联件（索引/清单/指针/版本号引用），逐处同步，不留旧指针。
