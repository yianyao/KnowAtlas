# Changelog

格式参考 Keep a Changelog。本项目纪律（K3 定稿）：变更工单自 2026-10-19 起不再新增文件，一律追加进本文件。

## [0.1.0] - 2026-10-19

### 定稿

- **项目正式命名**：中文「知道」，英文 **KnowAtlas**（用户 2026-10-19 定）。
  全量更名映射：包名 `knowtree`→`knowatlas`、环境变量前缀 `KNOWTREE_`→`KNOWATLAS_`、
  请求头 `X-KnowTree-Token`→`X-KnowAtlas-Token`、配置文件 `knowledge-tree.toml`→`knowatlas.toml`、
  基类 `KnowTreeError`→`KnowAtlasError`。仓库：https://github.com/yianyao/KnowAtlas
- Phase 0：建仓库；`docs/design/` 收录首批契约文档（设计方案 / 完整方案 / SOP / TODO /
  实施约束规范 + 4 份历史变更工单），**以仓库版本为准**；本 CHANGELOG 建立。

### 新增（按完整方案 §12 步骤 1–7 实现，M0.5 主体）

- 步骤 1 骨架：pyproject / requirements 两份 / `config/knowatlas.example.toml` / logging_setup / config（TOML + `KNOWATLAS_*` 环境变量覆盖 + 启动校验）。
- 步骤 2 契约基础：`models.py`（Entry/Category/UpsertResult/FetchResult/SearchHit + SOURCE_TYPES/SCHEMES）+ `ids.py`（entry_id `\x1f` 分隔、canonical URL 五步规范化、内容 hash 规范化）。
- 步骤 3 数据层：`migrations/001_init.sql` 全量 DDL（entries 含 `locator_canonical`、entry_locators、categories（path 不落库）、category_parents、entry_categories、content_store、content_fts、task_log、runs、entries_fts + 三条同步触发器）+ `db.py`（upsert 覆盖纪律、CTE 派生路径、多父 DAG、move/merge/attach/detach、search_fts 两字词 LIKE 兜底、archive_missing 删除检测）。
- 步骤 4 注册表：`registry/capability.py` + `builtins.py`（http/https/file + classify_coarse/tag_keywords）。
- 步骤 5–7 kadd 垂直切片：`adapters/manual.py` → `fetchers/`（http_simple + file_reader + fetch_with_fallback 升级路由）→ `pipeline/kadd.py`（建条目 → 抓取 → content_store → classify_coarse L1 先验/L2 规则 → 暂存区兜底）→ `cli.py`（kinit/kadd/serve 可用；ksync 骨架；kexport/kbackup/ktest 明确报"未实现"）。
- 步骤 8 提前并入：web 最小服务（`/api/tree` `/api/entries/{id}` `/api/search` `/api/stats` `POST /api/entries`），含 H5 五条安全约束（Host/Origin 校验、`X-KnowAtlas-Token`、content-type 白名单）。
- 测试：契约 / canary / ids / datalayer（幂等、H3 覆盖纪律、DAG 多路径、两字词检索兜底、archive_missing）/ kadd 端到端（本地 HTTP fixture）。
- CI 兜底：`.github/workflows/ci.yml`（pytest）；本地 pre-commit 门禁（`.githooks/`，core.hooksPath 指向）。

### 实施期新增（契约补充，canary 覆盖范围之外，特此记录）

- `errors.py` 新增 `FetchError`：抓取失败的显式错误分类（§10 错误表未列；M2 评估是否并入现有类）。
- `.gitignore` 相对复用区模板修正一处：模板整目录忽略 `config/` 会导致 `config/knowatlas.example.toml` 无法入库，项目内改为 `config/*` + `!config/*.example.toml`（复用区模板待同步）。
- 新增 `pipeline/kadd.py`（ingest_url）承载手动入口链路；`pipeline/dedupe.py` 为 M2 步骤 14 的骨架占位。
- `DataLayer.find_by_locator` 同时匹配 `entries.locator`（主 locator）与 `entry_locators`（附加 locator）——契约原文只写查 entry_locators，主 locator 也应命中才符合直觉。
- 新增 `DataLayer.get_stats / get_entry_detail / all_category_paths / archive_missing` 等 web 与同步所需辅助方法（接口签名扩展，未改动既有契约）。

## [0.2.0] - 2026-10-19

