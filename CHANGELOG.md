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

### 新增（0.2.0 第八批：非知识判定 + 写令牌体验，用户定调"非具体知识的条目没有保留价值"）

- **LLM 非知识判定**（classify_deep 同一次调用附带，零额外成本）：prompt 增加 kind 字段
  （knowledge = 具体自洽的知识内容 / non = 站点门户、导航首页、资源列表、纯资源文件）；
  判 non 的条目写 `meta.value_flag="not_knowledge"`，**不自动舍弃**——保留决定权在用户。
- **待清理候选视图**：`GET /api/not-knowledge` + 侧栏「🔬 待清理候选」——单条 🚫舍弃 /
  「↩是知识，保留」（`POST /api/entries/{id}/unflag` 清标记）；**用户否决被后续重评尊重**
  （value_flag=ok 的条目不再标记，防 LLM 反复骚扰）。
- **`DataLayer.merge_meta` / `list_by_value_flag`**（接口扩展）；health.py 体检改用
  merge_meta（同款模式简化）。
- **写令牌体验**：serve 启动时 KNOWATLAS_WEB_TOKEN 未设 → 自动生成本次会话令牌并打印
  （安全不降级——token 仍必填，仅由工具代生成，H5 第 3 条不变）；UI 弹窗文案说明
  「与 LLM 无关，是防冒充写操作的安全措施，值在 serve 启动日志」。
- **测试**：kind 解析、否决尊重等 2 项；全量 56 项通过。
- **真实数据验证**：391 条重评 13 秒，LLM 判出 30 条非知识候选——全部命中门户/素材站/
  自学平台首页/Your Repositories 类型（正是用户点名的"要来也没用"的条目）。

### 新增（0.2.0 第九批：文件夹适配器，M1 提期）

- **文件夹适配器**（`adapters/folder.py`，source_type=folder）：遍历
  `[sources.folders].roots` → 统一条目；source_key = 配置根相对路径（POSIX 风格）；
  locator = `file://<相对路径>`（file_reader 按 roots 逐根解析，§5 语法不变）；
  native_path = 根目录名/子目录层级（TODO 探针：嵌套层级正确）；隐藏文件/Office 临时文件/
  符号链接跳过并计数；meta.file_kind 四类标记（document/pdf/office/other）；
  2000 条防失控上限。多 root 重名相对路径计数警告（duplicate_rel）。
- **sync 增强**：`_BATCH_COLLECTORS` 注册 folders；archive_missing/revive 的 source_type
  按源映射（原硬编码 bookmark）；`--fetch-limit` 对 file:// 条目生效（txt/md 直读正文
  入 content_store 参与分类；Office/PDF 解析失败计 fetch_failed——"不可读文件"在此暴露）。
- **测试**：`tests/test_folders.py` 4 项（native_path 探针、根缺失报错、端到端幂等 +
  删除检测、file 补抓正文）；全量 60 项通过。
- 使用：config `[sources.folders]` 填 `roots = ["<本机文档目录>"]` 并 `enabled = true`。

### 修正 + 新增（0.2.0 第十批：emmx 适配器 + 视图跳转修复 + 测试代理隔离）

- **万兴脑图适配器**（`adapters/emmx.py`，source_type=emmx，M1 三源之三）：.emmx=ZIP，
  防御性解析 content.xml——topic 元素树（title/name 属性、children/topics 嵌套，覆盖
  MindMaster 常见结构）；节点 id 取 XML id 属性缺失时路径序号兜底；content.xml 缺失/
  坏 zip/无 topic 结构 → **降级标题级单条目，meta.degraded=true**（TODO page.bin 降级纪律）；
  source_key=相对路径#节点id、locator=emmx://同构、native_path=文件目录层级、
  主题路径进 meta.mind_path；3000 节点防失控上限。sync 注册 + fixture 测试 4 项。
  **真实 .emmx 样本验收探针待用户提供文件后执行**（合成 fixture 已全过）。
- **UI 修复（用户截图反馈"改一次分类就跳到暂存区，很烦"）**：写操作成功后不再强制跳转——
  各视图入口设置 refreshCurrent，操作后**留在当前视图局部刷新**。
- **测试环境修正**：conftest 强制 `NO_PROXY=127.0.0.1,localhost`——系统代理
  （http_proxy 环境变量）对本地 fixture 请求的转发不稳定，导致 kadd 端到端在多文件
  组合跑时偶发假挂（与 uv 验证期踩坑同源：httpx trust_env 读代理）。
- **测试**：全量 64 项通过（含组合跑回归验证）。

### 新增（0.2.0 第十一批：文件夹源过滤规则，用户截图反馈"会话数据文件混进条目"）

- **[sources.folders] 过滤**：`exclude_globs`（fnmatch 黑名单，匹配文件名或相对路径）
  + `include_exts`（扩展名白名单，设置后白名单外直接排除）。被排除文件不建条目、
  不参与 archive_missing 删除检测，排除计数进 stats（skipped_excluded / skipped_ext）。
  真实 dry-run：roots=D:/Data/百卓，**966 条候选入清单、8706 个非知识文件被白名单排除**。
- 用户本地 config 已回写过滤规则（include_exts 六类文档 + cj_session* 黑名单），
  并修正无效写法 `meta.file_kind`（非配置项）。
- **测试**：过滤规则用例 1 项；全量 65 项通过。

### 修订 + 验收（0.2.0 第十二批：emmx 真实格式定稿，M1 三源验收完成）

- **真实 .emmx 格式解剖**（9 个真实样本：D:/Data/百卓 下 PECOS 进度/供应链流程/编码规则/
  培训小程序/培训积分/总务管理/抽象工厂/泛型/行政）：实际为 **MindMaster 9.x Shape 结构**，
  与最初假设的 content.xml topic 树完全不同——主题树在 `page/page.xml`（document.xml 的
  Properties/Pages 指明页名）；节点 = `<Shape Type="MainIdea|MainTopic|SubTopic|SummaryTopic">`，
  标题在 Text/TextBlock/Text 深层 `<tp>` 元素（多段合并）；**层级不是 XML 嵌套而是
  `<LevelData><Super V="父ID"/>` 引用**；Boundary/Summary/Callout/MMConnector 为装饰 Shape
  不建条目；仅 mmpage/page.bin（旧版二进制）无 page.xml → 降级标题级 degraded=true。
- **解析器按真实格式重写**（`adapters/emmx.py`）：契约细化 source_key/locator 节点 id 为
  `<页名>/<ShapeID>`（如 `emmx://PECOS/编码规则.emmx#page/305`）；mind_path 沿 Super 引用
  上溯构建（父指向非主题装饰容器时断链按顶层，引用环有深度上限防死循环）；
  **native_path 修正为 根名/文件所在子目录层级**（原只存根名，丢失 PECOS/开发 先验信号，
  与 folder 适配器同构）。
- **真实验收探针通过**：9 文件全结构化解析、**0 降级**、865 节点条目
  （百卓/PECOS 500 + 百卓/开发 365；编码规则.emmx 单图 424 节点、行政.emmx mind_path 深
  达 d10 层级正确）；多段 tp 合并正常（"泛型 将要操作的数据类型指定为参数…"副标题段落并入标题）。
- **测试**：fixture 重写为真实格式（Shape/tp/Super 结构 + Boundary 断链 + 旧版 page.bin
  降级 + 空图降级），4 项全过；全量 65 项通过。
- **边界如实记录**：emmx 云端脑图（MindMaster 云文档）不在本地盘，适配器只能吃本地 .emmx
  文件——云端脑图需用户在 MindMaster 中另存为 .emmx 到 roots 目录；结构化条目标题未截断
  （副标题段落并入），展示层与分类输入侧自行截断。

### 修正（0.2.0 第十三批：来源徽标中文化，用户截图反馈"右边怎么还是文件夹的"）

- **来源徽标中文化**（`web/static/index.html`）：条目卡片 source_type 裸值（folder/bookmark/
  manual/emmx）改为中文标签（文件/书签/手动/脑图）——用户把 folder 徽标误解为"条目是文件夹"，
  实际这些条目本身就是文件（folder 是来源类型名）。未知类型回退显示原值。
- **513 条暂存根因确认（真实验证）**：markitdown 在本机 venv 已装且能解析真实百卓文件
  （PDF 说明书提取 17747 字符全文、docx 正常）——解析器是通的；暂存纯粹因 K1 默认不抓正文、
  用户从未跑 --fetch-limit，分类只靠文件名。解法：`ksync --full --fetch-limit 500` 补正文后
  `ksync --reclassify`。

### 修正 + 新增（0.2.0 第十四批：采集上限配置化 + emmx 主题路径进 LLM 输入，用户暂缓入库下先修基础能力）

- **[sources.folders].max_entries 上限配置化**：原 2000 为模块硬编码，真实踩坑——用户把
  roots 扩到 D:/Data 全盘后撞顶 2000，**617 个白名单文件被静默截断永远进不来**，且未
  collect 到的旧条目会被 archive_missing 误判为"源已删除"（删除检测与截断叠加的误杀风险）。
  现缺省 2000、<=0 视为不限，截断计数进 stats.truncated（已在 example.toml 写明风险）。
- **emmx 条目主题路径进 LLM 输入**（`classify_deep._entry_line`）：emmx 条目标题是脑图节点名
  （如"类型参数化"），单看信息量低；meta.mind_path（"泛型/概念/是什么/类型参数化"）是强语义
  信号，现随输入行送给 LLM；与标题相同时不重复输出。
- **测试**：max_entries 配置生效与 <=0 不限、mind_path 进 prompt（含去重）2 项；全量 67 项通过。
- **维护操作留痕**（临时配置走 KNOWATLAS_CONFIG，用户 config 原件未改）：用「folder roots 收回
  百卓 + 用户现有白名单」的临时配置跑 `ksync --source folders --full`，archive_missing 归档
  35 条 .txt 条目（对应用户收紧白名单去掉 .txt）；emmx 入库另用「emmx 启用 + folders 本轮关闭」
  的临时配置，避免 D:/Data 全盘文档被连带收录。

### 新增 + 修正（0.2.0 第十五批：目录级排除配置，用户需求"要 d:/data 但不要 d:/data/Fiction"）

- **目录级排除**：`[sources].exclude_dirs`（全局，各文件系统型源共用——folder 及将来的
  maildir 附件目录、会话记录产物目录、聊天记录导出目录都读同一项）+ `[sources.folders]
  .exclude_dirs`（源级追加）。命中的目录**整棵剪枝不采集**（遍历改 os.walk 在目录层剪枝，
  比逐文件判断快），统计进 stats.skipped_dir，不计入 seen_rel、不参与 archive_missing——
  即"不收录"与"源里没有"严格区分。语义：无 "/" 按目录名匹配（任意层级），带 "/" 按相对
  路径逐段前缀匹配（段内可通配，如 "项目/*_备份"）。
- **跨平台匹配修正（新发现踩坑）**：原 exclude_globs 用 fnmatch 直接匹相对路径字符串，
  依赖 `*` 跨路径分隔符通配——**Windows 上 fnmatch 先 normcase 把 '/' 换成 '\\'，
  实测 "项目资料/*_备份" 匹 "项目资料/旧版备份" 直接 False**，同一份配置跨平台行为不一致
  （违反项目可迁移铁律）。现自实现 `adapters/base.match_path_pattern`（逐段比较 +
  fnmatchcase），排除规则在 Windows/Linux 上行为一致；exclude_globs 与 exclude_dirs 共用。
- **真实验证**：D:/Data 白名单文件真实 2612 个（原 2000 上限静默丢弃 612）；配
  exclude_dirs = ["Fiction", ".git"] 后 Fiction 残留 0、剪枝 4 个目录；用户 config 已写入
  exclude_dirs + max_entries = 5000。git 目录下 694 个文档不受 .git 排除影响（那是用户自建
  文档目录，非仓库内部结构）。
- **测试**：目录名匹配 / 相对路径模式 / 源级追加 1 项（内含匹配语义回归）；全量 68 项通过。

### 新增（0.2.0 第十六批：令牌可自查，用户两次"配了环境变量还是用不了"）

