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
| §7.7 知识模型升级操作（Phase 7） | M7 批次逐个落地后生效 | 规划预置节——命令随实现批次进 SOP |

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
  - **数据根 `KNOWATLAS_HOME`（0.2.0 第五十三批）**：设了该环境变量后，配置里的
    相对路径（默认 `data/knowledge.db`、`data/backups`）全部挂到它下面——推荐
    设为用户目录（如 `C:\Users\<你>\.knowatlas`），代码与数据彻底分离，换机/装
    wheel 后 cwd 不定也不影响数据位置；不设则保持相对 cwd（仓库内使用现状）。
    绝对路径配置永远原样。本机已设并完成一次性迁移（2026-10-21）。

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

Web UI 同等功能：首页「🛠 数据管理」输入框粘贴 URL 即可；浏览器 bookmarklet（同区的「📮 收藏小书签」拖到书签栏）在任意网页点击即跳回本地服务 `index.html?add=<当前页URL>`，页面自动展开收录框并复用手动收录链路提交（2026-10-21 第 49 批落地）。写凭据走同源会话 Cookie——令牌不进书签栏、任何第三方网页拿不到；本工具 CORS 不放宽，不做跨站 no-cors POST。手动入口与书签走完全相同的抓取 → 归类链路，不新增任何机制。

### 2.5 线索库（主题聚合 + 线索，0.2.0 第三十二批；原名「串联工作区」，2026-10-22 用户定调改名）

痛点场景：「知道要什么，但相关知识散落在书签/文件/脑图多个源里，串不起来」。

入口：首页页签「🧵 线索库」（`/thread.html`）；检索工作台右上「🧵 固化为线索」按钮。

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
   域名、线索（跳线索库）。
5. **🏷 关联解释**开关：在边上常驻显示理由（默认关防噪，悬停 tooltip 恒显）。
6. **🧵 固化为线索**：把当前视图的条目一键存成线索，跳线索库继续编排
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
2. **线索**：当前结果所属线索聚合（名称 + 含当前结果 N 条，点击进线索库）；
   都不在任何线索里时明示并指路固化按钮。
3. **放射**：以命中第一条为焦点（或点「🎯 放射」自选），邻域按通道分组列表
   （挂接/同站点/同线索…各带解释），点「🎯 切焦点」持续下钻；
   「🕸️ 在图中打开」深链关系图直达放射（`graph.html?node=` 也支持手工拼）。

数据边界：聚合零新增 LLM 调用（复用 FTS 与 topic_recall 规则产物）；不建新表。
分类浏览/暂存区/待清理候选等既有视图不受影响——只有检索走工作台。

### 2.8 消费面守卫（0.2.0 第三十六批）

**判据**：条目要出现在知识消费页（关系图总览/子树下钻/搜索子图/放射/反查/路径固化、
首页检索与工作台、线索库），必须同时满足：`status='active'` +
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

**接入方式（不碰邮箱凭证）**：先把邮箱落成本地 maildir，再在 `config/knowatlas.toml`
配置：

```toml
[sources.mail]
enabled = true
accounts = { work = { path = "D:/Mail/work" } }   # maildir 根目录
```

**邮箱怎么变成 maildir（两条路，任选）**：

- **路 A：手动导出 .eml（零工具，适合少量）**——邮箱客户端/网页版里把邮件
  另存为 .eml 文件（Outlook：拖拽到文件夹即 .eml；Foxmail：导出邮件选 .eml；
  网页版如 QQ 邮箱：下载原始邮件），全部放进一个目录，把该目录配成上面的
  `path` 即可。适配器兼容「目录直落 .eml」形态，也支持一层子文件夹
  （文件夹名入 meta.mailbox）。