### 新增（M1 提期：书签源接入，M0.5 Gate 达成）

- **浏览器书签适配器** `adapters/bookmark.py`（source_type=bookmark，完整方案 §3.2 / §12 步骤 9）：
  Chrome/Edge Bookmarks JSON 同构解析；source_key = 浏览器名+节点 id（无 id 用收藏夹路径+标题兜底）；
  native_path = 收藏夹层级（「书签栏/技术/数据库」形）；非 http/https 书签跳过并计数；
  WebKit 时间戳（1601 纪元微秒）→ ISO 8601；文件缺失/损坏抛 AdapterError。
- **ksync 全量遍历型同步落地** `pipeline/sync.py`：批量源注册表（新源 = 一行）→ collect →
  幂等 upsert → 新建条目批量 classify_coarse（L1 先验 + L2 规则；unchanged 不重复挂）→
  full 时 `archive_missing` 删除检测 → `--fetch-limit` 显式补抓（K1：默认不抓正文，失败计数不中断）
  → dry-run 只探测不写库 → 单源 AdapterError 隔离。CLI ksync help 同步更新。
- **先验映射表按真实数据定稿初版** `semantic/priors.py`：按 390 条真实书签文件夹分布修订
  （M0.5 Gate「10 大类经真实数据检验」）——AI绘图/AI/js/前端/php/rabbitmq/python/java/git/api/
  后端/JS&TS/编程思想 → 技术开发与人工智能；Huawei/华为 → 华为云；自学/综合/other/tools →
  综合资料；弱信号路径（移动设备书签等）不映射、留暂存区。
- **测试**：`tests/test_bookmarks.py` 8 项（条目数与 native_path 层级一致探针、source_key 规则、
  canonical 规范化、坏文件报错、端到端幂等、删除检测、dry-run、源错误隔离）。全量 36 项通过。
- **真实数据验证（M0.5 Gate 数据）**：Edge+Chrome 共 390 条书签 + 1 条 manual = 391 条 active，
  分类覆盖率 94.6%（origin=prior 361 / origin=rule 9 / 暂存区 21）；
  `/api/tree` 层级正确、`/api/search` 中文命中、重复 kadd 幂等。

### 修订（0.2.0，用户 uv 工具链踩坑驱动）

- **依赖声明入 pyproject**（原契约"依赖不入 pyproject、以 requirements 两份清单为准"作废）：
  `uv run` 只按 pyproject 安装依赖，不读 requirements 文件——导致新环境 `uv run python -m knowatlas serve`
  报 `ModuleNotFoundError: No module named 'fastapi'`。现 core 运行依赖入
  `[project].dependencies`，pytest 入 `dev` extra，sentence-transformers/psycopg 入 `optional` extra；
  requirements 两份文件保留给 pip 用户，文件头注明两处同步维护。README 快速开始补 uv 跑法
  （`uv sync --extra dev`）。判据依据：项目可迁移铁律「新机器按文档能原样跑起来」。
- pyproject version 0.1.0 → 0.2.0（与 CHANGELOG 对齐）。

### 新增（0.2.0 第二批：树 UI 交互 + 分类管理 + 更新语义闭环）

- **树 UI 升级**（`web/static/index.html`）：点击分类 → 右侧显示子树条目列表（source_type 筛选）、
  面包屑跳转、暂存区常驻按钮；树节点悬停出现管理操作（新建子类 ✚ / 重命名 ✎ / 移动 ⇄ /
  合并 ⇒，合并需确认）。
- **分类管理 API**（`web/api.py`）：`GET /api/categories/{id}/entries`（子树条目，多父去重）、
  `GET /api/uncategorized`（暂存区）、`POST /api/categories`（新建）、`POST .../rename|move|merge`
  ——写操作全部过 H5 五条守卫（token + content-type + Host/Origin），全部写 task_log。
- **`DataLayer.rename_category`**（接口扩展）：重命名分类节点；path 为派生量，子树路径自动随之，
  无需级联重写。
- **updated 条目重分类（更新语义闭环）**（`pipeline/sync.py`）：同步预检区分新建/更新/归档复活——
  源条目移动文件夹或标题变化（_SOURCE_FIELDS 任一真实变化）→ 先 detach 机器来源
  （origin != manual）旧分类再按新 native_path/标题重挂；人工校正（origin=manual）永不覆盖（H3）；
  归档条目重新出现在源里 → 恢复 active（upsert 不写 status，同步显式 set_status + task_log）。
