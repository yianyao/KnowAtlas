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