- **路 B：offlineimap 自动同步（适合持续增量）**——开源工具（GPLv2，独立进程
  使用无传染问题），IMAP 拉取落标准 maildir：

  ```ini
  # offlineimaprc 最小示例
  [general]
  accounts = work
  [Account work]
  localrepository = work_local
  remoterepository = work_remote
  [Repository work_local]
  type = Maildir
  localfolders = D:/Mail/work
  [Repository work_remote]
  type = IMAP
  remotehost = imap.example.com
  remoteuser = you@example.com
  remotepassfile = D:/Mail/work.secret   # 密码放文件，不进仓库
  ```

  跑 `offlineimap -c offlineimaprc` 即落 maildir；凭证归 offlineimap 管，
  KnowAtlas 只读它产出的目录（权限最小面不变）。

支持标准 maildir（cur/new/tmp）与一层子文件夹（文件夹名入 meta.mailbox），兼容
目录直落 .eml 的导出形态。报错「maildir 路径不存在/没找到 mailbox」时检查该 path。

**行为**：每封邮件 = 一个条目（source_key = 账号:Message-ID，重同步幂等）；正文双轨——
增量正文（剥引用后，检索/摘要干净）进 inline_content，全量正文进 content_store（FTS
完整）；同会话邮件（In-Reply-To/References 链或 Subject 归一一致）自动还原为
thread_type='source' 的会话线程（线索库可见，📮 前缀命名）。

**故障处理**：解析失败的邮件跳过并计数（stats.skipped_parse），不中断同步；单源上限
5000 封（超出计 stats.truncated，提高上限需改适配器 _MAX_MESSAGES）。

### 2.14 OPML 导入源（0.2.0 第五十批）

**用途**：外部工具导出的 OPML 大纲文件（其他书签工具/阅读器迁移过来），或
本工具 `kexport --format opml` 产物回吃（换机/重建库时把书签类条目搬回来）。

```toml
[sources.opml]
enabled = true
files = ["D:/Imports/书签.opml"]   # 文件路径数组，可多个
```

**口径**：outline 嵌套 → `native_path`（免费分类信号，走先验映射；不命中进
暂存区，不硬猜）；只收有 `htmlUrl` 的 http(s) 条目——`type="rss"` 订阅源
（只有 `xmlUrl`）不是知识条目，跳过并计数；`created` 属性 ISO 8601（本工具
导出形态）与 RFC 822（OPML 2.0 惯例）都能解析，缺省置 NULL 不臆造；同一
URL 出现在多个分支各建一条（M2 跨源去重统一兜底）。文件改名 = 换源（旧条目
归档、新条目重建），尽量用稳定路径。条目照常走抓取（默认 `fetch.on_sync=false`
不抓）与分类链路。

---

### 2.15 页签化主视图（0.2.0 第五十九批）

首页（`/index.html`）自本批起为「顶栏 + 页签行 + 左栏」三层布局，六视图页签化、
各占全屏（深链不变：`/graph.html`、`/thread.html` 仍可直接打开，页签内以 iframe 内嵌）：

| 页签 | 内容 | 说明 |
|---|---|---|
| 检索（默认） | 全文/聚合/线索/放射工作台 + 分类浏览 | 搜索框上移顶栏，任何页签下都可检索 |
| 关系图 | graph.html 内嵌 | 首次点开才加载 |
| 线索库 | thread.html 内嵌 | 同上；检索「固化为线索」页签内直达 |
| 词云 | scoped cloud | 范围随左树焦点 |
| 时间线 | scoped timeline | 同上 |
| 管理 | 六个管理入口集中 | 暂存区/待清理/失效链接/时效候选/已舍弃/数据管理 |

- **收录入口**：顶栏「＋ 收录」按钮（对话框，同 kadd 链路：抓正文→归类→入树）；
  按钮悬停有用途说明。日常消费页从此无管理控件。
- **bookmarklet 左缘小书签坞**：默认收缩为左缘竖条（📮 收藏），悬停展开显示
  用途说明与拖取链接；拖拽过程中保持展开。`?add=<url>` 落地接收逻辑不变。
- **左栏**：只留分类树；默认收起、`[` 切换、偏好记 localStorage（第五十八批
  纪律保留），折叠按钮上移顶栏；「显示空分类」开关移入顶栏 ⚙ 菜单。