- **测试**：新增书签移动文件夹重分类、归档复活 2 项；全量 38 项通过。TestClient 实测
  create/rename/merge/entries/uncategorized 全 200，H5 Host 白名单拦截非白名单 Host 正常。
- **TODO**：勾选「分类树 UI v0」；Phase 5 新增「打包安装（wheel + KNOWATLAS_HOME 数据目录策略）」
  （2026-10-19 用户需求）。

### 新增（0.2.0 第三批：关系图 v0 + 条目人工改分类，用户反馈驱动）

- **知识关系图 v0**（`/graph.html`，原计划 M4 提前落结构关系层）：ECharts 力导向图
  （echarts 5.5.1 vendored 至 `static/vendor/`，不依赖 CDN）。节点三类：分类 / 条目 / 域名，
  边三类：条目↔分类挂接（prior/rule 着色区分）、条目↔域名（同 host 星型归组防边爆炸）。
  真实数据实测 449 节点 / 590 边。**边界如实标注**：语义级关系（正文引用、embedding 相似度）
  需 M2 正文与 M4 接入，页面 tip 行显式注明。
- **`DataLayer.get_graph_data`**（接口扩展）：图数据唯一出口（防腐化红线——图组装在数据层）。
- **条目人工改分类**：`POST /api/entries/{id}/recategorize`（按路径定位目标，不存在自动建，
  origin=manual）——替换全部旧挂接（"manual 永不覆盖"约束机器来源，人工自身后续校正允许更新，
  task_log 记录前后值）；UI 条目卡片悬停出「⇄改分类」按钮。
- **测试**：`tests/test_web_api.py` 4 项（分类 CRUD 流、recategorize 人工覆盖语义、
  图数据形状、写守卫 403）；全量 42 项通过。

### 新增（0.2.0 第四批：先验收敛 + L3 LLM 语义分类提前落，用户定调"分类树由内容决定，不由文件夹决定"）

- **先验映射收敛**（`semantic/priors.py`）：「软件开发」并入「技术开发」（RULES 同步）；
  「工具站/自学/综合/other」等随手命名的碎片文件夹**取消映射**——放行给 L2 规则与
  L3 LLM 语义分类。真实数据重评（`ksync --reclassify`）：顶层类 7 → 5
  （技术开发 169 / 人工智能 130 / 华为云 13 / 软件与ERP 5 / 文学创作 3），71 条弱信号
  条目进暂存区等待语义分类。
- **L3 LLM 语义分类**（`semantic/llm.py` + `semantic/tasks/classify_deep.py`，原计划 M4 提前）：
  classify_coarse 升级为三级流水线 L1 先验 → L2 规则 → L3 LLM（classify_coarse SPEC 升 1.1.0）；
  DeepSeek 兼容 Chat API，批量（llm.max_batch）控成本，候选路径优先归并、允许提议新路径；
  key 未设 → L3 静默跳过（行为同 0.1.0）；单批失败降级暂存区不中断；
  **L1/L2 命中不消耗 LLM 调用**（成本纪律）。
- **`ksync --reclassify`**：对库中全部 active 条目重跑三级流水线——含人工校正（manual）
  挂接的条目整条跳过；`DataLayer.list_entries`（接口扩展）。**设好
  `KNOWATLAS_LLM_API_KEY` 后执行一次即可让全库条目按内容语义重新归类**。
- **TaskContext** 契约扩展：新增 `config` 字段（任务读取自身参数）；`llm` 字段启用。
- **契约面更新（有意变更，canary 重录）**：capabilities 新增 classify_deep@1.0.0
  （canary capabilities 摘要 c94f8aba17ad → 3c9e3746e55a）；test_contract 能力白名单同步。
- **测试**：`tests/test_classify_deep.py` 6 项（JSON 容错提取、llm=None 跳过、批量解析与
  故障隔离、L1 命中不调 LLM、L3 兜底、reclassify 跳过 manual）；全量 48 项通过。

### 修正（0.2.0 第五批：reclassify 候选语义，用户截图反馈"LLM 跑了但树没变"）