- **令牌指纹**（`web/api.token_fingerprint`，sha256 前 8 位，**永不回传明文**）：
  - `GET /api/token-hint` 返回环境变量名、指纹、是否已配置——网页首次弹窗时直接展示
    服务端指纹，人填的值若与服务端不一致可当场发现；
  - 写守卫 403 消息带指纹，并列明**三类最常见原因**：①弹窗填的值与服务端不是同一个；
    ②配完环境变量没重启 serve（进程启动时读一次）；③同名环境变量在系统级/用户级两处
    都存在时被另一级覆盖（Windows 规则：用户级优先）；
  - serve 启动日志两种来源都打印指纹。
- **环境变量排查教训（已记入记忆）**：诊断"环境变量没生效"时**必须同时查系统级
  （HKLM）与用户级（HKCU）**——本次只看 HKCU 就断言"用户没配"，实际用户配在系统级，
  属误判。Windows 同名变量的优先级是用户级 > 系统级。
- **测试**：指纹不回传明文 + 403 消息含指纹 1 项；全量 69 项通过。

### 修正（0.2.0 第十七批：写令牌改为同源自动凭据，用户定调"设了环境变量就不该再填 token"）

- **用户定调**：令牌由服务端环境变量决定，网页端**不应要求用户手工填**。原设计要人把
  服务端的令牌再抄一遍进浏览器——两处不同步就永久 403，且浏览器 localStorage 缓存了旧值
  后连提示都不再出现（用户实际遭遇：环境变量配了、网页仍报"写操作需 token 头"）。