- **数据管理页新增源状态区**：`GET /api/sources`（只读）列 12 个知识源的配置
  状态（✓/—），只报布尔不回传路径/凭证；另有库内条目按来源统计与最近任务。

---

### 2.16 知识集分组检索（0.2.0 第六十批）

检索工作台「聚合结果」的列表形态升级（方案 §7.2a 组头信号化，用户裁决第 1 条）：

- **分层查询**：命中 ≤5 条 → 直接平铺给点；命中多 → 先给「知识集」分组概览
  （组头 + 成员数 + 代表条目摘句），组内条目卡片即下钻。
- **组头 = 成员内容自身信号，禁发明性命名**：共享词（组内**每条**正文都子串
  出现才上榜，jieba 抽词 + 可验证性硬闸，无 LLM 参与）、共享分类路径（组内
  每条都挂接）、共享站点 host、代表条目摘句。组头词可在组内任一条目验证。
- **聚合策略自动选择**（纯查询期计算，零数据风险）：≥2 条命中带向量 →
  语义贪心聚类（阈值 0.72，`ksync --cluster-report` 同款）；无向量
  （bge-m3 未装机/未 `ksync --embed`）→ 「主分类+同 host」结构聚合。
  均不成组或聚合失败 → 平铺兜底。
- **端点**：`GET /api/sets/group?ids=<逗号分隔 entry_id>`（只读，≤200 条），
  返回 `{mode: semantic|structural|none, threshold, groups[], singles[]}`。
- **sim 通道**：检索同时拉 hybrid 混合检索，语义命中带「语义相关 <余弦>」
  徽标（向量未启用时该路静默降级，无痕迹）。

---

### 2.17 关系图纯层级下钻（0.2.0 第六十一批，Phase 7 批次 63）

**用途**：关系图从大类逐层下钻（技术开发 → 前端 → javascript），不被一次
混显的子孙分类+条目糊脸（用户理念 4.1-4.3）。

**用法**：关系图页「层级模式」开关（默认开，localStorage 记忆）——点分类
只出下一级子分类（气泡=子树可消费条目数），继续点继续下；叶子层自动出条目；
非叶子层点「📋 显示条目」展开本子树条目（经典视图）。关掉开关即回到经典
混显视图（子孙+条目+祖先链）。放射/搜索/反查/固化线索不受影响。

---

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

### 2.12 时效守卫（0.2.0 第四十一批）

**用途**：把「过期的、容易误导的知识」清出来——与待清理候选（§2.8 价值守卫）
同构的只标不删模型。

**用法**：

```bash
uv run python -m knowatlas ksync --freshness-scan          # 全库体检打标
uv run python -m knowatlas ksync --freshness-scan --dry-run  # 只出报告不写库
```

**规则（纯规则、零费用、可解释）**：

| 结论 | 原因 | 信号 |
|------|------|------|
| stale（明确过期，退出消费面） | keyword | 标题含废弃词（已废弃/已过时/不再维护/deprecated 等），或正文自述（「本文已过期」「This page is outdated」句式） |
| suspect（疑似过旧，保留可见） | date_old | 正文可提取的最新日期（最后更新/发布/版权年份）早于 3 年前 |
| suspect | newer_version | 同 host 同主题（标题去版本号聚类）新旧并存，旧版进候选 |

防误杀：正文单独出现「过期」不触发（token 过期时间等技术语义常见），只认自述
句式；裸 deprecated 只在标题判；取正文**最新**年份（老页面近年更新过不算旧）；
与最新版日期并列的不判新旧。

**否决权**：Web UI「数据管理 → ⏳ 时效候选」逐条「不过时，保留」或一键舍弃；
保留置 freshness_flag=ok，之后扫描不再标记（与 value_flag=ok 同口径）。stale
条目从消费面（检索/关系图/召回）隐藏，管理视图照常可见；suspect 保留可见。
死链比例信号后置（单条死链已由链接体检 dead 承接）。