- **reclassify 候选路径修正**（三轮迭代定稿）：旧实现把全部现存类目（含残留碎片）作 LLM 候选，
  导致 LLM 顺手归并「综合资料/工具站」等碎片类目。修正后流程：① detach 前清理真·空壳类目
  （`DataLayer.delete_empty_categories`，非 manual 且无挂接无子类）→ ② detach 前快照大类骨架
  → ③ 摘除机器分类 → ④ 候选 = 人工挂接路径 ∪ 大类骨架（完整旧路径不进候选）。
  真实重跑：**「自学」「工具站」类目消失**，工具类条目按内容分流（技术开发/开发工具 7、
  系统工具 2、软件与ERP/安全软件 2、综合资料/素材资源 4、可商用素材 5、在线学习 5）；
  389/391 归类、暂存 3 条、12 秒/全量。
- **`DataLayer.manual_category_paths`**（接口扩展）：仅人工挂接分类的派生路径。
- **图边 tooltip 语义化**（`graph.html`）：边悬停显示「标题A —关系→ 标题B」（同域名/文件夹
  先验/关键词规则/语义判断/人工校正），替换裸 id。
- 已知边界：LLM 按内容细分产生 22 个单条目碎片二级类目（"先细后粗"的自然结果），
  可在 UI 用 ⇒合并收拢，或后续加自动归并策略（未实现）。

### 新增（0.2.0 第六批：舍弃机制 + 碎片自动收拢 + 改分类列表选择，用户反馈驱动）

- **条目舍弃机制**（`rejected` 状态，用户需求"无用内容舍弃后重读源不得复活"）：
  `POST /api/entries/{id}/reject` / `restore`、`GET /api/rejected`；UI 条目卡片悬停「🚫舍弃」
  （带确认），侧栏「🗑️ 已舍弃条目」查看/恢复入口。rejected 不入树/检索/图/暂存区
  （全部查询已按 status='active' 过滤，天然排除）；**重新同步永不复活**（revive 仅针对
  archived）；STATUSES 扩展（DDL 无 CHECK，canary 六面不变）。
- **碎片类目自动收拢**（`DataLayer.prune_fragment_categories`）：挂接条目 < 2 的非人工
  二级类目自动并入一级父（挂接迁移、类目删除、task_log 记录）。reclassify 流程在分类前
  （清上一轮）与分类后（收本轮）各执行一次。真实效果：**44 → 24 个类目、单条目碎片清零**，
  树完全由内容聚出（后端 89 / 前端 65 / AI绘图 60 / 开发工具 7 / 素材资源 4 …）。
- **改分类交互升级**：原生 prompt 手输路径 → `<dialog>` + `<datalist>` 列表选择
  （自动补全全部类目路径，输入过滤，也允许新路径）。
- **测试**：`tests/test_reject_prune.py` 4 项（舍弃生命周期、rejected 不复活、碎片收拢
  迁移正确性、reclassify 收拢联动）；全量 52 项通过。

### 新增（0.2.0 第七批：链接体检，用户需求"不可达的链接还要来干嘛"）

- **`kcheck` 命令**（`pipeline/health.py`）：对 active http(s) 条目 GET+stream 可达性检测
  （默认限量 100 条、qps 限流），结果写条目 meta（link_status/link_code/link_checked_at）。
  **可达性是波动属性，放 meta 不放 status 列**（status 归用户/源决定）。
- **四级分级**（真实体检校准，防误杀）：
  - `ok`：2xx/3xx；
  - `dead`：404/410——服务器明确说内容没了，高置信死链；
  - `blocked`：401/403/412/429——**反爬拦截，链接对人有效**（浏览器可达），不算失效
    （真实体检发现知乎 403、B站 412 均属此类）；
  - `error`：5xx、超时、DNS/网络失败——可能临时（本地代理环境也会产生噪音）。
  不自动舍弃任何条目；dead 只标记，批量舍弃由用户确认。
- **API + UI**：`GET /api/dead-links`（dead + error 分列）；侧栏「☠️ 失效链接」视图，
  单条 🚫 舍弃 + 「一键舍弃全部失效链接」（批量确认）。
- **`DataLayer.list_by_link_status`**（接口扩展，json_extract 查询）。
- **测试**：`tests/test_health.py` 2 项（mock 检测函数，meta 写入与分级查询）；全量 54 项通过。
- 后续（M2 正文层）：folder 源的乱码/不可读文件走既有 `DegradedParseError` 降级标记；
  死链重测多次仍失败可升级处理策略（未实现，先观察误报率）。