- **同源自动写凭据**（`GET /api/session`）：页面打开时服务端把写令牌种进
  **HttpOnly + SameSite=Strict + Path=/** Cookie，浏览器同源写请求自动携带——
  **零手工输入**。写守卫接受 header / cookie / query 三通道（bookmarklet 仍走 query）。
- **防护不降级**：cookie 是 HttpOnly（JS 读不到明文）、SameSite=Strict（跨站请求不带）、
  绑定 127.0.0.1 域（他站取不到）；Host/Origin 校验与 content-type 白名单照旧；
  错误 cookie 仍 403（有测试）。
- **自愈**：写请求遇 403 自动重取一次会话再重试（serve 重启换令牌后自愈）；
  指纹提示（第十六批）保留在启动日志与 /api/token-hint 供核对。
- **测试**：会话 Cookie 免手工通过守卫、错误 Cookie 仍拒 2 项；全量 71 项通过。

### 新增（0.2.0 第十八批：L0 价值守卫——「进去就是资源/首页/子目录页」不再花 LLM 判断）

- **用户定调（2026-10-20）**：收藏夹里大量条目"进去就是一个资源，或者是网站首页或
  某个子目录页面"，此类条目**URL 结构一眼可判，不需要 LLM 语义判断**。实测画像
  （390 条书签）：站点首页 81、列表/导航子页 42、资源直链 1、内容页 266——
  结构规则覆盖了约 1/3 的书签存量。
- **`semantic/value_guard.py`（新）`judge_value(locator)`**：纯函数零 IO，三类规则——
  `resource_file`（path 尾段扩展名 ∈ RESOURCE_EXTS：压缩包/安装包/镜像/媒体/图片/
  二进制库；**PDF/电子书/Office 不判**——可解析正文的知识资源）、`portal_homepage`
  （http(s) path 为空或 "/"）、`index_subdir`（http(s) path 以 "/" 结尾且非根）。
  防误杀：内容页（.html/无尾斜杠/GitHub 仓库页）不判；畸形 netloc 不抛异常。
- **classify_coarse 接入 L0（SPEC 1.1.0→1.2.0，canary 同步升版）**：命中条目直接短路
  ——不占 L1/L2/L3、**不调 LLM**（省 token 且防漏判）；tags 与 LLM kind=non 同构
  （`not_knowledge` + `value_reason:<规则>`）；`value_flag=ok`（用户否决）不短路。
  L0 短路条目显式排除出 L3 pending——**修了 tag 被 LLM 输出覆盖的 bug**。
- **`ksync --value-scan` 价值体检**（cli + `pipeline/sync._value_scan`）：只扫存量
  active 条目的 URL 结构打标（`value_flag=not_knowledge` + `value_flag_reason`），
  进 Web UI「待清理候选」（舍弃/保留决定权在用户，仅标记不动手）；
  **零费用、不动分类树、不调 LLM**——与 `--reclassify`（全量重分类）分工明确；
  支持 `--dry-run` 只出报告；已标记条目只补 reason 不重复计数。
- **Web**：`/api/not-knowledge` 透出 `reason` 字段；「待清理候选」视图按
  资源文件/站点首页/列表子页显示来源徽标；侧栏文案改「规则/LLM 判非知识」。

### 修正（0.2.0 第十八批同批：机器后处理 meta 被同步抹掉的 bug）

- **症状**：L0/LLM 打标（或 kcheck 体检）写入 meta 的 `value_flag`/`link_status`，
  在下一次 `ksync` 时被 upsert **整串 meta 覆盖**抹掉，并因 `row["meta"] !=
  meta_json` 误判 updated——每次同步都"翻转抖动"（旧 LLM 标记路径同样中招）。
- **根因**：upsert 更新时只保留 `manual_` 前缀键，其余 meta 键以源数据为准。
- **修法**（`datalayer/db.upsert_entries`）：meta 合并语义改为 `{**旧, **新}`——
  源自带键（source_type/browser/native_path/mind_path 等）以源覆盖，**源不设置
  而库中已有的键（机器/人工后处理）原样保留**；updated 判定改按合并后的 meta 比。
- **顺带对齐字段清单漂移**：`pipeline/sync._SOURCE_FIELDS` 补 `created_at`，
  与 `datalayer/db._SOURCE_FIELDS` 真正一致（原注释声称一致实则漏一项）。
- **`_flag_value` 改读库**：同步路径的条目 meta 来自采集器、不含后处理键，
  用户否决必须读库才能看到——否则 Web UI 点过「是知识，保留」后会被同步重新打标。
- **回归测试**：打标后二次同步 unchanged 不翻转 + flag/reason 保留；用户否决后
  源变化触发重分类不重新打标。**测试新增 36 项，全量 107 项通过**。

### 修正/UI（0.2.0 第十九批：分类树空枝不再占视线 + serve 横幅瘦身 + 硅基流动接法入例）

- **分类树加 count（`datalayer/db.get_tree`）**：每个节点带 count = 该子树（含自身、
  含多父重复出现）的 active 条目数——一次查询 + Python 自底向上聚合（DAG 防环占位）。
- **空枝默认隐藏（web/static/index.html）**：count=0 的节点（分类还在、条目被舍弃/归档
  后清空）默认不渲染，左下新增复选框「显示空分类」勾选可见（灰显斜体 + title 说明），
  选择存 localStorage。移动/合并的目标下拉（`catlist`）只收非空分类——搬进空分类无意义。
  **不删分类节点**（与「仅标记、决定权在用户」一贯风格一致；`ksync --reclassify` 的
  自动剪枝逻辑不变，仍只在全量重分类时跑）。
- 真实库实测 4 条空枝：文学创作（根）、综合资料/可商用素材、软件与ERP/安全软件、
  人工智能/AI绘图——后两者正是用户截图中「内容清空了目录还在留着」的节点；「可商用素材」
  是 LLM 细分时新建的碎片子类（不是凭空来的），条目被 Web UI 清理后成空枝。
- **serve 启动横幅瘦身（cli.py）**：删掉「网页弹窗里填的值必须与该环境变量的值完全一致
  （填错、没重启 serve、同名变量被系统级/用户级另一处覆盖……）」两句细节——配置描述
  （example.toml [web]）与 403 异常消息（含服务端指纹 + 三因）已说清；令牌指纹行保留
  （异常消息引用「见 serve 启动日志」）。
- **example.toml**：[llm] 注释补硅基流动接法（base_url=https://api.siliconflow.cn/v1，
  model 如 deepseek-ai/DeepSeek-V3；与 DeepSeek key 并存互不覆盖的配法：另设环境变量名
  KNOWATLAS_LLM_API_KEY_SF 再把 api_key_env 指过去）；[web] 补两个坑（设完环境变量必须
  重开终端 + 重启 serve；同名变量系统级/用户级只配一处，用户级优先）。
- **回归测试 +3 项**（test_datalayer：子树 count 聚合 / rejected 不计数 / 空分类 count=0 /
  多父各计一次），**全量 110 项通过**。

### 新增（0.2.0 第二十批：LLM key 池——多个 api key 失效/限流自动切换）

- **用户诉求（2026-10-20）**：「配置多个 LLM 的变量，优先级咋来？」「硅基流动我也有多个
  api key，用完一个，换环境变量的值再用另一个？」——原实现 api_key_env 只读一个变量、
  单 key，非 200 直接抛错，确实只能手动 setx 换值。
- **`semantic/llm.py` key 池**：`api_key_env` 支持逗号分隔多个变量名，每个变量值也支持
  逗号分隔多个 key（两种堆叠、去空白、保序去重）；`chat()` 按池内顺序尝试——
  401/403（key 失效）、402（余额不足）、429（限流）自动换下一个 key 重试；
  500/网络异常不换 key（不是 key 的问题，照旧抛出由调用方降级）；全部不可用抛聚合错误。
- **纪律延续**：错误消息只带 key 指纹（sha256 前 8 位，与 web 令牌指纹同思路），
  绝不回传明文；key 仍只从环境变量读、不入配置/日志。单 key 配置行为与旧版完全一致
  （向后兼容，无新配置键——canary 契约面不变不升版）。
- **配置描述**：example.toml [llm] 写清两种多 key 配法 + 顺序即优先级 + 换 key 触发条件
  + 「serve 启动时读一次，换 key 后重开终端并重启 serve」。
- **测试**：新增 tests/test_llm_pool.py 12 项（配置解析 5 + 池行为 7），全量 122 项通过。

### 新增（0.2.0 第二十一批：LLM 多后端池——多个 base_url 按序 failover）

- **用户诉求（2026-10-20，截图红字）**：「多个 base_url 也没用啊，只能用一个」——第二十批
  key 池只解决同一 base_url 下多 key 切换，跨供应商（DeepSeek ↔ 硅基流动）仍然切不动。
- **`[[llm.backends]]` 数组表（新配置键，canary config_keys 摘要已升版重录）**：每个后端
  = base_url + key 池 + model，书写顺序即 failover 优先级；不写 backends 时由扁平
  `[llm]` 字段（base_url/api_key_env/model）合成单后端——**旧配置照常工作**；
  后端 key 未设的自动跳过（不带空池进链）；temperature 可后端级覆盖全局。
- **两级切换策略（`semantic/llm.py` 重构 `_Backend` + `LlmClient(backends)`）**：
  401/403/402/429（key 失效/余额/限流）→ 先换同后端下一个 key → key 池尽切下一个后端；
  5xx/网络异常/响应结构异常 → 同后端其他 key 无益，直接切下一个后端；
  4xx 其他（400 等请求/配置问题）→ 直接抛，不换供应商（换了也治不好且掩盖问题）。
- **错误聚合**：全部不可用时逐行列「base_url — HTTP 状态/错误（key 指纹）」，只指纹不明文；
  单后端单 key 的错误消息与旧版逐字一致（向后兼容）。
- **测试**：test_llm_pool.py 重写扩到 15 项（failover 全路径、5xx 跳同后端 key、4xx 不切、
  聚合只带指纹、旧消息兼容、扁平配置兼容、数组表解析与覆盖、无 key 后端跳过），
  另做端到端真 TOML 验证（DeepSeek 优先 + 硅基双 key 兜底）；**全量 125 项通过**。

### 新增/UI（0.2.0 第二十二批：关系图改三视图——大类总览 → 搜索子图/子树下钻）

- **用户定调（2026-10-20，附截图）**：主图按树节点定大类没意见，但「图谱开始只显示大类，
  给个搜索框，输入关键字再只显示关键字相关的」——即**搜索驱动的按需子图**，取代
  一次渲染 438 节点的全量力导（采纳，比纯树形下钻更好：搜索直达，不用逐层点）。
- **数据层三视图（`datalayer/db.py`）**：
  - `get_graph_overview()`：只含一级大类节点，value = 子树 active 条目数（气泡大小依据）；
  - `get_graph_subtree(cid, limit=120)`：子孙分类 + 挂接条目（近 limit 条，带 locator）
    + 祖先链灰底上下文；分类不存在返回 None → 404；
  - `search_graph(q, limit=80)`：条目标题 / 分类名 LIKE 命中（`%/_` 转义防注入语义），
    只带命中条目 + 其直挂分类 + 祖先链——**不扩散拉全子树**，子图小而相关；
    同域名 ≥2 条仍聚出域名节点（与 v0 口径一致）。
- **API**：`/api/graph/overview`、`/api/graph/subtree`、`/api/graph/search`；
  旧 `/api/graph` 保留兼容。
- **前端 `graph.html` 重写**：初始渲染大类气泡（大小 ∝ 子树条目数）；搜索框回车出子图
  （Esc 回总览）；点分类下钻（`notMerge` 整体替换防旧节点残留）；点条目 `window.open`
  原文；视图提示语随状态更新。
- **配置核实（用户截图两问）**：①多后端**书写顺序即优先级**——用户 config 硅基在前即
  优先用硅基，注册表注入实测 2 后端就绪 + 真实小调用走硅基 DeepSeek-V4.1-Flash 返回成功；
  ②`max_batch` **只认 `[llm]` 扁平键**，写进 `[[llm.backends]]` 块会被静默忽略
  （消费方是 sync/classify_deep 的 `cfg.get("llm.max_batch")`，与供应商无关）——已把
  用户 config 里的 max_batch 移回 [llm]，example.toml 注明；另发现 config 引用的
  `KNOWATLAS_LLM_API_KEY_SF2` 两级注册表均未设（该后端 key 池暂只有 SF1 一把 key，
  未设变量被静默跳过，属预期；SF2 留作第二把 key 的槽位）。
- **测试**：+4 数据层（总览根计数 / 子树定位与 locator / 搜索命中与分类链与转义 /
  同域聚合）+1 端点（overview/subtree/404/search/空 q），**全量 130 项通过**。

### 修正/UI（0.2.0 第二十三批：分类树双向联动收口 M1 + 空枝过滤 fail-open）

- **修 bug（用户截图报「显示空分类勾选逻辑反了」）**：症状为不勾选树全空、勾选后节点
  全出来——根因是**旧 serve 进程**（第十九批前启动）的 `/api/tree` 不带 `count` 字段，
  前端把「缺字段」误当「空分类」全隐藏。修法 fail-open：仅 `count === 0` 判空，
  字段缺失放行（树渲染、移动/合并下拉、灰显样式三处同步）；重启 serve 后按设计工作。
- **双向联动②（条目 → 分类，M1 Gate 尾巴收口）**：条目列表（分类视图/暂存区/检索结果/
  待清理候选/已舍弃/失效链接全视图通用）每条带「📁分类路径」徽标，点击 → 左树滚动定位
  + 闪烁高亮（1.1s×2 动画）；新端点 `GET /api/entries/linkage?ids=` 批量取挂接
  （只读、≤100 id、声明在 `/api/entries/{entry_id}` 之前防路径参数吞掉 "linkage"）。
  双向联动①（点树看条目）M0.5 已有。Phase 1「分类树 UI 完整版」勾结。
- **测试**：+1（linkage 批量/空 id/路由顺序），**全量 131 项通过**。

### 新增（0.2.0 第二十四批：DeepSeek Fetch 升级抓取后端接入——M2 第一项落地）

- **外部事实核实（2026-10-20 检索）**：DeepSeek Fetch API 于 2026-10-17 官方上线——
  `POST https://api.deepseek.com/v1/tools/fetch`，Bearer 鉴权，返回 {title, content(markdown)}；
  5 元/千次成功请求（失败/超时/空结果不计费）；账号级 5 QPS + 域级限速。设计文档命名押中。
- **`fetchers/http_deepseek.py` 实装（替换原占位 stub）**：
  - 429 指数退避（0.8s 起步 ×2，fetch.max_retries 次）；其余非 200 直接抛——失败不计费，
    重试同请求无益的 4xx 更不该烧钱；
  - 请求前客户端预检 URL（http/https、≤8192 字符）——不合规请求不发出；
  - key 走环境变量：新配置键 `fetch.deepseek_api_key_env`（默认 KNOWATLAS_LLM_API_KEY，
    与 LLM 后端共用同一把 DeepSeek key）+ `fetch.deepseek_base_url`（canary config_keys
    摘要已重录 31d80a965903）；key 本体不入配置/日志（铁律）；
  - 空正文（目标站反爬/无正文）明确报错并注明按规范不计费。
- **升级路由**：`fetch_with_fallback` 挂点早已就绪（simple 失败：HTTP≥400/正文过短/提取
  失败 → fallback_backend）；用户 config 的 fallback_backend 由空改为 deepseek 启用。
  K1 纪律不变：同步默认不抓，抓取只发生在 kadd / ksync --fetch-limit。
- **真实冒烟**：升级路由触发 ✅、鉴权 ✅、200 解析 ✅（api-docs.deepseek.com 真实抓回
  1173 字符 Markdown）；知乎/B站连 DeepSeek 自家抓取器也被拒（404 failed to fetch /
  超时）——符合官方「受目标站点访问策略影响」，错误透明、失败不计费。
- **测试**：+7（全 mock：升级路由端到端 / 429 退避序列 0.8s,1.6s / 429 耗尽 / 非 429 不重试 /
  空正文 / 缺 key 带 hint 不发请求 / 坏 URL 预检不发请求），**全量 138 项通过**。

### 新增/修正（0.2.0 第二十五批：内容质量守卫——用户铁律「不可达/乱码 = 没有知识」落地）

- **用户定调（2026-10-20）**：「坚持一个原则——不可达的、没办法解释的、乱码的等等，
  总而言之一句话，不是具体的、用不了的知识，等于没有」；并拍板暂存区处置走路径 A
  （补抓正文）。
- **`semantic/value_guard.is_garbled(text)`（新，纯函数零 IO）**：替换符 U+FFFD 占比 > 5%
  或控制字符（\t\n\r 除外）占比 > 10% → 乱码（只扫前 5000 字符）。
- **`pipeline/sync._fetch_missing` 重写**：
  - 抓取失败打标：FetchError/AdapterError → reason=unreachable（无法访问）、
    DegradedParseError → reason=unparseable（解析失败）、乱码 → reason=garbled（乱码）——
    统一走 _flag_value 进待清理候选（value_flag=ok 用户否决照旧不被覆盖），
    并落 meta.fetch_status / fetch_error 供诊断；
  - **修连带 bug**：file_reader 对「文件不存在」抛 AdapterError，原代码只捕
    FetchError/DegradedParseError——一个文件缺失会把整轮补抓炸掉；
  - 乱码正文不入 content_store、不进 FTS（不污染检索）；
  - limit 语义改为**尝试次数**上限（原为成功数），防大量失败时一轮跑不完；
  - 成功条目 meta.fetch_status=ok。
- **Web**：待清理候选 reasonLabel 新增 无法访问/解析失败/乱码 三种来源徽标。
- **测试 +4**（is_garbled 阈值、失败/乱码/成功三路端到端、用户否决不被覆盖），
  **全量 141 项通过**。

### 运维记录（0.2.0 第二十五批续：路径 A 实跑——暂存区清零完成）

- **执行**：`ksync --source folders --full --fetch-limit N` 分 6 轮（500/700/900/2000/1000/1200），
  每轮额度被失败重试消耗后追加；期间修了三个实跑暴露的 bug（见上）。
- **重大事实：folder 条目全量换 id**——此前百卓目录用临时 config（roots=D:/Data/百卓）
  入库，id 按相对路径派生；本次真实 config（roots=D:/Data）下 rel 路径多一层 `百卓/` 前缀，
  2613 条全部按新建处理，旧 1040 条被删除检测归档。**人工资产核查：归档条目上人工挂接 0、
  value_flag=ok 否决 0——无损失**；55 条用户已拒绝的旧 folder 条目按 locator 映射
  （file://x → file://百卓/x）把拒绝决定迁移到新条目（task_log 留痕 rekey_migrate）。
- **终态（2026-10-20 12:45 实测）**：folder active 2558，有正文 1464，缺正文且未打标仅 2；
  挂接 1758 / 暂存 800。全库 active 3576；**待清理候选 1408**（unparseable 1076 + LLM 判非知识
  303 + unreachable 28 + garbled 1）；rejected 348。
- **unparseable 1076 的构成**：git/code 仓库内的 vendor 测试样例与坏 Office 文件
  （phpoffice samples、specSkill fixtures 等）——正是用户铁律「不是可用的知识」的典型，
  全部进待清理候选等用户一键处置。经验：代码仓库目录不适合按 include_exts 白名单收
  （样例数据文件噪音高），后续可考虑 exclude_globs 按 vendor/samples 目录级排除。
- 书签源的 http 补抓（约 30s/条的知乎类超时）未在本轮跑，留待后台单独执行。

### 变更工单（0.2.0 第二十六批：方案增补——主题工作区与放射导航契约草案，纯文档）

- **来源**：用户与外部讨论收敛的交互方案（放射导航 + 串联工作区双模式）要求对账现状、
  判定取舍、整理进方案。
- **对账结论**：三层两契约、书签/文件夹/脑图适配、FTS、三级流水线、L0 价值守卫、
  关系图三视图、DeepSeek Fetch（外部稿排第三阶段，实际第二十四批已落地）均已实现；
  **真增量 = Thread 串联工作区（数据模型 threads/thread_items + topic_recall +
  thread_suggest）与放射导航机制增强（relation_reason/导航栈面包屑/Top-N/双向反查）**；
  负反馈表设计预留不建（价值侧已有 value_flag=ok）；统一入口工作台为 UI 迭代项。
- **命名纠偏**：外部稿 CLI `atlas`、`knowatlas.db` 为未实施的旧称——实际
  `python -m knowatlas` + `data/knowledge.db`（完整方案 §9.4 已注明）。
- **落点**：完整方案新增 §9.4（契约草案，标注「实现时字段变更走 CHANGELOG 工单」）；
  TODO Phase 4 新增三待办（串联工作区最高优先 > 放射增强 > 统一入口），词云/时间线顺延。

### 0.2.0 第二十七批（2026-10-20）：超时三次规则 + 目录级排除 + kadd 核实收口

**变更工单（三件事，全部落地）**

1. **补抓超时三次规则**（用户定调：「连续三次超时且排除网络问题，扔掉」）
   - 旧→新：`_fetch_missing` 单次失败即打标 → 超时类错误（措辞 timed out/timeout）
     最多重试 3 次（每次走完整双后端链），仍超时按 `unreachable` 打标进待清理候选；
     非超时错误（403/404/解析失败）是确定性失败，一次判死不重试。
   - 复检探针：`tests/test_value_guard.py` 新增 3 项（恰 3 次后打标 unreachable /
     前 2 次超时第 3 次成功恢复入库 / 非超时 1 次判死），全绿。

2. **目录级排除 exclude_dirs**（git/code 仓库噪音源头治理）
   - 旧→新：用户 config `[sources.folders]` 新增
     `exclude_dirs = ["vendor", "samples", "_legacy", ".git", "node_modules"]`；
     folder 采集器机制早已支持（目录名或相对路径 glob 任意深度命中即剪整棵子树）。
   - 效果：phpoffice samples、specSkill fixtures 等样例噪音不再入库；
     需全量重同步一次让存量噪音归档（本轮已执行，见运维记录）。

3. **kadd 联动补全核实收口**
   - 核实 `pipeline/kadd.py` 全链路（建条目→抓正文→put_content→classify_coarse→
     挂接/暂存）已实现且测试在位（test_kadd_full_chain），TODO 标 [x] 无需新代码；
     content store 同批核实标记 [x]。

- 测试：145 项全绿（142 + 3）。

### 0.2.0 第二十八批（2026-10-20）：Office 文档解析修复——「我能直接打开的 .doc 被打 unparseable」

**根因（用户核实待清理候选时指出，两个独立问题叠加）**

1. markitdown 0.1.8 裸装（无 `[all]` extra）缺可选依赖：docx（mammoth）/
   xlsx（openpyxl+pandas）/ xls（xlrd）/ pptx（python-pptx）全部
   `MissingDependencyException`——**Office 文档解析在本库从未成功过**
   （待清理候选 489 条 = xlsx 306 + docx 64 + xls 54 + ppt 32 + doc 31 + pptx 2）。
2. 旧版二进制 .doc / .ppt：markitdown 根本没有转换器（"No converter attempted
   a conversion"），装依赖也解决不了，需要独立解析链路。

**修复**

- 补装依赖（requirements-core + pyproject dependencies 两处同步）：mammoth /
  openpyxl / pandas / xlrd / python-pptx；pywin32 入 optional（Windows COM 可选能力）。
- 新增 `fetchers/office_legacy.py`：.doc/.ppt 旧版后端链——soffice（LibreOffice，
  `KNOWATLAS_SOFFICE_PATH` 可覆盖路径，跨平台首选）→ Windows COM（Word /
  PowerPoint 自动化，本机已验证）→ DegradedParseError 带可操作指引（另存
  docx/pptx / 装 LibreOffice / 装 pywin32+Office）；`file_reader.py` 按
  扩展名路由 `_LEGACY_SUFFIXES = {".doc", ".ppt"}`。
- 修「补抓成功仍赖在待清理候选」：upsert meta 合并语义（{**旧,**新}）保留旧键，
  `value_flag=not_knowledge`（reason 属 fetch 三因 unparseable/unreachable/garbled）
  在补抓成功后显式清除；`merge_meta` 增 None=删键语义；用户否决 value_flag=ok
  与 L0 结构规则（URL 形态，与抓取无关）不动。
- 复检探针：`tests/test_office_parse.py` 10 项（真实 xlsx/pptx/docx 转换、
  .doc 路由、无后端指路报错、soffice/COM 后端选择、None 删键、打标清除、
  用户否决与 L0 打标保留）。真机冒烟：STD-技术手冊(Version2019).doc 经 COM
  提取 10447 字符；docx/xlsx/xls/pptx 真实文件 markitdown 全通。

- 测试：155 项全绿（145 + 10）。

### 0.2.0 第二十九批（2026-10-20）：迁移踩坑清单落盘（纯文档）

- 用户令：回头看工作空间内踩过的所有坑记下来，换机不再重踩。新增
  `docs/迁移踩坑清单.md`（七类：依赖坑[markitdown 裸装 Office 全废/旧版
  .doc/.ppt 无转换器/uv venv 无 pip]、Windows 环境坑[CRLF/fnmatch/两级注册表/
  Bash 重复执行/端口]、网络代理坑[localhost 劫持/GitHub 推送代理/reg.exe]、
  SQLite 并发坑、LLM 密钥坑、解析器数据坑[真实样本先行/大文件剪枝/真坏件]、
  开发纪律坑[upsert 删键/测试硬约束/替换脚本引号]）+ 新机冒烟清单五步。
- 关联件同步：设计方案 §0 文档清单登记；SOP §9 增"换机前必读"指针。

### 0.2.0 第三十批（2026-10-20）：发票目录排除出库（纯配置+运维）

- 用户定：财务发票非知识且敏感——folders exclude_dirs 增「发票」（用户自行改入
  config），重同步归档 271 条电子发票 PDF/表格；原件永久留在源目录。库况终态：
  active 约 1937，有正文 1342，待清理候选 64。

### 0.2.0 第三十一批（2026-10-20，变更工单）：§9.4 增补「原始会话线程还原」+ TODO Phase 2/3/4 同步（纯文档）

**背景**：用户引文核查定调（0.2.0 第二十九批同日）——采纳「线程还原 + 规则引用剥离」
思想，不绑定引文推荐工具；Python 侧自行选型。

**旧 → 新**

1. 完整方案 §9.4：原只有用户串联线索（threads 表）→ 增补「原始会话线程还原」契约草案：
   threads 增列 `thread_type`（curated 用户串联 / source 源还原，同表不分表）；新表
   `conv_messages`（DDL 草案：id/thread_id/entry_id/msg_key/parent_id/sender/sent_at/
   ordinal/quote_anchor，只存结构与锚点、永不复制正文）；语义任务新增 quote_strip
   （规则，mail-parser-reply 底座[MIT/纯Python/零依赖/2025-12 仍维护，联网核实] +
   中文回复头自补；email_reply_parser 仅英文停更只借鉴）/ delta_summarize / thread_digest
   （LLM 后置，走 [llm] 池硅基流动优先）；三层留存、视图衔接、实施顺序纪律。
2. TODO Phase 2 邮件适配器：增线程还原 + quote_strip 增补行与双探针。
3. TODO Phase 3 AI 会话适配器：增 conv_messages 还原增补行与探针。
4. TODO Phase 4：增「会话线程语义任务」条目（先规则后 LLM、可独立关闭）+ 探针。

**复检探针**（已全部命中）

- §9.4 含 thread_type / conv_messages / mail-parser-reply / quote_strip / delta_summarize / thread_digest
- TODO Phase 2 含「线程增补」，Phase 3 含「conv_messages」，Phase 4 含「quote_strip」
- 变更文件 UTF-8 无 BOM + LF（字节扫描通过）

### 0.2.0 第三十二批（2026-10-20，变更工单）：Thread 串联工作区（主题工作区）落地——M4 用户最高优先项

**来源**：用户 2026-10-20 定调 Phase 4 优先序「Thread 串联工作区 > 放射导航增强 > 统一入口工作台；
词云/时间线顺延」；契约草案见完整方案 §9.4（0.2.0 第二十六批）+ thread_type 增列（第三十一批）。
痛点：「知道要什么，但相关知识散落多个源多个条目，串联困难」。

**旧 → 新**

1. **数据模型**（migrations/002_threads.sql，随 schema canary 升版）：
   - 新表 `threads(id, name, note, thread_type, created_at, updated_at)`——thread_type
     默认 `curated`（用户串联线索）；`source`（邮件/AI 会话源还原）随 Phase 2/3 适配器使用，
     本批不建 conv_messages（属适配器批次，YAGNI）。
   - 新表 `thread_items(id, thread_id, entry_id, position, relation_type, note)`——
     线索内有序条目；relation_type 开放枚举，首现定义 seq/because/prereq/contrast（新增走 CHANGELOG）。
   - 迁移机制升级（只进不前纪律不变）：schema.py 由「单文件 001」改为按序发现
     `migrations/NNN_*.sql`；db.py init_schema 顺序应用所有待定迁移并逐版置 user_version；
     库版本高于代码时明确报错（旧代码开新库不给静默错数据）。
2. **数据层方法**（db.py，写操作全部落 task_log，task_name=threads）：
   create_thread / get_thread / list_threads / update_thread / delete_thread；
   add_thread_item（position 默认追加尾位，同线索去重）/ remove_thread_item /
   move_thread_item（重排序号紧凑化）/ update_thread_item / threads_for_entry。
   models.py 新增 Thread / ThreadItem dataclass 与 THREAD_TYPES。
3. **语义任务**（注册表新增两项，互不依赖、可独立关闭）：
   - `topic_recall`（纯规则、零费用）：输入主题词或节点 id（c:<分类id>/e:<条目id>），
     四路召回——FTS 命中、同分类路径共现、同 host 聚类、同线索显式关联；每条结果带
     relation_reason（`fts` / `cocategory:<路径>` / `same_host:<host>` / `thread:<线索名>`），
     按 source_type 分组。语义相似通道（LLM/embedding）按 §9.4 为可选项，留待 M4 embedding
     接入，本批不建死代码。
   - `thread_suggest`（LLM 后置）：输入线索条目集，LLM 按「概念→步骤→注意事项」建议初始
     排序；ctx.llm 为 None 或调用失败 → 按原序返回并记 llm_used=false（纯规则降级，
     不阻塞保存）。
   - TaskContext 新增可选字段 datalayer（召回型任务需要读库；既有任务不传不受影响）。
4. **Web API**（api.py，写端点全部过 check_write_access；审计走数据层）：
   GET /api/threads；POST /api/threads（支持 entry_ids 一并入库=路径固化）；
   GET /api/threads/{id}；POST /api/threads/{id}/update|delete|items|items/{iid}/remove|
   items/{iid}/move|suggest；POST /api/recall（只读，无令牌）；GET /api/entries/{id}/threads。
5. **UI**：新增 static/thread.html 串联工作区（线索列表 + 主题召回 + 线索编辑器 +
   LLM 建议排序）；index.html 侧栏加入口，检索结果视图加「🧵 固化为线索」（探索路径一键沉淀）。

**复检探针**（实现后逐条命中）

- 新库 init_schema 后 threads/thread_items 存在且 user_version=2；旧库（user_version=1）
  再次打开自动应用 002 且既有数据无损
- 线索 CRUD + 条目增删移 + 重开库不丢（持久化探针）
- 同线索重复加同一条目被拒；删除线索级联清 items
- topic_recall 对种子数据产出跨源条目且每条带 relation_reason；节点 id 输入（c:/e:）生效
- thread_suggest 在 llm=None 时原序降级；mock LLM 返回顺序被应用且不丢条目
- 全部写端点无令牌 403；recall 无令牌可读
- test_canary 的 ddl 与 capabilities 摘要随工单升版后全绿
- 变更文件 UTF-8 无 BOM + LF（字节扫描通过）

**复检结果**（2026-10-20 落地当日）

- 测试 **169 项全绿**（155 + 14）：tests/test_threads.py 覆盖迁移新库/旧库升级/库高于代码
  报错、CRUD 持久化（重开不丢）、条目规则（去重/夹紧/紧凑/级联/白名单）、重排集合校验、
  召回四通道与 relation_reason、节点 id 输入、suggest 降级与 LLM 应用（含漏号补齐）、
  Web API 全端点与写守卫、recall 免令牌。
- test_canary 已升版：ddl=865bbbd1078e（全量迁移拼接）、capabilities=bb91f4917209
  （新增 topic_recall@1.0.0 / thread_suggest@1.0.0）。
- 真实库冒烟（data/knowledge.db 副本，1866 active）：001→002 迁移无损；「Python」召回
  8 条跨源命中，示范 channels=['fts','cocategory:技术开发/后端','same_host:docs.python.org']；
  线索 CRUD 与 threads_for_entry 正常。
- 修复过程发现并钉住的两个问题：① thread_suggest 初版按编号序而非 LLM 建议序收集
  （回归测试 test_thread_suggest_applies_llm_order 钉住）；② topic_recall 线程通道
  最初豁免种子导致线程内共现种子丢关联解释（与 cocategory/same_host 口径统一）。
- 关联件同步：TODO Phase 4「串联工作区」标 [x]；SOP 增 §2.5 串联工作区用法；
  交接文档状态快照与待办刷新；契约草案 §9.4 的 thread_type 列已随 002 落库。

### 0.2.0 第三十三批（2026-10-20，变更工单）：放射导航增强——关系图三视图上的探索导向迭代

**来源**：TODO Phase 4「放射导航增强」；契约草案完整方案 §9.4 第 1–6 条
（Top-N 渐进披露 / 导航栈面包屑 / 边带 relation_reason / 双向反查 / 空层降级 / 路径固化）。
痛点：「知道大概方向，想顺线索探索发现遗漏」。**不推翻三视图**（总览→搜索子图→子树下钻
仍是主干），在其上叠加放射能力。

**旧 → 新**

1. **数据层**（db.py，纯查询无 DDL 变动，canary 不受影响）：
   - `radiate(node_id, per_channel=8)`：焦点一跳邻域。节点 id 约定 `c:<分类id>` /
     `e:<条目id>` / `d:<host>`（既有图约定）。通道与 relation_reason：
     分类焦点 → `child`（子分类）/ `attach:<origin>`（挂接条目）/ `parent`（父分类）；
     条目焦点 → `attach:<origin>`（直挂分类，带 path）/ `same_host:<host>`（同域名条目，
     复用 entries_by_host）/ `thread:<线索名>`（同线索，复用 threads_for_entry——
     与第三十二批串联工作区双向打通）；域名焦点 → `host_member:<host>`。
     每通道上限 per_channel，超出记 `truncated[通道]=剩余数`（前端「展开更多」依据）。
     焦点不存在返回 None（API 404）。**没有解释的关联不展示**：每个节点带 reasons[]、
     每条边带 reason。
   - `reverse_reach(node_id, limit=20)`：双向反查「哪些焦点能到达它」。条目焦点 →
     直挂分类（带 path）+ 同域名 + 同线索（kind=thread 带 thread.html url）；
     分类焦点 → 父分类 + 挂接条目 Top-N。域名节点不支持反查（返回 None）。
2. **Web API**（api.py，均只读免令牌）：
   GET /api/graph/radiate?node_id=&per_channel=；GET /api/graph/reverse?node_id=&limit=；
   未知节点 404。
3. **UI**（graph.html 重写导航层，渲染内核不变）：
   - 导航栈 + 面包屑：总览/搜索/子树/放射四类视图统一压栈，`关键字 › 集 › 簇 › 知识点`
     式面包屑任一级可回跳（防迷路）；
   - 放射模式开关（默认关，保 legacy 行为）：开启后点任意节点出邻域图（焦点居中固定、
     加大高亮）；放射视图内点击邻域节点持续下钻；域名节点点击恒走放射（原无动作）；
   - 边带 relation_reason：tooltip 恒显（节点聚合理由 + 边理由），「🏷 关联解释」开关
     控制边上的常驻标签（默认关防噪）；
   - 反查面板：「🔍 反查」按当前焦点列出可达焦点（分类带路径、线索可跳 thread.html）；
   - Top-N 渐进披露：服务端每通道 8 条，「展开更多」按 ×3 扩容（封顶 40），tip 显示
     truncated 计数（防毛球）；
   - 空层降级：焦点无任何邻域时不压栈、tip 明示（不强行补空节点）；
   - 路径固化：「🧵 固化为线索」把当前视图条目节点一键 POST /api/threads（复用第三十二批
     端点组），成功给 thread.html 直达链接；thread.html 增 `?id=` 参数支持；
   - index.html 侧栏关系图入口文案更新。
4. **语义边界**：relation_reason 全部由规则生成（§9.4「LLM 分工」纪律——共现/标签统计
   纯代码）；语义相似边仍留 M4 embedding，本批不建死代码。

**复检探针**（实现后逐条命中）

- radiate 对分类/条目/域名三类焦点均返回邻域，且**每个节点 reasons 非空、每条边 reason 非空**
- per_channel 上限生效且 truncated 计数正确（展开更多据此扩容）
- 条目焦点的 thread 通道带线索名；reverse 对条目返回分类（带 path）+ 域名 + 线索
- 空分类 radiate 返回空邻域（空层降级，不造节点）；未知节点 API 404
- radiate/reverse 免令牌可读；写端点（固化）无令牌 403（既有守卫）
- 面包屑回跳：任一级点击重现该层视图（UI 探针，手工 + 静态检查）
- pytest 全绿（新增放射导航测试）；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-20 收口，全命中）**

- 三类焦点 radiate 全过且 reasons/reason 完备：真实库「信息安全」放射出 `attach:llm`
  + `parent`，「AI绘图」空邻域（仅父分类，空层可辨）；条目焦点 `attach:rule/prior` +
  `same_host:github.com`（9 节点）+ thread 通道；域名焦点 `host_member`
- per_channel 截断：`{attach: 1}` 计数正确，per_channel=40 无截断；API 层夹紧 [1,40]
- reverse：条目 → 分类（带 path）+ 域名 + 线索（带 thread.html url）；分类 → 父 + 挂接
  Top-N；域名/未知 → None（API 404）
- 免令牌可读 / 写端点无令牌 403 / 带令牌固化 2 条成功（test_api_write_still_guarded）
- 测试 183 项全绿（+14：tests/test_graph_radial.py）；canary 不变（无 DDL / 注册表变动）
- 真实库副本冒烟：4 分类焦点 + 3 条目焦点 + 域名焦点放射全部带解释返回
- 变更文件 UTF-8 无 BOM + LF（字节扫描见收尾记录）

### 0.2.0 第三十四批（2026-10-20，变更工单）：统一入口工作台——搜索框升级为三视图切换

**来源**：TODO Phase 4「统一入口工作台」；契约 §9.4 定位条款——「统一入口为一个
搜索/输入框，输入后工作台同时呈现聚合结果 + 线索编辑区 + 一键切放射视图；
**模式是视图切换，不是启动分叉**」。痛点：检索、串联、放射探索三个入口分散，
用户要在三个页面间手动搬运上下文。

**旧 → 新**

1. **Web API**（api.py，新增一个只读端点）：
   `GET /api/threads-lookup?ids=<entry_id[,entry_id...]>` →
   `{map: {entry_id: [{id, name, thread_type}...]}}`——批量查条目所属线索
   （工作台「线索」视图聚合用；避免前端对 N 条命中发 N 个请求的 N+1）。
   注册顺序置于 `/api/threads/{thread_id}` 之前语义无冲突（路径前缀不同，
   `/api/threads-lookup` 与 `/api/threads/` 不共享段）。
2. **UI**（index.html 检索流程升级为工作台，其余视图不动）：
   - 检索提交后主区呈现**三视图切换条**（默认「聚合结果」）：
     - 「聚合结果」：`/api/search` FTS 命中 ∪ `/api/recall` 多路召回，按条目去重
       合并；每条带关联解释徽标（`全文命中` / `同分类:<路径>` / `同站点:<host>` /
       `同线索:<线索名>`）；保留🧵固化为线索按钮（对合并后全量条目）。
     - 「线索」：批量 threads-lookup 聚合当前结果所属线索（名称 + 条目数 + 跳
       thread.html 链接），无关联时明示；固化为线索按钮同样可用。
     - 「放射」：焦点 = 命中第一条（可点结果切换焦点）；`/api/graph/radiate`
       按通道分组列表（挂接/同分类/同站点/同线索各带 relation_reason），点邻域
       条目即切焦点持续下钻；「🕸️ 在图中打开」深链 graph.html。
   - 关键词输入框 placeholder 更新；`/api/recall` 对纯关键词 fallback：先当 FTS
     词查（既有 resolve 逻辑），无命中时聚合视图仍显示 FTS 结果，两源互补。
3. **graph.html 深链**：支持 `?node=c:<id>|e:<id>|d:<host>` 启动直达放射视图
   （工作台放射视图「在图中打开」的落点；无效节点回退总览）。
4. **语义边界**：聚合与徽标全部复用既有规则产物（topic_recall relation_reason /
   FTS snippet），零新增 LLM 调用；不建新表（canary 不变）。

**复检探针**（实现后逐条命中）

- threads-lookup：多 id 混合（有线索/无线索/不存在）返回正确 map；免令牌可读
- 检索后三视图切换无报错，聚合结果无重复条目且徽标齐全（静态检查 + 端点联测）
- 放射视图切焦点正常；「在图中打开」深链直达放射
- 既有功能不回退：分类浏览/暂存区/待清理/失效链接/固化为线索全保留
- pytest 全绿（+threads-lookup 测试）；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-20 收口，全命中）**

- threads-lookup：有线索/无线索/不存在混合查询 map 正确；空 ids 返回 `{"map": {}}`；
  免令牌可读（test_threads_lookup_batch）
- 端点链实跑（真实库 serve）：index 200 → search 50 hits → recall topic 5 hits →
  threads-lookup map 3 键（真实库尚无线索，全空属预期）→ radiate 焦点邻域返回 →
  graph.html?node= 深链 200
- 三视图切换/去重合并/徽标：前端逻辑静态检查（聚合 = FTS ∪ recall，channels 合并
  去重，fts 徽标去重）；既有视图（分类/暂存/候选/失效/舍弃）零改动
- pytest 184 项全绿（+1）；canary 不变（无 DDL / 注册表变动）
- 变更文件 UTF-8 无 BOM + LF（字节扫描见收尾记录）

### 0.2.0 第三十五批（2026-10-20，变更工单）：关系图节点弹窗卡——替换 ECharts tooltip 交互

**来源**：用户实图反馈（红字批注）——tooltip 里的「打开原文」没多大用：
①鼠标很难移上 tooltip（跟随鼠标即移即消，链接根本点不到）；②应弹窗显示概要；
③鼠标走弹窗隐；④鼠标点击再进原文。

**旧 → 新**

1. **Web API**（api.py，新增一个只读轻端点）：
   `GET /api/entries/{entry_id}/summary` → `{title, locator, source_type, created_at,
   snippet(正文前 400 字), categories(路径列表)}`——弹窗概要数据源（完整 detail
   含全文，悬浮场景过重；服务端截断防大文件）。
2. **UI**（graph.html）：
   - ECharts tooltip 对节点不再出框（边保留 tooltip——纯信息无链接，无此痛点）；
   - 新增 DOM 弹窗卡 `#nodecard`：悬浮节点 → 固定弹窗（不跟鼠标）显示名称/类型/
     路径/关联解释 + 条目懒加载概要摘要 + 「▶ 打开原文」按钮；
   - 交互按用户口径：鼠标在节点或弹窗上 → 弹窗保持；离开两者 → 250ms 后隐；
     点「打开原文」→ 新标签进原文（节点点击行为不变：分类下钻/放射模式下钻）；
   - 视图重渲染时强制收起弹窗，防残留。
3. **边界**：分类/域名节点无原文，弹窗只显示路径与关联解释；概要按 entry_id
   前端缓存，重复悬浮不重复请求；零 DDL / 注册表变动（canary 不变）。

**复检探针**（实现后逐条命中）

- summary 端点：有正文条目返回截断 snippet；无正文返回空串；404 正确；免令牌
- 弹窗卡：节点悬浮出现且不随鼠标跑；移入弹窗保持；移开即隐（静态检查 + serve 联测）
- 「打开原文」按钮带 locator 新标签打开；分类节点无该按钮
- pytest 全绿（+summary 测试）；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-20 收口，全命中）**

- summary 端点：有正文返回 400 字截断 snippet（空白归一，`第一段 摘要正文` 连体）；
  无正文空串；未知 404；免令牌（test_entry_summary_endpoint）；真实库实跑返回
  「Python 教程 — Python 3.8.6 文档」400 字 + 分类路径
- 弹窗卡：固定定位不跟鼠标（视口夹紧防出屏）；移入弹窗保持/双离开 250ms 隐；
  分类/域名节点无概要与打开原文按钮；视图重渲染强制收起（静态检查）
- 节点 ECharts tooltip 已抑制（返回空串），边 tooltip 保留
- pytest 185 项全绿（+1）；canary 不变（无 DDL / 注册表变动）
- 变更文件 UTF-8 无 BOM + LF（字节扫描见收尾记录）

### 0.2.0 第三十六批（2026-10-20，变更工单）：消费面守卫 + 工作区回退/兜底 + 大类弹窗豁免 + uv.lock 补账

**来源**：用户实图批注三条 + uv.lock 遗留问询。
①关系图总览出现无条目空类节点，且「已舍弃/失效/待清理」条目仍会出现在
下钻/放射/反查/路径固化/串联工作区等**知识消费页**——非活跃知识不该被探索到；
②thread.html「少了回退」+ 列表加载失败停在「加载中…」无兜底；
③大类节点不需要弹窗卡（不承载具体知识的顶层/中间节点，没有概要与原文）；
④uv.lock 遗留：第二十八批 `uv add`（markitdown 及可选依赖组）时新版 uv 重写了
锁文件（python 3.14 解析标记 + 传递依赖 cobble 等），pyproject 已提交而锁没跟上。

**旧 → 新**

1. **消费面守卫**（db.py，统一口径；管理页——待清理候选/失效链接/归档检索——不受影响）：
   判据 = `status='active'`（既有）且 `meta.value_flag != 'not_knowledge'`（待清理）
   且 `meta.link_status != 'dead'`（永久失效；error=疑似临时不判死）。落到全部
   消费读路径：graph overview/subtree/search/v0、radiate/reverse、search_fts
   （含 FTS 分支补上此前缺失的 status 过滤）、entries_by_host、
   get_entries_for_categories、get_thread items（线索里自动隐藏非活跃条目）。
   **空类剪枝**：overview 只出子树内可消费条目 >0 的一级大类；subtree/放射 child
   通道同理剪无可消费条目的子类（焦点根与祖先链上下文保留）。
2. **thread.html**：顶部加「← 返回工作台」；loadThreadList 加 try/catch 兜底
   （加载失败明示可刷新，不再停在「加载中…」）。
3. **graph.html**：弹窗卡只对条目节点出（分类/域名节点悬浮不再弹卡——点击行为
   不变：分类下钻/放射，域名放射；边的关联解释 tooltip 保留）。
4. **uv.lock**：`uv lock --check` 通过（锁与 pyproject 一致）后单独 chore 提交。

**复检探针**（实现后逐条命中）

- 打 not_knowledge / dead 标的条目：不出现在 overview/subtree/search_graph/radiate/
  reverse/search_fts/entries_by_host/get_thread；管理页 list_entries_by_value/link 照出
- 无可消费条目的一级大类不出现在 overview；子类剪枝后焦点根仍在
- status='rejected' 同样不出现（既有 active 过滤 + 本批守卫叠加）
- thread.html 加载失败显示错误态；有回退链接（静态检查）
- graph.html 悬浮分类/域名节点无弹窗（静态检查）
- pytest 全绿（+消费守卫测试）；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-20 收口，全命中）**

- 守卫测试 6 项（tests/test_consumable_guard.py）：not_knowledge / dead 条目在
  overview/subtree/search_graph/radiate/reverse/search_fts/entries_by_host/get_thread
  全部不可见；纯脏类（只挂非活跃条目）不进总览；空子类剪枝且焦点根保留；
  非活跃条目自身不能当放射焦点（404）；管理页 list_by_value_flag /
  list_by_link_status 照常全量
- 既有测试修正 1 处：test_sync_bookmarks_end_to_end 原断言「PostgreSQL 教程
  可 FTS」属旧世界——其 /docs/ 尾斜杠目录页本就被 L0 守卫打 not_knowledge
  （index_subdir），本批起按口径进不了消费页；改断言 SQLite 条目可检索 +
  PostgreSQL 待清理不可检索 + 管理页可见
- 真实库副本冒烟：待清理 6 / 永久失效 0；overview 由 6 类剪至 4 类且全部
  value>0（截图批注的空类节点消失）；「PostgreSQL」FTS 返回未打标条目；
  放射正常
- 三页 serve 实跑 200；pytest 191 项全绿（+6 守卫 -0）；canary 不变
- 变更文件 UTF-8 无 BOM + LF（字节扫描见收尾记录）

### 0.2.0 第三十七批（2026-10-20，变更工单）：弹窗卡提速/修打开原文 + 管理入口折叠 + 测试重名修正

**来源**：用户实图批注——①概要加载太慢、「不用太长吧？」；②弹窗卡「打开原文」好像失效；
③默认应该是消费页，数据采集/清理入口应折叠隐藏（大部分时候是消费数据）。

**根因**

- 概要慢：`/api/entries/{id}/summary` 走 `get_content` 拉全量正文（content_store 有
  百万字符级条目），悬浮场景只用开头几百字。
- 打开原文失效：locator 三种 scheme 前端一律当 href——http(s) 可开；
  `file://<配置根相对路径>` 两段式被浏览器解析为 host=配置根名（指向错误位置）；
  `emmx://` 浏览器不认。假链接必失效（浏览器还不允许 http 页面直接导航 file://）。
- 附带发现：tests/test_web_api.py `test_entry_summary_endpoint` 定义两次，
  后者覆盖前者，pytest 实际只收集一个。

**旧 → 新**

1. **db.py** 新增 `get_content_preview(content_hash, limit)`：SQL `substr(text,1,?)`
   只取前缀，不再整段进内存。
2. **api.py entry_summary**：改用 preview（limit=2000）→ 空白归一 → snippet
   截 400 → **160** 字（用户口径：不用太长）。
3. **graph.html 弹窗卡**：locator 以 http(s) 开头才渲染「打开原文」链接；
   file:// 与 emmx:// 改为只读 locator 文本 + 「⧉ 复制」按钮（file:// 为配置根
   相对路径；emmx 为脑图节点引用，均提示在对应工具打开）。隐藏延时 250→350ms
   （鼠标走到卡片的余裕更足）。
4. **index.html**：侧栏管理入口（暂存区/已舍弃/失效链接/待清理候选）折进
   `<details>`「🛠 数据管理（采集 / 清理）」，**默认收起**；消费入口（搜索工作台/
   关系图/串联工作区/分类树）保持顶层。"/" 本就服务 index.html（消费页），路由不动。
5. **tests/test_web_api.py**：删除重复定义的 `test_entry_summary_endpoint`，
   保留一份并更新断言（snippet 160、超长归一后截断）。

**复检探针**（实现后逐条命中）

- get_content_preview(hash, n) == get_content(hash)[:n]（有/无正文两态）
- summary snippet 长度 ≤160；无正文空串；404 不变
- graph.html 静态检查：仅 `^https?:` 渲染 anchor；复制按钮事件绑定存在
- index.html 静态检查：details#mgmt 默认无 open；四个管理入口在其内
- pytest 全绿；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-20，全命中）**

- get_content_preview 前缀 == get_content[:n]（含无正文 None、超长 limit=全文，
  tests/test_datalayer.py::test_get_content_preview_prefix）
- summary snippet 160 + 空白归一 + startswith 断言；无正文空串；404 不变
  （test_entry_summary_endpoint 重名定义已删，实测此前 pytest 只收集一份）
- 静态页探针 test_static_pages_consumption_defaults：graph.html 仅 /^https?:/
  渲染打开原文 + ccopy 复制按钮存在；index.html details#mgmt 存在且默认收起、
  四个管理入口均在块内
- pytest 193 项全绿；七个变更文件 UTF-8 无 BOM + LF
- canary 不变（无 DDL / 注册表变动）

### 0.2.0 第三十八批（2026-10-20，变更工单）：跨源去重（确定性判据：canonical + content_hash）

**来源**：TODO Phase 2 步骤 14（M2 落地）。真实库摸底：canonical 重复 2 组 4 条
（Edge/Chrome 同一收藏），content_hash 重复 63 组 140 条（同一文档多目录拷贝，
如 constitution×3、runtime_pitfalls×4）。

**范围裁定**：本批只做确定性判据（canonical URL / content_hash 完全一致）——
simhash 近似与 embedding 余弦（M4）误合成本高于漏合（合并伤害消费体验且需解释），
待真实需求驱动再立项；开源 simhash 实现届时先调研再定。

**合并模型（只标不删，与 value_flag 同款纪律）**

- 合并 = 主条目（组内 created_at 最早、可消费）attach_locator 副条目 locator
  （双 locator 进 entry_locators，可跳转）+ 副条目 meta 打 `dedupe_master=主id`
  与 `dedupe_reason`（canonical_hit / content_hit）；副条目**保留在库**、照常参与
  同步 upsert（meta 合并语义 `{**旧,**新}` 保标不抹）——不引入新 status、不动 DDL、
  canary 不变；删 meta 两键即恢复（可逆）。
- `_consumable` 追加 `dedupe_master` 为空条件 → 副条目从全部消费页（树计数/
  检索/图/放射/召回/线索）自动消失，管理侧不受影响。

**旧 → 新**

1. **pipeline/dedupe.py 补全**（原骨架仅 is_same_url）：
   - `_is_consumable(entry)`：Python 侧口径与 _consumable 一致（active + 无
     value_flag=not_knowledge + 无 link_status=dead + 无 dedupe_master）；
   - `find_master(dl, entry)`：canonical 优先、content_hash 兜底，在可消费条目中
     找（排除自身与已 merged），取 created_at 最早；
   - `merge_into(dl, master, dup, reason)`：attach_locator + merge_meta 打标 +
     log_task；幂等（attach INSERT OR IGNORE、标同值不翻转）；
   - `dedupe_entries(dl, entries)`：sync 入库后对新/更条目逐条判重（已有标跳过）；
   - `scan_and_merge(dl, dry_run)`：存量全库扫描——先摘「死标」（dedupe_master
     指向不存在/不可消费条目的，回归候选），再按 canonical / hash 分组合并；
     dry_run 只出报告。
2. **db.py** `_consumable` 追加 dedupe_master 为空条件（消费 SQL 片段单点改）。
3. **sync.py**：upsert 与 post_fetch 重分类后对 new_ids∪updated_ids 跑
   dedupe_entries，stats 记 `deduped`；`--dedupe-scan` 跳过源收集只跑存量扫描。
4. **cli.py**：ksync 加 `--dedupe-scan`（与 --value-scan 同款交互）。
5. **kadd.py** 不动（canonical 判重既有，方向=命中即附挂不建新，与本批互补）。

**复检探针**（实现后逐条命中）

- 书签+manual 同 URL：合并为一条消费可见，find_by_locator 两个 locator 均可查到主条目
- 两 folder 条目同正文：hash 命中合并；副条目从 search_fts/graph/radiate/
  recall/threads 消失（_consumable 单点生效）
- 同步幂等：副条目所在源重复 sync，标不抹、不重复建、不重复附挂
- 主条目被舍弃后扫描：死标摘除，副条目回归消费面（或换主）
- scan_and_merge dry_run 零写入；真实执行后统计与库一致
- pytest 全绿；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-20，全命中）**

- tests/test_dedupe.py 7 项：canonical 命中合并（书签+manual，双 locator 反查主）/
  hash 命中合并（两 folder 同正文）/ 消费面隐藏（search_fts/subtree/radiate/
  _consumable_count）/ 幂等+源重推保标 / 主被舍弃后死标摘除（dry_run 零写入）/
  scan_and_merge 分组+幂等 / canonical 优先于 hash
- 开发期修的两个方向性 bug（测试钉住）：①find_master 原只比候选不比自身——同批
  新建条目会互相当主、方向依赖遍历序；改为主条目 = 候选∪自身中
  (created_at or "9999", id) 最小者（None created_at 排最后，不与真实时间竞争）；
  ②find_by_canonical 只回任意一条——组内同伴漏检；新增 find_canonical_group 全组查询
- 旧断言升级：test_bookmarks 端到端的「跨文件夹重复 URL」fixture 本就是重复对——
  created_at 微秒差 3μs 在 ISO 秒级截断后并列，id 序定主；断言改为「恰好一条
  消费可见 + 副条目标指向主 + 检索命中的正是主」
- 真实库副本冒烟：dry_run {canonical 2 组, hash 63 组} 零写入 0.1s；真实执行合并
  77 条（组内 >2 展开）；副 locator 反查指主 ✓；检索/关系图不见副条目 ✓；
  二次扫描 merged=0 幂等 ✓
- pytest 200 项全绿（+7 dedupe）；九个变更文件 UTF-8 无 BOM + LF；canary 不变
  （无 DDL/注册表变动，dedupe_master 走 meta 键）

### 0.2.0 第三十九批（2026-10-20，变更工单）：邮件适配器——maildir 解析 + 会话线程还原 + 引用剥离

**来源**：TODO Phase 2 邮件适配器条目（IMAP 同步工具落 maildir → 本地解析）。
设计定调：本项目**不做 IMAP 直连、不碰凭证**——用外部同步工具（offlineimap 等）
把邮箱落成 maildir，适配器只解析本地文件；凭证问题的最小面 = 路径配置错误，
报错明确指向 `sources.mail` 配置项（探针①）。

**依赖（开源轮子核实）**：mail-parser-reply（PyPI 1.36，MIT，零运行时依赖，
月下载 379K，GitHub alfonsrv/mail-parser-reply）作引用剥离底座——多语言回复头
识别，中文（zh）标记 untested → 本项目自补中文回复头规则（「在…写道：」「发件人：」等），
双保险：库不可用/解析失败降级自研规则（"> " 引用行 + 中文头）。

**旧 → 新**

1. **迁移 003_mails.sql**（canary ddl 升版）：`conv_messages` 表——id（Message-ID
   归一，缺省 sha1 兜底）、entry_id、in_reply_to、subject_norm（归一化主题）、
   sent_at、thread_id（FK threads，可空；持久化映射保证重复同步幂等）。
2. **adapters/maildir.py**：maildir 目录（root/{cur,new,tmp} 与一层子文件夹，
   文件夹名入 meta.mailbox）逐 .eml 解析（email 标准库 policy.default）：
   RFC2047 中文标题解码、From/To/Date、text/plain 正文（无则 text/html 剥标签降级）。
   source_key = `{account}:{message_id}`（Message-ID 缺省 sha1(raw) 兜底，幂等）；
   locator = `mail://{account}/{message_id}`（mail scheme 契约既有预留）；
   created_at = Date 头。meta 记 account/mailbox/from/to/date/message_id。
   正文双轨：**inline_content = 增量正文**（quote_strip 剥引用后，检索摘要干净）、
   content_store = 全量正文（FTS 全文完整），content_hash = 全量 hash（跨源去重可用）。
   目录不存在/不是 maildir → AdapterError 指向 `sources.mail` 配置项（探针①）。
3. **pipeline/mail_threads.py**：Subject 归一化（去 Re:/Fwd:/回复:/转发:/答复: 等前缀链）
   + 线程分组（in_reply_to/references 链优先归到根 Message-ID；无引用头时
   account+subject_norm 归组）→ 组内 ≥2 封建 threads(thread_type='source')，
   thread_items 按 sent_at 排序 relation_type='seq'；conv_messages.thread_id 持久化，
   已映射的重复同步跳过（幂等）。引用剥离 quote_strip：mail-parser-reply 底座 +
   中文头自补 + 自研降级。
4. **sync.py / cli.py**：_BATCH_COLLECTORS 加 "mails"；upsert 后对 mail 源调
   _rebuild_mail_threads；stats 记 threads_built / messages_staged。
   依赖：uv add mail-parser-reply（pyproject 主依赖 + uv.lock）。
5. **db.py**：upsert_conv_messages / list_conv_messages（唯一碰 SQL 处）。
6. **canary**：ddl 摘要升版（003 新表即契约面）；SOURCE_TYPES/SCHEMES 无变化
   （mail 既有预留）。

**复检探针**（实现后逐条命中）

- maildir fixture 解析：中文标题/发件人/时间/正文正确入 meta 与正文；幂等 unchanged
- 目录不存在 → AdapterError 报错文本含 `sources.mail`（探针①）
- A→B(In-Reply-To)→C(References) 还原为一条 source 线程，轮次按时间序正确（探针②）
- 无引用头但 Subject 同链（原文 vs Re:）归入同一线程；不同主题不混
- 多层引用邮件：增量正文不含 "> " 引用块与中文回复头行；锚点=in_reply_to 指向被引用轮（探针③）
- conv_messages.thread_id 持久化：重复同步不重复建线程
- canary ddl 新值落常量；pytest 全绿；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-20，全命中）**

- tests/test_maildir.py 12 项：解析（中文标题 RFC2047/发件人/时间/正文/meta）/
  子文件夹 mailbox / 探针①路径报错（message+hint 均指 sources.mail accounts）/
  禁用源空返回 / source_key 幂等 / Subject 归一化与 Message-ID 归一 /
  quote_strip 三形态（英文 wrote:/中文「在…写道：」/QQ 邮箱「原始邮件」分隔）/
  无引用邮件原文兜底 / 探针② A→B→C 一条 source 线程轮次时间序 / 无引用头
  Subject 同链归组且不同主题不混 / 单封不建线程 / 端到端 ksync（含 content_store
  全量正文 + 增量 inline + 线程 + 二跑幂等）
- 开发期修的三个 bug（测试钉住）：①create_thread 返回 Thread 与 list_threads 的
  dict 取 id 方式不一致；②引用链通道给无引用消息也赋了组键 → subject 通道永轮空；
  ③引用链组未收编根消息（A 落单成 subj 组，线程只有 B/C 两封）
- 配置键统一：契约预留 sources.mail（config_keys 摘要不变），_collectors/适配器/
  测试统一用 "mail"；_validate_enabled_sources 的 mail 必填校验改为 accounts.*.path
- 真实库副本迁移冒烟：user_version 2→3 自动升版，1839 条 active 无损，检索正常
- pytest 212 项全绿（+12 邮件）；canary ddl 升版 567685343650（003 新表），
  test_threads 迁移断言升 3 并纳入 conv_messages 表检查
- 变更文件 UTF-8 无 BOM + LF（字节扫描见收尾记录）

### 0.2.0 第四十批（2026-10-20，变更工单）：书签扩散抓取——同目录系列内容显式扩抓

**来源**：2026-10-20 用户需求（像微信收藏步骤三「全扒」一样，书签不只抓原文，还抓
同一目录页同一主题的内容）。TODO Phase 2 预留条目落地。

**范围裁定（纯规则，可解释）**：扩散线索 = 种子页内链接中**与种子同目录**（同
scheme+host+父目录路径）者——正中「同一目录页同一主题」；整站同 host 链接不收
（导航/推荐噪音会演变成全站爬取，违背「显式触发、小步扩充」约束）。LLM 相似判定
后置（relation_reason 纪律：规则可解释先行）。

**模型**：种子 = 已入库书签/http 条目。`ksync --expand <entry_id>` 显式触发（不自动跑）：
现抓种子 HTML（fetcher 产物是 readability 纯文本，链接已丢，须读原文）→ 提取同目录
链接 → 过滤链（canonical 化去重锚点 → 排除种子自身 → 未入库 [find_by_canonical /
find_by_locator] → L0 价值守卫 judge_value 放行 → --expand-limit 截断，默认 20）→
逐条 fetch_with_fallback 抓正文 → 入库 + content_store + 照常 classify_coarse 分类。

**旧 → 新**

1. **models.py** SOURCE_TYPES 加 "expand"（canary source_types 升版；SCHEMES 不动，
   locator 仍 http）。新增枚举动机：扩散条目不得用 bookmark（书签源 full 同步
   archive_missing 会把它归档——它不在书签文件里），manual 语义（手动收录）也不准。
2. **pipeline/expand.py**：expand_seed(cfg, dl, locators, semantics, seed_entry_id,
   limit=20)——校验种子存在且 http(s)；现抓 HTML（httpx，复用 UA/超时配置）；
   urljoin 归一链接；同目录判定；候选过滤链；逐条抓取入库（source_key =
   `expand:{seed_id}:{canonical}` 幂等）；meta 记 seed_entry_id + expand_reason
   （"series_same_dir"，关联解释纪律）；put_content；分类复用 kadd 的
   classify_coarse 链路；task_log 全程留痕。
3. **cli.py / sync**：ksync 加 `--expand ENTRY_ID`、`--expand-limit N`（不进 run_sync
   主循环，CLI 分支直调 expand_seed，自含 start_run/finish_run 留痕）。
4. **index.html**：SRC_LABEL 补 { expand: "扩散" } 徽标。
5. **config**：无新键（limit 走 CLI 参数；不进 pyproject 依赖——纯标准库+既有依赖）。

**复检探针**（实现后逐条命中）

- 种子页含同系列链接（/series/02、/series/03）→ 扩散出条目且 meta.seed_entry_id
  指向种子、expand_reason="series_same_dir"（探针①）
- 不同目录链接（/other/x）与站外链接不产生条目
- L0 拦截：同目录下 /docs/ 尾斜杠列表页被价值守卫拦截，不产生条目（探针②）
- 重复 expand 同一种子 → 第二轮 created=0，canonical 去重（探针③）
- --expand-limit=1 截断生效
- pytest 全绿；canary source_types 新值落常量；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-20，全命中）**

- tests/test_expand.py 5 项（本地 HTTP fixture 多路由）：探针①同目录系列扩散
  （02/03 入库，meta.seed_entry_id 指种子、expand_reason='series_same_dir'、
  全文进 content_store）/ 探针② L0 拦截（/series/ 尾斜杠列表页 blocked_by_guard=1）
  + 不同目录与站外不收 + 种子自身 already_known / 探针③重复扩散 created=0
  （canonical 去重）/ --expand-limit 截断 / 非 http 种子拒绝
- 开发期修一处语义：种子自身链接计入 already_known（原 continue 不计数，
  幂等报告少一项）
- fetch_with_fallback http 分支不依赖 locators——扩散直接传真实注册表（无 shim）
- canary source_types 升版 25f37b30ac76（+expand）；SCHEMES 不动
- pytest 217 项全绿（+5）；九个变更文件 UTF-8 无 BOM + LF

## 0.2.0 第四十一批：时效守卫 freshness_flag——过期的、容易误导的知识清出来

**背景**：TODO 步骤「时效/可信守卫」（2026-10-20 用户需求）。与 L0 价值守卫同构：
纯规则信号、零费用、只标记不自动删，否决权与 value_flag=ok 同口径。
「易误导」的语义判定成本高，LLM 后置（YAGNI，规则信号不够再上）。

**变更**

1. **新增 semantic/freshness.py**（纯函数零 IO）：
   - `judge_text(title, body, *, stale_years=3, now_year=None)` → (flag, reason)：
     - 标题/正文自述关键词（已废弃/已过时/不再维护/deprecated 等）→ **stale/keyword**；
     - 正文可提取的最新日期（发布/更新/版权年份）早于 stale_years 年前 → **suspect/date_old**；
   - `extract_latest_year(text)`：日期提取（最后更新于/发布于/©/Copyright/日期模式），
     取最大年份（最后更新时间）；
   - `title_key(title)`：同主题聚类键（小写、去版本号 \d+(\.\d+)+、去标点）。
2. **sync._freshness_scan**（`ksync --freshness-scan [--dry-run]`）：扫全部 active
   条目（跳过 value_flag=not_knowledge、link_status=dead、freshness_flag=ok 否决件），
   正文取 inline_content + content_store 前 5000 字符；跨条目规则：同 host 同
   title_key 组内 ≥2 条、本条更旧（正文日期优先，缺则 created_at）→
   **suspect/newer_version**。命中打 meta.freshness_flag/freshness_reason/
   freshness_checked_at。死链比例信号后置（单条死链已有 link_status=dead 承接，
   host 级比例批量标储备疑，规则信号不够再上）。
3. **db.py**：`list_by_freshness_flag(flag)`；`_consumable` 追加排除
   freshness_flag=stale（过期知识退出消费面；suspect 保留可见）。dedupe.py
   `_is_consumable` 同口径。
4. **api.py**：`GET /api/freshness`（stale+suspect 分组，带 reason/checked_at）；
   `POST /api/entries/{id}/unflag-freshness`（否决 → freshness_flag=ok，之后不再标）。
5. **index.html**：数据管理区加「⏳ 时效候选」入口 + 视图（veto/一键舍弃同款交互）。
6. **config/依赖**：无新键、无新依赖（纯标准库）。

**复检探针**（实现后逐条命中）

- 标题含「已废弃」样本 → stale/keyword（探针①）
- 正文「最后更新于 2021-05」且 now_year=2026、stale_years=3 → suspect/date_old；
  正文日期 2025 → 不标（探针②）
- 同 host 同主题新旧并存 → 旧的进候选 suspect/newer_version、新的不标（探针③）
- freshness_flag=ok 后二次扫描不翻转（探针④，与 value_flag 口径一致）
- stale 条目退出消费面（_consumable）、suspect 保留；dry_run 零写库
- pytest 全绿；canary 不动（无 DDL/枚举/配置变化）；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-21，全命中）**

- tests/test_freshness.py 11 项：探针①标题/正文自述关键词 → stale/keyword
  （防误杀反例：token 过期时间、正文裸提及 deprecated 不触发）/ 探针②
  「最后更新于 2021-05」→ suspect/date_old、2025 不标、无日期不标 /
  探针③同 host 同主题（Python 3.6 vs 3.12 去版本号同键）旧的进
  suspect/newer_version、新的不标 / 探针④freshness_flag=ok 二次扫描不翻转
  （stale 计数归零、meta 保持 ok）/ dry_run 零写库 / 待清理与死链条目跳过
  / 消费读路径实测 stale 不可见、suspect 可检索，管理视图全量列出
- 开发期修两处：日期提取预检正则误入 findall 循环（无分组返回整串导致
  ValueError）拆出独立预检；同日期并列条目被 id 决胜随机误标 newer_version
  ——改为日期并列即跳过（id 只作排序稳定用）
- 真实库副本 dry-run 冒烟：1837 扫描，stale 0（强信号窄口径符合预期）、
  suspect 87（date_old 85 + newer_version 2），只报告未写库
- _consumable SQL 片段与 dedupe.py Python 口径两处同步（freshness_flag!=stale）
- canary 六面不变（无 DDL/枚举/配置键变化）；pytest 228 项全绿（+11）；
  十一个变更文件 UTF-8 无 BOM + LF

## 0.2.0 第四十二批：手动收录 UI 入口 + 复制条目 ID（用户两点反馈）

**背景**：①扩散抓取需要 entry_id，但 UI 不展示——加「复制 ID」；②手输 URL 抓取
网页内容的能力（kadd / POST /api/entries）已存在但无 UI 入口——补上。

**变更**

1. **index.html**：
   - 数据管理区新增「🔗 手动收录」输入框（粘贴 http(s) 网址 → POST /api/entries
     → 走 kadd 的 ingest_url：抓正文 → 归类 → 入树），结果显示 entry_id
     （可复制，直接接 ksync --expand）、抓取/归类状态；重复收录幂等提示。
   - 「复制 ID」按钮（🆔）：bindEntryButtons 统一注入——所有带 data-id 的条目行
     （分类列表/检索/待清理/时效/聚合等全部视图）自动获得，点击复制，
     无需逐视图改模板。
2. **graph.html**：节点弹窗卡对 entry 类型加 ID 行（显示 16 位 id，点击复制）。
3. **api.py / 后端**：零改动（/api/entries 已有）。

**复检探针**（实现后逐条命中）

- index.html 出现 add-url 输入框与 🆔 注入逻辑；graph.html 弹窗卡含 ID 行
- POST /api/entries 幂等（重复 URL 返回 status=duplicate）
- pytest 全绿（静态页断言补新元素）；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-21，全命中）**

- index.html：数据管理区出「🔗 手动收录」输入框（回车/按钮均可触发），结果行
  显示 entry_id（点击复制，title 指引 ksync --expand）+ 抓取/归类状态 +
  duplicate 幂等提示；bindEntryButtons 统一注入 🆔——全视图条目行自动获得
- graph.html：entry 弹窗卡出「ID：<16 位> ⧉」行，点击复制（.ccid 独立通道，
  与 locator 复制互不干扰）；eid 提升到 showCard 顶部消除重复声明
- 后端零改动；POST /api/entries 幂等由 test_manual_ingest_endpoint_idempotent
  钉死（本地 HTTP fixture：created+fetched → duplicate 同 id → 缺 url 400）
- 静态页探针升级：五个管理入口均在 mgmt details 内 + add-url/cid-btn/ccid 断言
- pytest 229 项全绿（+1）；四个变更文件 UTF-8 无 BOM + LF

## 0.2.0 第四十三批：词云视图 v0（scoped cloud 三态词元）

**背景**：TODO 步骤「词云视图」——范围随焦点分类子树变化；分类词元点击进入
子分类并联动分类树；内容词元点击 = facet 过滤当前范围；字号 ∝ √权重；
按主导顶层分类着色。v0 划范围：词元来源=子树内可消费条目标题+内联正文
（jieba tf-idf，main 依赖已含 jieba 0.42.1）；分类词元=focus 直接子分类；
返回全库走「↩ 全库」（逐级回退后置，词云刷新即重新出发）。

**变更**

1. **db.py**：`cloud_data(category_id, *, sample=800)`——focus 子树（None=全库）
   的分类词元（直接子分类 + 可消费条目数，空类剪枝）与内容词元样本
   （DISTINCT 近 sample 条，带每条直挂分类的顶层根，多父取最小 id 保确定）；
   `cloud_facet(category_id, word, limit=50)`——子树内可消费且标题/内联正文
   含该词的条目（内容词元点击的 facet 数据源）。
2. **api.py**：`GET /api/cloud?category_id=&limit=&word=`——分类词元 + 内容词元
   （jieba tf-idf top8/条聚合计数，过滤单字/纯数字；主导顶层分类 + 12 色板配色，
   按词元总量降序分配）；`word` 参数 facet 模式追加 entries 列表。
3. **index.html**：侧栏常驻「☁️ 词云」入口；工作台 tabs 加 cloud；renderCloudTab
   渲染范围条 + 分类词元（点击→currentCat+loadTree+highlightInTree 联动+
   刷新词云）+ 内容词元（字号=13+22√(count/max) px，点击→facet 条目列表，
   复用 entryHTML/bindEntryButtons）；↩ 全库复位。
4. **配置/依赖/canary**：零新增（jieba 已是 main 依赖；无 DDL/枚举/配置键变化）。

**复检探针**（实现后逐条命中）

- 切到某大类，词云只反映该子树条目（他子树条目不出现在样本/facet）（探针①）
- 分类词元点击 → currentCat 同步 + 树定位高亮 + 词云范围切换（探针②）
- 内容词元点击 → 当前范围按该词过滤出条目列表（探针③）
- 字号随计数非线性增长（√权重）、颜色按主导顶层分类（探针④）
- pytest 全绿；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-21，全命中）**

- tests/test_cloud.py 7 项：探针①范围隔离（mq 子树词元无生活主导词、facet 只出
  子树条目）/ 探针②前端静态断言（cloud-cat 点击 → currentCat 同步 +
  highlightInTree 树定位 + 词云刷新）/ 探针③内容词元 facet（word=消息 → 恰 2 条，
  待清理与生活条目不出）/ 探针④字号公式（Math.sqrt(w.count / max)）与配色断言；
  另有 db 层空类剪枝/顶层根确定性/空范围不炸 + 噪音词元过滤用例
- 开发期修两处：db 返回键 children→categories 统一；jieba 对「消息总线」类
  未登录词会切碎——测试语料改词典稳定词；冒烟另暴露 markdown/导出噪音
  （##/---/NaN/PASS/Unnamed 曾占词元榜首）→ _cloud_word_ok 三道闸
  （须含字母/非纯符号/噪音停用词）后真实库词元干净（md/skill/技能/模板/LLM/API…）
- 真实库副本冒烟：800 样本聚合 5.3s（首次含词典加载），顶层词元
  技术开发 821 / 软件与ERP 671 / 人工智能 268，词元主题分布合理
- canary 六面不变（无 DDL/枚举/配置键变化）；pytest 236 项全绿（+7）；
  五个变更文件 UTF-8 无 BOM + LF

## 0.2.0 第四十四批：时间线视图 + 陈旧分支提醒（最后大件收官）

**背景**：TODO 步骤「时间线视图 + 陈旧分支提醒（长期无新内容的分支提示清理或
归档）」——视图四件套（串联/放射/工作台/词云）的最后一块。

**设计要点**

- 时间轴走 **created_at**（内容时间：书签收藏时间/文件创建时间），不走
  exported_at（入库时间，全库挤在同一批无分布意义）；无 created_at 的条目
  （folder 源等）诚实进「时间未知」计数，不编造时间。
- 与词云同构的 scoped 范围：焦点分类子树（currentCat，null=全库）。

**变更**

1. **db.py `timeline_data(category_id, *, granularity=None, bucket=None,
   stale_years=2)`**：
   - 分桶：granularity=None 自适应（跨度 >24 个月→year，否则 month），可显式
     覆盖；空桶补齐（连续区间，ECharts 轴均匀）；buckets=[{key,label,count}]；
   - unknown_count：created_at 缺失的可消费条目数；
   - bucket 参数：返回该桶条目列表（按 exported_at 近序，limit 100）——柱点击
     下钻，首屏不返回全量；
   - stale_branches：子树内**叶子分类**（无子节点的分类）的可消费条目数 +
     max(created_at)，latest 超 stale_years 年 → [{id,name,latest,count,
     age_years}]（age 降序）；max 为 NULL 的分支进 unknown_branches
     **不判陈旧**（时间未知 ≠ 陈旧，只标不删可逆模型同款口径）；
   - span {min,max}（有 created_at 的极值）。
2. **api.py `GET /api/timeline?category_id=&granularity=&bucket=&stale_years=`**：
   聚合上述数据 + threshold_years 回传（前端明示规则）。
3. **index.html**：侧栏常驻「📈 时间线」入口；工作台 tabs 加 timeline；
   renderTimelineTab = 范围条 + ECharts 柱状图（复用 vendored echarts.min.js，
   与 graph.html 同源）+ 柱点击下钻桶条目（复用 entryHTML/bindEntryButtons）
   + 年/月粒度切换 + 「🕰️ 陈旧分支提醒」区块（分支名/最新条目时间/停滞年数/
   条目数/「📍树中定位」——currentCat 同步 + loadTree + highlightInTree，
   与词云分类词元同款联动）。
4. **配置/依赖/canary**：零新增（echarts 已 vendored；无 DDL/枚举/配置键变化）。

**复检探针**（实现后逐条命中）

- 切到某子树，桶只反映该子树条目（他子树条目不出现在桶/bucket 下钻）（探针①）
- 粒度自适应：跨 2020-2026 → year；单年数据 → month；显式 granularity 覆盖（探针②）
- 叶子最新条目超 2 年 → 进 stale_branches；有新条目的叶子不命中；无 created_at
  的分支进 unknown_branches 不判陈旧（探针③）
- bucket 模式返回该桶可消费条目（待清理/死链不出）；空桶不炸（探针④）
- stale_years 参数化（传 10 → 6 年前的叶子不 stale）（探针⑤）
- pytest 全绿；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-21，全命中）**

- tests/test_timeline.py 7 项：探针①范围隔离+月粒度空桶补齐（mq 子树跨度
  8 个月≤24→month，中间月补 0）/ 探针②粒度自适应（全库 66 个月→year、
  数据库叶子单月→month）+ 显式覆盖 / 探针③陈旧分支（消息队列停滞 5.6 年
  进 stale、数据库有新内容不命中、生活无 created_at 进 unknown 不判陈旧）
  / 探针④bucket 下钻可消费口径（待清理不出、空桶不炸）/ 探针⑤阈值参数化
  （10 年阈值不 stale）/ API 结构 + 前端静态探针（tl-link/tab/echarts 复用/
  陈旧分支区块明示规则）
- 开发期修三个真 bug：①叶子分类查询用错列（category_id=子节点列，叶子应查
  parent_id 列——原实现把「根分类」当叶子，子树全漏判）；②datetime 时区
  混比（created_at 带 +08:00 vs now() naive → TypeError，统一 UTC aware）；
  ③bucket 匹配绑死当前粒度宽度（month 模式传 "2020" 永远落空 → 改长度
  自适应前缀匹配，前端行为不变、直调更友好）
- 真实库副本冒烟：全库年粒度 2011-2026（2015-2022 收藏高峰、2026 批量 673），
  时间未知 792（folder 源诚实计数不编造）；陈旧分支：后端 274 条停滞 4.7 年、
  系统工具 15 条 5.5 年、信息安全 5.6 年——正是值得提醒清理的分支；
  bucket 2020 下钻 87 条 0.18s；子树范围隔离正常
- canary 六面不变（无 DDL/枚举/配置键变化）；pytest 243 项全绿（+7）；
  五个变更文件 UTF-8 无 BOM + LF