> **删除出口（Phase 7 批次 64 落地后生效，2026-10-21 用户裁决）**：人裁
> 「确认废弃」→ 即刻 rejected（全部视图/检索/词云/导出不可见）→ 30 天冷却
> → 自动物理删除（task_log 留痕、content_store 引用计数回收）。此前本节
> 「只标不删」口径在批次 64 后由该出口承接——拒绝区只是冷却缓冲，不是
> 长期存留。

### 2.13 时间线视图与陈旧分支提醒（0.2.0 第四十四批）

**用途**：按「内容时间」看知识库的分布与停滞——左侧树焦点分类子树（或全库）
的条目按 created_at（书签收藏时间/文件创建时间）分桶柱状图；长期无新内容的
叶子分支出提醒（只提示清理/归档，不自动删任何东西）。

**入口**：Web UI 侧栏「📈 时间线」（范围随左侧树焦点分类子树变化，与词云同款
scoped 思路）；工作台检索结果区也有「📈 时间线」tab。

**时间口径**：轴走 created_at（内容时间）；exported_at 是入库时间（全批同时
刻，无分布意义）不用作轴。created_at 缺失的条目（folder 源等）只进「时间未知」
计数，不编造时间。

**分桶**：跨度 >24 个月自动按年、否则按月（可手动切换，偏好保留）；连续区间
补齐空桶（柱状图轴均匀）；点柱子下钻该桶条目列表（可消费口径：待清理/死链/
去重副条目/stale 不出）。

**陈旧分支提醒**：子树内叶子分类（无子节点的分支）最新条目超 2 年无新内容 →
进「🕰️ 陈旧分支提醒」（含停滞年数/最新条目日期/条目数/「📍树中定位」跳到左侧
树）；有新内容的分支不命中；created_at 全缺的分支列「时间未知」不判陈旧
（时间未知 ≠ 陈旧）。阈值 stale_years 可由 `GET /api/timeline?stale_years=N`
调整。提醒是纯只读信号——清理/归档走左侧树节点上的管理按钮。

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

**条目侧校正三方式（0.2.0 第五十二批，全部写 task_log 可复现前后值）**：
- **单条**：条目行悬停「移」按钮（或把条目**拖到左树任一节点**）→ 弹窗输入
  目标路径（可从下拉列表选）；
- **多父挂接**：弹窗里勾「保留原挂接」——只追加新分类不摘旧（同一知识挂到
  多个分支，DAG 设计初衷）；不勾则替换全部旧挂接（默认）；
- **批量**：底部浮动条勾「多选」→ 条目行出现复选框（跨视图累计，检索/
  暂存/待清理各视图通用）→「移到…」一次改挂全部（每条独立 task_log，
  batch_id 串联同一批）。

### 5.5 回归测试集（ktest regress，0.2.0 第五十一批）

**是什么**：人工确认的「条目 → 期望分类」对照集（regress_cases 表）。跑
`ktest regress` 对每条案例重跑自动分类链路（**只验证 L1 先验 + L2 规则层，
零 LLM 费用**），三级判级出报告：exact（全等）/ prefix（方向对差半级）/
miss（无输出或被价值守卫短路）。守住分类质量基线，也是 Phase 4 LLM 兜底的
few-shot 底稿。

```bash
.venv/Scripts/python -m knowatlas ktest regress                       # 跑报告
.venv/Scripts/python -m knowatlas ktest regress --seed-from-log       # 回填历史改类后跑
.venv/Scripts/python -m knowatlas ktest regress --seed-from-log --dry-run  # 只看回填规模
.venv/Scripts/python -m knowatlas ktest canary                        # 契约金丝雀（转 pytest）
```

**案例从哪来**：
- **日常确认**：Web UI 条目行悬停出「✓」按钮（有分类挂接的条目才有），点击
  把当前主分类（manual 挂接优先）确认为期望——看到分类对的条目顺手点一下；
- **历史回填**：`--seed-from-log` 把 task_log 里全部 recategorize 改类动作
  回填（同条目取最后一次 new_path，source=log_seed）——用户改过的类就是
  人工确认过的判断；
- 重复确认同一条目 = 覆盖旧值（改主意语义）。

**报告怎么用**：miss/prefix 明细暴露规则层缺陷（如关键词误映射）——核对后
修订 `semantic/rules.py` / `priors.py` 再跑，exact 率应上升；通过率随批记录
在 CHANGELOG，Phase 4 接 LLM 后同口径对比。

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
uv run python -m knowatlas kexport --format json     # 全量 JSON（Schema 版本化）
uv run python -m knowatlas kexport --format obsidian # 条目笔记 + 分类 MOC 笔记
uv run python -m knowatlas kexport --format opml     # 书签类条目往返格式
```

导出是数据层的投影，不碰原始源。Obsidian 导出后可直接用现有笔记工具打开，作为防锁定出口。

**各格式口径（0.2.0 第四十五批实现）**：

| 格式 | 范围 | 正文策略 | 关键口径 |
|------|------|---------|---------|
| JSON | 全量（含 archived/rejected） | inline_content 内联；content_store 全量正文**不内联**（百万字符级，需要完整正文自行拷贝 content_store 目录） | schema_version 常量（当前 1.0）标记契约；categories 带 parents DAG、entries 带 locators/categories/meta；threads/thread_items 同投影 |
| Obsidian | active 全量（含被守卫条目——防锁定优先；archived/rejected 不进） | 笔记正文 = inline_content（短摘要） | 条目笔记放主分类目录、所有父分类 MOC 都双链它（短链全局解析，多父不丢）；MOC 文件名=分类名（安全化避撞）； Obsidian 内重名分类的短链可能歧义（v0 已知限制） |
| OPML | active 且 locator_canonical 以 http 开头的条目（书签类；file:///mail:///emmx:// 天然排除） | 无正文 | 分类 DAG 展平为 outline 树（多父重复出现）；未分类条目落「（未分类）」根；导出文件可被标准 XML 解析重建无损树（往返保真）；**导入回路已实现**（0.2.0 第五十批，ksync 批量源，见 §2.14） |

---

## 7.5 自动备份与恢复（SOP-B，0.2.0 第四十六批）

```bash
uv run python -m knowatlas kbackup --snap                       # 立即快照 + 轮换
uv run python -m knowatlas kbackup --snap --no-throttle         # 忽略节流强制快照
uv run python -m knowatlas kbackup --verify <快照文件>           # 恢复演练验证（integrity + 条目数）
uv run python -m knowatlas kbackup --restore <快照文件>          # 从快照恢复
```

**机制**：SQLite 官方 `VACUUM INTO` 一致性快照（WAL 开启状态下安全——直接拷
.db 文件会丢 -wal 内未 checkpoint 的数据，这是用内置机制不自己拷文件的理由）。
快照落 `data/backups/knowledge-日期时间.db`。

**同步前自动快照**：每次 `ksync` 真正写库前自动快照一次（节流：距上次快照不足
`backup_min_interval_hours`（默认 24h）则跳过——VACUUM INTO 是全库重建有成本；
`--no-throttle`/force 可强制）。契约=**没快照不同步**：快照失败会中断同步、
不写库（保证任何写入前都有恢复点）；`backup_on_sync=false` 可显式关闭（风险自担）。

**轮换与安全纪律**：默认保留最近 10 份（`backup_keep`），超出删最旧；删除只认
自家白名单（备份目录内 + `knowledge-` 前缀 + `.db` 后缀 + 时间戳名格式），
绝不碰用户放在同目录的其他文件。恢复只接受备份目录内的自家快照（防路径穿越），
且**恢复前自动对当前库快照**（安全网：恢复错了也有后悔药）。恢复前还会探测
本机 serve 端口（`general.server_port`，默认 8420）——可连通即拒绝执行（恢复
是文件级操作需独占 db，先停服务再恢复）；安全网快照的轮换份数与 `backup_keep`
一致，且绝不轮换掉本次恢复的源快照。

**恢复注意事项**：恢复是文件级操作（内部自动关连接、删旧 -wal/-shm、拷快照回
db_path、重开对账 integrity + 条目数）；恢复后如需继续用 Web/CLI 自行重启即可。
数据重要性高的场景，建议定期 `kexport --format json` 与快照双保险（快照防库损坏，
导出防锁定）。

---

## 7.6 MCP 只读查询端点（0.2.0 第四十六批）

`serve` 启动后，agent 可通过以下只读端点查询（v0 = REST 形态，真 MCP 协议
stdio/SSE 后置，需引入 mcp SDK——YAGNI 暂不加依赖）：

| 端点 | 说明 |
|------|------|
| `GET /api/mcp/search?q=&limit=` | FTS 检索，返回命中条目（entry_id/title/locator/snippet/rank） |
| `GET /api/mcp/tree` | 全分类树 + 未分类计数（遍历入口） |
| `GET /api/mcp/entry/{entry_id}?content_limit=` | 单条目详情（元信息 + category_ids + 正文前缀，substr 截取不整段进内存） |

只读纪律有测试钉死：AST 扫描三个 handler——无任何写方法调用、不摸私有 `_conn`、
无非 SELECT SQL。只读端点不走写令牌校验（GET 无副作用），但仍受本机 Host 白名单
约束（不监听非本机，H5 安全约束不变）。

---

## 7.7 知识模型升级操作预置（Phase 7 规划节，M7；实现批次落地后逐条展开为可用命令）

依据：docs/design/知识索引工具-知识集与知识生命周期方案.md（定稿 v2，2026-10-21 两轮用户裁决）。
本节只预置**运维纪律与验收口径**，命令随实现批次进 SOP（SOP 不虚构不存在的命令）。

**批次 59-65 总纪律**（开工前读一遍）：

1. **组头信号化**（60 批验收口径）：知识集列表的组头只允许成员内容的自身信号
   （共享关键词/分类/host/代表条目原文摘句），禁止发明性命名——LLM 职责是
   「选出成员间真实共享的词」，不是起标题；
2. **形态判定先行**（61 批）：切点前每个载体条目先判 integral（整条即点：方案、
   论证、单主题文档）/ split（集合型才切），判定理由落 meta 可抽检；切后规范化
   hash 去重，一点多溯源（溯源数=可信度信号）；
3. **emmx 重灌纪律**（62 批）：重灌前**强制 kbackup 快照**（没快照不动手）；全删
   只删 source_type='emmx'；重灌后抽检 20 文件核对方案型是否保住整体性；
4. **删除出口口径**（64 批）：人裁废弃 → 即刻 rejected 全面不可见 → 30 天冷却
   → 自动物理删除（task_log 留痕、content_store 按引用计数回收——共享内容块
   只减计数，删到零才清正文）；拒绝区是冷却缓冲不是存留区；
5. **勘误不篡改原文**（65 批）：改正 = 勘误附注层并显，原文 diff 恒为零；LLM
   勘误结论必须附可核查依据（官方文档 URL/版本号），给不出依据只标「疑似」；
   L1 只做确定性错误（完整代码块语法、死链），疑似交 LLM 防误报淹没；
6. **抽检固化**（61 批起）：首批 50 条人工过目后固化为回归集（51 批 ktest
   regress 机制复用），点层质量可持续回归，不只看一眼。

规模前瞻：待接入几万封邮件 / 几 GB 微信聊天记录 / ≥10 万条 AI 会话——
批次 61-65 期间检索与聚合查询持续以真实库规模压测；10 万条规模下查询期
聚合需签名缓存（词云挂账同款机制），届时立项。

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
4. 设 `KNOWATLAS_HOME`（用户级环境变量，指向新机的数据根，如
   `C:\Users\<你>\.knowatlas`）——相对路径配置自动挂到该处。
5. `python -m knowatlas ksync --dry-run` 验证各源可达。
6. `python -m knowatlas ksync --full` 全量同步，与迁移前条目数对账。
7. 需要历史数据时，拷贝旧机 `<KNOWATLAS_HOME>\data\` 下 SQLite 文件
   （db + -wal + -shm 三件套一起拷，停服后拷）到新机同位置，再跑
   `--incremental` 补齐；未设 KNOWATLAS_HOME 的旧库则在旧机仓库 `data/` 下。

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
