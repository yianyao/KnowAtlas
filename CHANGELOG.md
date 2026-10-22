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

## 0.2.0 第四十五批：三种导出格式（M5 Gate 前半）——JSON/Obsidian/OPML

**背景**：TODO Phase 5「导出与运维」Gate 前半「三种导出格式验证通过」。
CLI 的 kexport 骨架早已预留（--format json|obsidian|opml --out），SOP-E 已
约定形态；本批把三个 stub 实现落地。

**设计**

- 导出是数据层的**投影**，不碰原始源（SOP-E 纪律）；
- JSON 走 schema 版本化契约（schema_version 常量，未来破坏性变更靠它分流）；
- 正文策略：JSON 内联 inline_content（短摘要，检索摘要口径），content_store
  全量正文不内联（百万字符级，用户按需自行拷贝目录——SOP-E 注明）；
- OPML「书签类」判定 = locator_canonical 以 http 开头（知识源自网页的确定性
  判据，可解释；file:///mail:///emmx:// 天然排除）；
- OPML 导入（反向回路）后置——本批验证格式往返保真（导出文件可被标准 XML
  解析重建无损树），作为 ksync 新源是独立批次；
- Obsidian 条目笔记放**主分类**目录，但所有父分类 MOC 都双链它（Obsidian
  短链全局解析，多父不丢）。

**变更**

1. **db.py**：新增 `all_entry_locators() -> dict[str, list[str]]`（一次查询拿全
   附加 locator，供导出投影；公开方法，不摸 _conn）。
2. **新增 pipeline/export.py**（纯投影零 LLM 零网络）：
   - `export_json(dl, out) -> stats`：schema_version/generator/exported_at/
     counts/categories（含 parents DAG）/entries（含 locators+categories+
     meta+inline_content）/threads/conv_messages；
   - `export_obsidian(dl, out_dir) -> stats`：条目笔记（frontmatter + 正文 +
     `[[MOC]]` 回链）+ 每分类 MOC（`[[条目]]` 双链 + 子分类链接）；文件名
     安全化（去 `\/:*?"<>|`、截 80、重名加 id 后缀）；
   - `export_opml(dl, out) -> stats`：分类 DAG 展平为 outline 树（多父重复
     出现），叶子 = http canonical 条目（htmlUrl + title）。
3. **cli.py**：_cmd_kexport 落地——三格式分发 + 统计打印（目录自动建）。
4. **SOP**：§7 补正文策略与 OPML 书签类判定说明。

**复检探针**（实现后逐条命中）

- JSON 含 schema_version 且 counts 与库对账；entries 带 locators/categories/meta（探针①）
- Obsidian：每分类有 MOC；条目笔记有 frontmatter + `[[MOC]]` 回链；文件名
  安全化；多父条目在所有父 MOC 出现（探针②）
- OPML：XML 可解析；outline 嵌套=分类层级；叶子数=http 条目数；导出文件
  解析重建树无损（往返保真）（探针③）
- CLI 三格式真跑 tmp 目录成功；pytest 全绿；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-21，全命中）**

- tests/test_export.py 5 项：探针① JSON（schema_version=1.0 + counts 对账
  + entries 带 locators/categories/meta/inline_content + archived 在全量投影
  + 分类 parents DAG）/ 探针② Obsidian（MOC 在各分类目录、条目 frontmatter +
  回链全部父 MOC、多父条目两 MOC 都列、file/mail 条目在 vault、archived 不在、
  文件名安全化重名避撞）/ 探针③ OPML（XML 可解析、嵌套=层级、e1 三路径多父
  不丢、叶子=http 条目数、往返重建无损）/ CLI 三格式真跑 + 未知格式 EXIT_BUSY
- 工单即时增补：db.py 增加 all_categories_dag / all_entry_categories 两个公开
  投影方法（原计划只有 all_entry_locators——JSON/Obsidian/OPML 都需要分类 DAG
  与条目-分类映射，公开方法不摸 _conn）
- 开发期修三个真 bug：①`_EXIT_ERROR` 常量不存在（真名 EXIT_BUSINESS，NameError
  直接暴露）；②Obsidian MOC 只列主分类条目——多父挂接的另一侧丢失（违背工单
  「所有父 MOC 都双链它」承诺，改 MOC 列全部直挂、笔记目录仍用主分类）；
  ③修②时把 cids 移出笔记循环导致 parent_links/tags 泄漏成最后一条目的分类
  （Python 循环变量泄漏的经典坑，测试抓出）
- 真实库副本冒烟：JSON 6976 条全量（15 分类，schema 1.0）；Obsidian 1837 篇
  笔记 + 15 MOC（1852 个 md）；OPML 161 个 http canonical 书签叶（真实库
  bookmark 源中 locator_canonical 为空的条目天然排除，口径可解释）
- canary 六面不变（无 DDL/枚举/配置键变化）；pytest 248 项全绿（+5）；
  五个变更文件 UTF-8 无 BOM + LF

## 0.2.0 第四十六批：自动备份 + MCP 只读端点（M5 Gate 后半；打包安装按用户指示后挪）

**背景**：TODO Phase 5 剩余两项（打包安装 2026-10-21 用户明示后挪，TODO 保留未勾选）。
备份用 SQLite 官方 VACUUM INTO（一致性快照、WAL 安全——直接拷 .db 会丢 WAL 内
数据，用内置机制不自己拷文件，开源轮子铁律）。

**变更**

1. **新增 pipeline/backup.py**（纯 SQLite 机制零自研）：
   - `snapshot(cfg, dl, *, keep=10, min_interval_hours=24, force=False)`：
     VACUUM INTO 落 `knowledge-YYYYmmdd-HHMMSS.db`；节流（目录内最新快照未超
     min_interval_hours → skipped）；轮换保留最近 keep 份删最旧——删除白名单
     （仅 backup_dir 内 + knowledge- 前缀 + .db 后缀 + 时间戳名格式，防误删
     用户文件，个人文件安全纪律）。
   - `restore(cfg, dl, snap_path)`：snap 须在 backup_dir 内（防路径穿越）；
     恢复前对当前库自动快照（安全网）；调用方负责先 close dl（CLI 层做）；
     删目标 db 的 -wal/-shm；copy2 快照回 db_path；恢复后 sanity
     （integrity_check + 条目数）。
   - `verify_snapshot(snap_path)`：integrity_check + entries 数 + 文件时间
     （恢复演练验证手段）。
2. **sync.py**：run_sync 主体（非 scan 分支、非 dry_run）开头 snapshot；
   stats["backup"]。契约=没快照不同步：失败默认中断（返回 error 统计），
   `general.backup_on_sync=false` 可显式关闭。
3. **config.py**：CONFIG_SCHEMA_KEYS +3（backup_on_sync/backup_keep/
   backup_min_interval_hours）+ 快捷属性；example toml [general] 补注释。
4. **api.py**：`/api/mcp/search`（q/limit）、`/api/mcp/tree`、
   `/api/mcp/entry/{id}`（正文前 4000 字符）——只读投影。真 MCP 协议
   （stdio/SSE，需 mcp SDK）后置不加依赖；v0  REST 形态文档注明。
5. **cli.py**：kbackup 落地——--snap / --restore FILE / --verify FILE /
   --keep N / --no-throttle；restore 分支先 dl.close() 再操作。

**复检探针**（实现后逐条命中）

- 探针①：WAL 开启下从快照恢复（删 -wal/-shm）后条目数与快照时一致
- 探针②：轮换 keep=2，快照 3 次后剩 2 份且最旧的被删
- 探针③：节流——min_interval_hours 内二次快照 skipped；force 强制
- 探针④：run_sync 主体后 backup_dir 有新快照；dry_run/scan 分支不产生
- 探针⑤：MCP 只读校验——AST 扫描三个 handler：无写操作调用、无裸
  _conn.execute 非 SELECT
- 探针⑥：restore 前自动安全网快照（恢复前库多一份快照）
- 真实库副本恢复演练一次成功（Gate「备份恢复演练一次成功」）
- pytest 全绿；变更文件 UTF-8 无 BOM + LF

**复检结果（2026-10-21，全命中）**

- tests/test_backup.py 9 项：探针① WAL 开启下恢复后条目数与快照时一致（3 条
  快照 → 追加至 8 → 恢复回 3，-wal/-shm 已清；注意 WAL 模式持久化在 db 头、
  之后新连接会重建 -wal 属正常行为）/ 探针② 轮换 keep=2 三次快照删最旧 /
  探针③ 节流 skipped + force 强制 / 探针④ run_sync 主体后有新快照、dry_run
  不产生 / 探针⑥ 安全网快照（恢复前 8 条形态留底）/ 白名单（目录外快照拒绝、
  目录内非自家命名拒绝且原样不动）/ CLI 三模式真跑 / 备份失败中断同步不写库
- tests/test_web_api.py +2：MCP 三端点 200+结构+404；探针⑤ AST 只读校验
  （写方法黑名单 + 不摸私有 _conn + 无非 SELECT SQL，测试钉死）
- 真实库副本恢复演练（Gate「备份恢复演练一次成功」）：快照 integrity=ok
  全库 6976；模拟破坏（50 条 active→archived）后恢复，active 1837/全库 6976
  与快照时完全一致；恢复前自动安全网快照留底
- 真实库副本 MCP smoke：search q=python 20 命中 / tree 6 顶层分类 /
  entry 详情含正文前缀 701 字符 / 404 正常
- canary 升版：config_keys 31d80a965903→efd23b704e45（+3 备份配置键）；
  pytest 258 项全绿（+10）；十一个变更文件 UTF-8 无 BOM + LF
- 开发期修：①Windows 上 Path("/proc/...") 是项目根相对路径（mkdri 反而成功）
  ——失败用例改用「文件当目录」构造，并清理项目根 proc 测试残留；②快照同秒
  重名的避让名不合白名单正则 → 改为跨秒等待并同步 name；③restore 原要求
  调用方先 close，但安全网快照需要活连接 → 改自包含（内部 close）；④dry_run
  误走备份 → 加 not dry_run 条件；⑤_consumable 无关——本轮无消费面变更

## 0.2.0 第四十七批：第四十六批复审修复（MCP 计数封顶 / 安全网轮换口径 / restore 占用预检）

**背景**：第四十六批代码精读复审（2026-10-21）发现三处边角问题，趁恢复链路
上下文还热修掉（打包安装前的低成本清理）。

**变更**

1. **db.py / api.py**（MCP tree 未分类计数封顶）：`/api/mcp/tree` 原用
   `len(get_uncategorized(limit=1000))` 计数——超 1000 条时给 agent 假数字。
   DataLayer 新增 `count_uncategorized()`（精确 COUNT，口径与暂存区一致
   = active 且未挂分类），mcp_tree 改用之。
2. **backup.py restore 安全网轮换口径**：安全网快照原硬编码 keep=10，改读
   `cfg.backup_keep` 与日常快照一致；连带发现并修复——安全网快照的轮换可能
   把本次恢复的源快照当「最旧」删掉（keep 小、存量多时 copy2 直接无源），
   `snapshot()` 增 `protect` 参数，轮换跳过受保护文件名（份数暂 keep+1，下轮收敛）。
3. **backup.py restore 占用预检 + 结构化失败**：①恢复前探测本机 serve 端口
   （`general.server_port`，默认 8420）——可连通即拒绝（恢复是文件级操作需
   独占 db，报错指路「先停止 serve」）；②删 -wal/-shm 与 copy2 阶段 OSError
   不再裸抛 traceback，结构化返回并指路安全网快照回滚（原库文件本体未动，
   仅可能丢 -wal 未 checkpoint 数据——安全网快照含完整恢复前形态）。

**复检探针（实现后逐条命中）**

- 探针A：1001 条未分类 → count_uncategorized=1001（list+LIMIT 旧口径出 1000）
- 探针B：MCP tree uncategorized 精确（单条目场景 =1）
- 探针C：backup_keep=2 + 存量 2 快照 → restore 后源快照仍在、恢复成功
- 探针D：serve 端口占用 → restore 拒绝且库未被触碰
- 探针E：copy2 抛 PermissionError → 结构化 error 含安全网快照名，快照可 verify

**复检结果（2026-10-21，全命中）**

- test_datalayer.py +2（探针A/B）、test_backup.py +3（探针C/D/E）、
  test_web_api.py MCP 用例 +1 断言（探针B）
- pytest 263 项全绿（258→263）；canary 不变（无 DDL/dataclass/scheme/config 键变更）
- 变更文件 UTF-8 无 BOM + LF

## 0.2.0 第四十八批：关系图放射模式三处修复（child 缺边 / 焦点挤视口左上 / reason 原始码透出）

**背景**：用户截图（放射：放射技术开发）实锤——焦点+挂接条目整团挤在视口
左上被裁剪、标签叠成一团；子分类节点漂在画布中央冒充主要内容；弹窗卡
关联理由显示 `attach:rule` 原始码。

1. **db.py radiate child 通道缺边**：分类焦点时 child 通道只 add_node 不
   add_edge——子分类成孤立节点（14 节点 8 边的来源：8 条挂接边，5 个子分类
   全孤立）。补 `add_edge(c:<id>, "child")`，tooltip/理由标签恢复正常语义。
   既有测试焦点全取叶子分类（无子分类），故从未暴露。
2. **graph.html 放射布种**：焦点 fixed 在 (0,0)=视图坐标原点=包围盒左上角，
   自动 fit 后整团挤在视口左上。改为非焦点节点绕原点环形布种（黄金角
   ≈137.5°，分类 260 / 条目 170 / 域名 140 半径 + 抖动），包围盒以焦点为
   中心，fit 后焦点居中、邻域放射展开。
3. **graph.html reason 显示格式化**：新增 `fmtReason()`（attach:rule →
   挂接·关键词规则；未识别段原样），四处展示点统一（节点弹窗卡 / 边
   tooltip / 🏷边标签 / 反查面板）。

**连带修复（第四十七批遗留）**：test_backup.py bcfg 夹具缺 server_port 键，
本机真跑着 serve（8420）时 restore 用例全被端口预检误判拦截——夹具显式
`server_port: 0`（connect 必败），测试与宿主机环境解耦。

**复检**：pytest 264 项全绿（263→264，新增 child 边测试）；canary 不变
（无 DDL/scheme/config 键变更）；graph.html 经浏览器冒烟（无 JS 错误）。
生效说明：前端两项刷新页面即生效；child 边需重启 serve。

## 0.2.0 第四十九批：文档挂账收尾——勾选遗漏补勾 + bookmarklet 前端落地

**背景**：待办盘点（2026-10-21）发现两类文档债：①TODO 里 16 项早已落地有
测试背书但复选框未勾（Phase 0 全部 8 项、Phase 0.5 骨架/数据层/kadd/http
simple/FTS5/安全中间件、Phase 1 先验映射与 10 大类）；②SOP §2.4 承诺的
bookmarklet 前端从未实现，且实现层另有暗坑。

1. **TODO 补勾 16 项**：逐项核对代码/测试证据后勾选并注明依据；探针未跑的
   如实挂账（CI"故意提交破坏看红"演练未单做，canary 拦截能力由套件内
   canary 测试同源保证）。回归测试集 v0 不在补勾范围（真未做）。
2. **bookmarklet 方案裁决**：SOP 原描述"no-cors POST 带 ?token="在实现层
   走不通——`check_write_access` 严格只收 application/json（415），而浏览器
   no-cors fetch 只能发 CORS-safelisted content-type，JSON 根本发不出去；
   且 no-cors 响应为 opaque 无反馈、令牌明文进书签栏。改为：bookmarklet
   `GET 跳转 index.html?add=<当前页URL>` → 首页启动逻辑展开「数据管理」区、
   填入手动收录框并自动提交——**复用既有手动收录链路（第 42 批），零新机制**；
   写凭据走同源会话 Cookie（HttpOnly），令牌不出书签栏，第三方网页拿不到；
   `history.replaceState` 清参防刷新重发；只收 http(s)。
3. **文档对齐**：SOP §2.4 bookmarklet 段按新机制重写；api.py 安全约束注释
   第 5 条同步（CORS 不放宽的理由更新为"bookmarklet 走同源跳转"，
   `?token=` 降为 CLI/脚本兜底）。

**验证**：pytest 全量通过（exit 0；改动面为前端/文档/注释，无测试变更）；
浏览器实测 10 项全过——bookmarklet href 动态拼 origin 正确、`?add=` 落地
自动展开/填充/提交、duplicate 幂等反馈（"该网址已在库中，未重复建"）、
query 参数清除、控制台无 JS 错。canary 不变。

## 0.2.0 第五十批：OPML 导入回路（ksync 批量源收账）

**背景**：第 45 批 OPML 导出实现时挂账"导入回路后置（ksync 新源独立
批次）"——本批收账，打通 OPML 往返（导出 → 外部流转/备份 → 回吃重建）。

1. **新适配器** `adapters/opml.py`（source_type=opml）：outline 树 →
   统一条目。契约要点：
   - outline 嵌套 → native_path（免费分类信号，走先验映射，不命中进暂存区）；
   - 只收有 htmlUrl 的 http(s) 条目；type="rss" 订阅源（只有 xmlUrl）跳过
     计数；非 http 的 htmlUrl 计数跳过（与 bookmark 源同一纪律）；
   - created 属性 ISO 8601（本工具导出形态）优先、RFC 822（OPML 2.0 惯例，
     email.utils 标准库）兜底，都失败置 NULL 不臆造；
   - source_key = 文件路径 + outline 全路径 + 标题兜底（OPML 无稳定节点 id，
     文件改名=换源，SOP §2.14 注明）；同 URL 多分支各建一条计数
     （M2 跨源去重统一兜底）；
   - 单文件缺失/坏 XML/缺 body/未配 files → AdapterError，message+hint 指路
     `[sources.opml]`（隔离原则：跳过本源，其余源继续）。
2. **接线**：SOURCE_TYPES 增 "opml"（复用 bookmark 会被书签源 archive_missing
   误归档，必须独立 source_type）；CONFIG_SCHEMA_KEYS 增 sources.opml；
   _BATCH_COLLECTORS / _SOURCE_TYPE_BY_NAME 注册（archive_missing 删除检测
   天然生效）；config/knowatlas.example.toml 增配置段（enabled=false）；
   前端 SRC_LABEL 两处（index.html/thread.html）补 OPML 标签。
3. **canary 更新**（预期漂移）：source_types、config_keys 两个期望 hash；
   DDL/schemes/entry_fields/capabilities 不变。
4. **文档**：SOP 新增 §2.14（用法+口径+改名=换源警告）；§7 导出表 OPML 行
   更新为"导入回路已实现"；TODO Phase 5 挂账句改为已实现（探针 ✅）。

**验证**：pytest 268 项全绿（264→268：解析/跳过计数/错误指路/往返回吃
4 项新测试，roundtrip 用例 kexport 产物回吃对账 canonical 集合与
native_path 层级）；真实库冒烟——kexport --format opml 导出 151 书签叶
（15 分类）→ 临时启用 opml 源 dry-run 回吃 **151 条精确对账**、
duplicate_urls=2（多父展平预期）、0 非法 URL；既有三源 dry-run 零回归；
用户 config 改动已还原（hash 比对一致）并清理临时文件。

## 0.2.0 第五十一批：回归测试集 v0 机制（Phase 0.5 最后一项）

**交付**（TODO 挂账项"回归测试集 v0"的机制层全量；案例积累为日常渐进）：

1. **迁移 004_regress.sql**：regress_cases 表（entry_id PK CASCADE /
   expected_path 存路径不存 id——分类重建 id 漂移路径不漂 / source=
   manual|log_seed）。canary ddl hash 更新（567685343650→979471412904），
   迁移版本断言 3→4（test_threads 三处）。
2. **数据层**：add_regress_case（INSERT OR REPLACE=改主意覆盖）/
   list_regress_cases（join 条目投影供重跑）/ count_regress_cases /
   list_task_log_actions（按 task_name+action 全量扫描——回填场景，
   与 get_task_log 的最近 N 条快照语义区分；pipeline 不摸 _conn 纪律）。
3. **runner** pipeline/regress.py：
   - run_regress：全量案例重跑 classify_coarse——**ctx.llm 恒 None 强制
     跳 L3**（用户 config 可能启用 LLM，回归重跑绝不烧 token；Phase 4 接
     LLM 后在此显式开开关）；正文 content_store 优先 inline_content 兜底；
     exact/prefix/miss 三级判级（prefix=一方是另一方路径前缀，方向对差
     半级）；报告落 task_log（ktest/regress）。
   - seed_from_log：task_log 全部 recategorize 回填（同条目取最后一次
     new_path，空白容忍；dry_run 支持）。
4. **CLI**：ktest regress [--seed-from-log [--dry-run]] / ktest canary
   （转 pytest tests/test_canary.py 退出码透传）；_unimplemented 死代码
   随 ktest 落地删除（已无调用方）。
5. **确认入口**：POST /api/entries/{id}/confirm-category（当前主分类
   manual 优先；无挂接 400）；index.html 条目行 ✓ 按钮——注入在
   attachCatChips() 同循环（依赖挂接徽标数据，时序不能提前；onclick 在
   其尾部绑定，**不回调 bindEntryButtons 防死循环**——它尾部调
   attachCatChips）。开发期拦截：初版把注入放 bindEntryButtons 同步段，
   chip 未进 DOM 时序必挂；review 时发现改为同循环注入。

**验证**：pytest 274 全绿（268→274：CRUD 覆盖/CASCADE、三级判级、回填
最后值+dry_run、确认端点 manual 优先+无 token 403、CLI 空集 SKIP+报告
输出）；真实库冒烟——dry-run 统计 5 动作 4 条目 → 回填 → 报告 4 案例
exact 0/prefix 0/miss 4，**暴露两条规则误判**（GooglePythonStyleGuide
标题"Google"→华为云、Agent-Skill 文档"Agent"→文学创作）与一对疑似跨源
重复条目——规则修订与去重核查属数据决策，挂账待用户裁决后复跑。

**连带修复（第五十一批）**：
1. **writeJSON 假成功防御**（index.html）：非 2xx 且无 error 字段的响应
   （FastAPI 默认 404/500 是 {"detail":...}）规范化为 error 结构——修前
   confirm-category 404 会被 `!res.error` 误判成功显示"✓已确认"；修后
   alert 报错。防御意义超出本功能：所有 writeJSON 调用方受益。
2. **serve 重启踩坑记录**：trae 后台任务句柄失效后旧进程链（venv python
   父 → uv python 子）仍存活持有 8420（父进程被杀后子进程持继承句柄），
   新 serve 报 10048；重启 serve 必须按命令行匹配杀全链
   （Get-CimInstance Win32_Process 过滤 knowatlas serve），不能只信 job id。
3. **验证方式定稿**：浏览器 agent 新 profile 无会话，403 的 alert 会被
   自动吞掉造成"无报错"假象——写端点验证以 curl 会话流
   （GET /api/session 存 Cookie → 带 Cookie POST）+ 查库为准；本轮
   curl 全链路 200 + regress_cases 落库（log_seed 覆盖为 manual，
   改主意语义正确）+ task_log 出现 confirm_regress 记录。

## 0.2.0 第五十二批：人工校正 UI 收口（Phase 1 最后一项，TODO 全勾）

**交付**（Phase 1 人工校正 UI 的条目侧三能力；分类侧管理 M0.5 已有）：

1. **多父挂接**：recategorize 增 `keep_existing`（默认 false 保持替换
   语义不变）——true 只追加新挂接不摘旧（幂等防重复：先 detach 目标类
   再 attach）；move-dialog 增「保留原挂接」勾选。一条知识挂多个分支
   （DAG 设计初衷）从此是 UI 一等能力。
2. **批量改类**：POST /api/entries/batch-recategorize {entry_ids,
   target_path, keep_existing?}——逐条复用单条语义；每条独立 task_log
   （action=batch_recategorize，detail.batch_id 串联同一批，old_paths
   记前值）；not_found 跳过进 skipped、entry_ids 去重保序。
   **复现性纪律与单条一致**（TODO 探针）。
3. **前端**：
   - 多选模式：底部浮动条（多选开关/已选 N/移到…/取消）——勾「多选」
     body.multiselect → 条目行注入复选框（**跨视图累计**：检索/暂存/
     待清理/词云切面全通用，bindEntryButtons 尾部统一注入不碰 8 处模板）；
     视图刷新后按 selection Set 回填勾选态。
   - 拖拽：条目行 draggable（拖选择集或单条，dataTransfer 自定义类型
     text/knowatlas-ids）→ 树节点 drop（dragover 虚线提示）→ 弹窗预填
     目标路径。
   - 弹窗单/批统一：moveTargets 数组，>1 走 batch 端点；skipped 有值时
     alert 提示跳过数。
4. task_log 复现性补全：recategorize 的 old_paths 原来只记非 manual 挂接
   （替换语义下旧 manual 路径丢失）——改为记全部旧挂接，替换/追加两种
   模式均可完整复现。

**验证**：pytest 279 全绿（274→279：test_corrections.py 5 项——keep
追加语义/默认替换/批量 task_log 复现性+去重+幽灵跳过/批量多父/400+403
校验）；浏览器实测多选全流程 9 步通过（浮动条、复选框注入、计数、批量
弹窗、提交后条目出现在目标分类、模式退出清空）；拖拽链路代码简单
（标准 HTML5 DnD）留人工日常检验；serve 已重启至本批代码（PID 18228）。

**Phase 1 至此全部收口**（书签/文件夹/脑图三源 + 树 UI + 校正 UI 全勾）。

## 0.2.0 第五十三批：KNOWATLAS_HOME 数据根策略 + 一次性数据迁移（5a）

**背景**：db_path/backup_dir 相对路径按 cwd 解析——仓库内使用一直正常，
但装 wheel 后 cwd 不定数据位置就悬空；且 688MB 数据躺在仓库目录里，代码
与数据耦合。用户裁决（2026-10-21）：数据根设用户目录，仓库与数据彻底
分离。

1. **机制**（config.py）：`Config.home` = KNOWATLAS_HOME 环境变量
   （未设 None = 现状）；`_resolve()` 统一解析——绝对路径永远原样（换机
   显式指定优先），相对路径 home 已设挂 home、未设挂 cwd。默认值不变
   （data/knowledge.db、data/backups），**未设变量的行为与历史完全一致**。
2. **测试隔离**：conftest 显式 pop KNOWATLAS_HOME——测试自管 tmp_path
   绝对路径本不受影响，防未来相对路径用例落到真实用户目录。
3. **一次性迁移（本机）**：停 serve → `data\` 整体搬家到
   `C:\Users\yianyao\.knowatlas\data\`（db+wal+shm+backups 三件套同拷，
   SQLite 一致）→ `setx KNOWATLAS_HOME`（用户级永久）→ 重启 serve。
   仓库内 data/ 移除。
4. **文档**：SOP §1.3 数据根纪律 + §9 迁移流程第 4/7 步（新机设变量、
   三件套拷贝口径）。

**验证**：pytest 283 全绿（279→283：test_home.py 4 项——未设保持现状/
挂 home/绝对路径原样/空白值）；serve 打开新家真实库 200（6 大类、
wal/shm 活跃即真实读写）；**运维坑记录**：agent sandbox 只许写工作区+
Temp，serve 读写用户目录需非沙箱进程（dangerouslyDisableSandbox）——
用户终端跑 serve 不受影响。

## 0.2.0 第五十四批：Phase 4 侦察收口（补勾 ×2 + L3 few-shot 来自回归集）

**侦察结论**：Phase 4 未勾项里两条早已在产线（规则分类器=L1/L2、FTS5+jieba=
001_init 建表+词云），quote_strip 第三十九批已实现，L3 兜底 0.2.0 提前接入
——真缺失只有：few-shot 注入（本批）、delta_summarize/thread_digest（下一批）、
embedding+聚类+混合检索+语义边（再下一批）。

1. **补勾**（TODO）：规则分类器、FTS5 全文检索+jieba 两条转 [x]（注明实现
   出处与「两字词 LIKE 兜底已在 search_fts 落地、测试钉住」事实核查——初版
   补勾文案误写「trigram 已覆盖两字查询」，trigram 3 字符滑窗对两字查询零
   命中，已纠正）。
2. **L3 few-shot**（classify_deep v1.1.0）：`_few_shots(datalayer)` 从
   regress_cases 取最近 12 条人工确认样例（_case_line 与 _entry_line 同口径
   拼行），注入 prompt【人工校正示例】段；system prompt 增第 5 条（归类口径
   向示例对齐）。kadd/sync×2 三处 TaskContext 透传 datalayer。任何异常
   （无 dl/无表/库异常）安全降级为无示例——few-shot 是增益不是依赖。
3. **canary**：capabilities bb91f4917209 → 074a5d9a6582（SPEC v1.0.0→1.1.0）。

**验证**：pytest 285 全绿（283→285：few-shot 注入断言 + 降级安全 ×2）；
回归重跑路径（run_regress ctx.llm 恒 None）不受影响——few-shot 只在 L3
实际执行时读取。

## 0.2.0 第五十五批：线程语义压缩（delta_summarize + thread_digest，§9.4 LLM 后置层）

**背景**：quote_strip（第三十九批，规则层）已剥出增量正文落
entries.inline_content，本批补齐其后的 LLM 压缩层——§9.4 语义任务三件套
的最后两件。可独立关闭：LLM 关闭/故障一律静默降级不写库，线程视图照常
显示原始正文（摘要是压缩表示，原始层永在）。

1. **迁移 005_thread_digest.sql**：threads 加 `digest TEXT` 列（thread_digest
   产物，组装后的纯文本，可空=未生成；可重复生成=重算覆盖）。canary ddl
   979471412904→35c2852837b5；迁移版本断言 4→5（test_threads 三处）。
2. **delta_summarize**（semantic/tasks/）：输入缺摘要条目的增量正文列表，
   输出 entry_id→1-3 句「本轮新增了什么」；产物落 entries.meta.delta_summary
   （merge_meta，无 DDL）。LLM 输出 JSON 数组（extract_json_array 容错），
   无法解析/故障降级空。delta 空的条目照常送审（prompt 规则 3 要求照实短写）。
3. **thread_digest**（semantic/tasks/）：thread 层一次调用，读全量轮次
   重新组织成「问题→关键进展→当前结论/待办」，**不拼接各轮摘要**（与
   delta_summarize 互不依赖）；三节组装成【节标记】行纯文本落 threads.digest，
   空节剔除；全部为空视为未产出拒写。
4. **数据层**：Thread dataclass 加 digest 字段；get_thread/list_threads 带出；
   set_thread_digest（空串拒写 ContractError，task_log action=digest）。
5. **Web**：POST /api/threads/{id}/digest（写守卫）——①delta_summarize 只跑
   缺 meta.delta_summary 的条目（省 token，二次调用零 delta 开销）；②
   thread_digest 全量轮次；sender/sent_at 取 meta.from/meta.date（邮件条目）；
   无 inline_content 的非 mail 条目回退 content_store 截断。GET /api/threads/
   {id} 返回 digest + 每条 item.delta_summary。
6. **前端 thread.html**：工具栏「📝 LLM 摘要」按钮（生成中禁用防重复提交）；
   线程级摘要虚线框展示（可重新生成覆盖）；每条目下「💬 本轮新增」小字。
7. **注册**：builtins 登记 delta_summarize/thread_digest v1.0.0；capabilities
   074a5d9a6582→13b73497bbc5。

**复检探针**（实现后逐条命中）

- 探针①：关闭 LLM 后 quote_strip 产物（inline_content）仍工作、线程视图
  照常（digest=None 不渲染摘要框）——test_digest_endpoint_no_llm_writes_nothing
- 探针②：thread_digest 关闭不影响检索与线程视图（不写库不改条目）
- LLM 正常：meta.delta_summary 与 threads.digest 双落库、GET 回读一致；
  二次调用 delta 层零调用（缺摘要条目为空）
- LLM 故障：两层均不写库、返回 error、原始正文视图不受影响
- canary 新值落常量；pytest 全绿；变更文件 UTF-8 无 BOM + LF

## 0.2.0 第五十六批：M4 本地 embedding（向量索引 + 混合检索 + 语义边 + 聚类报告）

**背景**：TODO Phase 4 最后一块——本地 embedding（bge-m3 类中文模型，optional
依赖）+ 聚类 + 混合检索（结果可解释排序理由）+ 关系图语义边（db.py:844 与
topic_recall 语义通道两处挂账收口）。降级纪律与 LLM 同构：[embedding] 未启用/
依赖缺失 → 全部功能静默退回现状（fts 检索、无 sim 通道），主链路零影响。

1. **semantic/embed.py**：LocalEmbedder（sentence-transformers 惰性导入，
   首次 encode 才载模型；bge-m3 默认 HF 名，model_path 可指本地）+ from_config
   （enabled=false / provider!=local / 导入失败 → None）+ 纯标准库向量数学
   （float32 BLOB 往返、L2 归一化、余弦、top_similar——不引 numpy 硬依赖，
   两千条 ×1024 维毫秒~百毫秒级）。
2. **迁移 006_vectors.sql**：entry_vectors（entry_id PK / FK CASCADE，dim 防换型
   误算，vector float32 BLOB 归一化，model 记来源；可随时 --embed-force 重建）。
   canary ddl 35c2852837b5→8fe61eb2057d；user_version 5→6（test_threads 断言同步）。
3. **数据层**：put_vectors（upsert）/ get_vector / all_vectors / count_vectors /
   delete_vectors；db.radiate 条目焦点新增 **sim 通道**（阈值 0.5，异维残留跳过，
   _entry_row 已滤 archived/不可消费；节点 reason=sim:<余弦>，与 same_host 同
   条目时边 reason 拼接两段）。
4. **pipeline/embed_index.py**：
   - embed_entries：增量索引（inline_content 优先、content_store 兜底，截断
     4000 字；批 32 分批编码；archived 跳过、无正文计数不写）；
   - hybrid_search：FTS top30 + 向量余弦 top30 → **RRF 融合**（常数 60），
     每条带 reasons（fts / sim:<余弦>）——错字 query 纯语义命中可用（可解释探针）；
   - cluster_report：暂存区条目贪心聚类（阈值 0.72，簇心增量均值）+ LLM 为簇
     命名（§6.2 步骤 3「人工确认后生效」——**只出报告不建类**，确认后用既有
     改类 UI 挂接）；LLM 不可用退化簇号命名。
5. **CLI**：`ksync --embed` / `--embed-force` / `--cluster-report`（SKIP 退出码 3
   ——specSkill 语义：SKIP 计退出码不伪装通过）；未启用时打印 SKIP 提示。
6. **Web**：GET /api/search?mode=hybrid 接通（无 embedder → 降级 fts + note，
   探针钉住；有 embedder → hybrid hits 带 reasons/snippet/score）；
   topic_recall 第五路 **sim 通道**（仅主题词模式，query 向量近邻 top20 阈值
   0.45；c:/e: 焦点模式不叠加语义噪声）。
7. **注册与配置**：无新 SemanticTask（embed 是 pipeline 级能力，capabilities
   canary 不变）；embedding.* 配置键集早已在 canary（Phase 0 冻结）。

**复检探针**（实现后逐条命中）

- 探针①：embedding 未启用时 fts 检索与全部现有视图不受影响（端点降级 note 测试）
- 探针②：错字 query（fts 零命中）纯语义命中返回且 reason=sim 可解释
- 双命中条目 RRF 排名高于单命中；archive 条目不建向量；换型异维向量跳过不报错
- 聚类报告不建类（条目仍全部未分类）；LLM 命名 / 簇号退化两路
- canary 新值落常量；pytest 315 全绿（298→315）；变更文件 UTF-8 无 BOM + LF
- **bge-m3 真机冒烟未做**（模型 ~2.3GB 下载受网络影响，挂账待环境就绪单测）

## 0.2.0 第五十七批：零凭证在线源（AI 会话 + 数据文件，Phase 3 前两源）

**背景**：TODO Phase 3 五源中两源零凭证可先行（用户裁决）：AI 会话适配器
（session-harvester exports 产物映射）+ 数据文件适配器（SQLite/PostgreSQL
自省采样）。凭证类三源（B站/IMA/腾讯文档）待用户提供 cookie/token 后跟进。

1. **adapters/session.py**：读 harvester exporter 产物（`<category>/<YYYY-MM>/
   *.json`，SessionRecord 平铺结构；manifest 与坏文件跳过计数不中断）。映射：
   source_key=session_id、locator=session://<urlencode>、native_path=分类/月份
   （先验信号）、meta 带 harvester_source/origin/workspace/lossy/models/
   export_file/turns。inline_content=turns 摘要（前 12 个对话轮 role:首行）；
   全量对话正文（剔除 note/[context] 系统注入轮）经 stats["_full_bodies"] 落
   content_store（与 mail 源同约定，fetcher=harvester_export）。
2. **pipeline/session_threads.py**：全部轮次（含 note）落 conv_messages
   （msg_key=session_id#序号；in_reply_to 如实 NULL——产物平铺无引用头）+
   每会话一条 threads(thread_type='source')（🤖 标题，add_thread_item 去重
   幂等）。thread_items 是条目级粒度，轮次顺序由 msg_key 序号 + sent_at 承载；
   thread_digest 端点对会话线程直接可用（读条目全量正文 → 会话级摘要）。
3. **adapters/dbfile.py**：SQLite（stdlib，mode=ro 只读，缺文件 fail loud——
   dbmeta「绝不静默建空库」教训）+ PostgreSQL（psycopg optional，缺依赖/
   连接失败报错含安装与配置指引）。每张用户表一条目：source_key=文件名::表名
  （文件名作相对标识避免绝对路径入库）、locator=db://<标识>?table=<表名>、
   inline=行数+列清单+前 5 行采样（JSON 行，bytes/超长值截断）；视图与系统表
   排除（sqlite_%/pg_%/information_schema）。
4. **sync.py**：_BATCH_COLLECTORS 注册 sessions/dbs；session 附加处理与 mail
   同构（content_store + rebuild_session_threads）；**新增 _SECTION_BY_NAME**
   ——批量源名（复数 sessions/dbs）与 config 契约节名（单数 sources.session/
   sources.db，Phase 0 冻结）的差异映射。
5. 测试 12 项（test_session_source 6 + test_db_source 6）：collect 映射/
   容错/note 轮剔除、sync 端到端（content_store/conv_messages 不复制原文/
   线程幂等二跑）、SQLite 表清单采样探针、psycopg 缺失与坏 DSN 报错指引。

**复检探针**（TODO Phase 3 前两源）

- AI 会话：harvester 产物目录 → 条目含 title/session_id/created_at/turns
  摘要 ✅；conv_messages 轮次/父子关系与产物一致（含 note 全落、引用头如实
  空）、原文不复制进 conv_messages ✅
- 数据文件：SQLite 表清单与采样行正确进入条目 ✅；PostgreSQL 探针（docker
  起 PG 实例）**挂账**——代码路径与报错指引有测试，真机连接待环境
- pytest 327 全绿（315→327）；无 DDL/canary 变更（scheme 与 config 键
  Phase 0 已冻结在案）；变更文件 UTF-8 无 BOM + LF

## 0.2.0 第五十八批：serve 冻结根因修复 + 左栏折叠 + 词云噪音词过滤

**背景**：用户界面冒烟（2026-10-21 截图）反馈三问：①词云大量非知识性
词汇（XAMPP/localhost/php/your…）②左栏默认收起、知识窗口更大
③「聚合中…」永转圈、好慢。py-spy 栈转储定位到根因不是单点慢，而是两个
缺陷叠加：`_search_like` 的 UNION 查询在真实库（1809 条 / content_fts
约 130MB）上触发灾难计划（过期统计使 planner 估 entries 仅 61 行 →
entries 当外层 × content_fts 虚表全扫当内层，条目数 × 130MB 扫描量，
单查询 1h+ 0 CPU），且 `/api/recall` 是 async def 却在事件循环上同步跑
重查询——一个慢查询冻结整个 serve（/api/session 都 8s 无响应），前端
所有轮询全部挂死。诊断全程只读；修复后两字查询 36ms、recall 1.0s、
/api/session 14ms。

1. **db.py `_search_like` 重写**：UNION 拆成两条计划安全的查询 + Python
   去重（语义等价）：①entries 三列 LIKE（走 idx_entries_status，毫秒级）
   ②content_fts LIKE 子查询先出 content_hash → idx_entries_hash 回表
   （实测百毫秒级）。测试断言只钉命中不钉顺序，无需改。
2. **web/api.py 事件循环纪律**：`/api/recall`、POST /api/entries（内含
   抓网页网络 I/O）、threads suggest/digest（LLM 秒-分钟级）四处
   async def → sync def（FastAPI 自动入 anyio 线程池）。立纪律：事件
   循环上永远不跑重 DB / 网络 / LLM 调用。
3. **词云噪音词过滤**：`_CLOUD_NOISE` 从 12 词扩至 ~110 词（URL/HTML/
   文件类型样板 + 英文高频虚词 + 中文通用泛词；保留 内核/控制台/重启 等
   具体技术名词）。真实库验收：top30 全为知识性词元（md/skill/py/agent/
   技能/模板/LLM…），XAMPP/php/your 等零残留。
4. **index.html 左栏折叠**：默认收起（用户定调：知识窗口优先），偏好记
   localStorage「knowatlas-side」；h1 加「◀ 收起」按钮，收起后左上
   悬浮条（▶ 展开按钮 + 工作台搜索镜像框）；`[` 快捷键切换（输入框
   聚焦时不触发）；bookmarklet ?add= 落地自动展开（收录流程需要数据
   管理区可见）。browser 验收：默认收起/展开/再收起/重载记忆 4 项全过。
5. pytest 355 全绿；无 DDL/canary/config 变更；变更文件 UTF-8 无 BOM + LF。

**挂账**：全库词云首跑 ~8s（jieba 全量分词，tab 有「首次略慢」提示），
如感慢可后续加内容签名缓存；本次未做（避免过度工程）。

## 0.2.0 文档基线（第五十九批开工前，2026-10-21）：知识模型升级方案定稿 v2 + Phase 7 立项

纯文档批（不占批次编号，59 号留给布局三层代码批；无代码/DDL/契约变更）。
用户理念「知识应能聚能散能溯源能老化能勘误」经两轮讨论定稿，四点裁决全部落入方案：

1. **组头信号化**：知识集列表组头只用成员内容自身信号（共享词/分类/host/原文
   摘句），禁发明性标题容器——LLM 职责是「选出成员间真实共享的词」；
2. **切点+去重**：知识点按规范化 hash 去重，一点多溯源（溯源数=可信度信号、
   最早溯源=知识形成时间）；
3. **形态判定先行**：切点前 LLM 判 integral（方案/论证/单主题→整条即点）/
   split（参考集/多主题/讨论型→才切），理由落 meta；emmx 方案型脑图不再碎切；
4. **老化终点=删除**（用户裁决，规模论据：待接入几万邮件/几 GB 微信记录/
   ≥10 万条 AI 会话）：人裁废弃→即刻 rejected 全面不可见→30 天冷却→自动
   物理删除（task_log 留痕、content_store 引用计数回收）。

执行者意见一并采纳：点层独立 points/point_sources 表（切片进 entries 会污染
全部消费面）；勘误附注层不篡改原文；LLM 勘误必须附可核查依据；L1 只做确定性
错误防误报。emmx 存量裁决全删重灌（重灌前强制快照）。

文件变更：
- docs/design/知识索引工具-知识集与知识生命周期方案.md——定稿 v2：§5.1 用户
  裁决记录、§7.1 点层独立表+形态判定流水线、§7.2 组头信号化、§7.5 删除出口、
  §7.6 勘误附注层、§7.8 emmx 全删重灌流程、§9 批次 59-65 重排+并行待办合并、
  §10 裁决记录七项定案（初版由用户今日起草，本次按裁决修订定稿）
- docs/design/知识索引工具-TODO.md——新增 Phase 7（K7，批次 59-65 各带验收
  探针 + 并行待办清单）+ 里程碑 M7 行 + 配套文档指针
- docs/design/知识索引工具-SOP.md——§0 映射表加 §7.7 行；§2.12 时效守卫加
  删除出口指路（批次 64 后「只标不删」由删除出口承接）；新增 §7.7 知识模型
  升级操作预置（六条总纪律：组头信号化/形态判定/emmx 重灌先快照/删除出口
  口径/勘误不篡改/抽检固化——命令随实现批次进 SOP，不虚构）
- 字节扫描 UTF-8 无 BOM + LF；测试不涉及（纯文档）

## 0.2.0 第五十九批：布局三层信息架构（页签化主视图，Phase 7 批次 59）

**背景**：知识模型升级方案定稿 v2 §7.7/§9（用户七项裁决 + mockup 批注三条：
①③解释性文字不要 / 小书签默认收缩左缘 hover 展开 / 收录按钮说明悬停出）。
首页从「单页堆叠 + details 折叠管理区」改为「顶栏 + 六页签 + 左栏」三层信息架构。

1. **index.html 重写（957→约 900 行）**：
   - 顶栏：品牌 + 全局搜索（任何页签下可检索）+「＋ 收录」+ 左栏折叠键 + ⚙
     （显示空分类开关移入）；
   - 页签行六视图：检索（默认）/关系图/串联/词云/时间线/管理，各占全屏；
     graph/thread 以 iframe 内嵌、懒加载、深链保留（/graph.html、/thread.html
     与 ?node=/?id= 参数透传）；词云/时间线页内渲染，范围随左树焦点；
   - 管理页集中六入口（二级页签）：📥 暂存区/🔬 待清理/☠️ 失效链接/
     ⏳ 时效候选/🗑️ 已舍弃/🛠 数据管理（源配置状态 + 条目统计 + 最近任务 +
     收录入口）；日常消费页不再有管理控件（mockup 裁决）；
   - 收录对话框上移顶栏「＋ 收录」，title 悬停出说明（同 kadd 链路不变）；
   - bookmarklet 改左缘小书签坞：默认收缩竖条、hover 展开显示用途、拖拽中
     保持展开；?add= 落地自动打开收录框并提交（第 49 批语义不变）；
   - 58 批左栏折叠纪律保留（默认收起/[/localStorage），58 批的悬浮镜像搜索条
     删除（搜索已常驻顶栏）；多选校正/复制 ID/确认归类等 51-53 批能力全保留。
2. **web/api.py 新增 GET /api/sources**（只读）：12 个知识源配置状态布尔
   （键集与 config 白名单同源），不回传路径/凭证——数据管理页渲染用。
3. **测试**：新增 test_sources_status_readonly（布尔状态/无路径泄漏）；
   静态探针更新两处（test_web_api 页签化探针、test_cloud/test_timeline
   顶层页签入口），行为探针（renderCloudTab/renderTimelineTab 内部）不动。
   pytest 356 项全绿（1 skip）；无 DDL/canary/config 变更。
4. browser 验收：六页签/默认检索/懒加载/管理页六子页签/暂存区渲染/数据管理
   源徽标/词云 60 词元/时间线 canvas+陈旧分支/收录对话框开关/书签坞收缩与
   hover CSS/左栏默认收起（清偏好后验证）与 [ 切换——全部通过；窄视口页签
   文字折行补 white-space:nowrap + overflow-x 兜底。改动文件 UTF-8 无 BOM + LF。

**边界**：知识集列表（方案 §7.2，组头信号化）属批次 60+，本批只做布局容器；
graph/thread 页内部不动。

## 0.2.0 第六十批：知识集分组检索（组头信号化，Phase 7 批次 60）

**背景**：知识索引工具方案 §7.2a/§7.3（用户裁决第 1 条：按知识集分组），
TODO Phase 7「知识集聚合」。检索命中多时一次性平铺难扫读——升级「聚合结果」
为**分层查询**：命中 ≤5 条直接给点；命中多先给「知识集」分组概览，组内即下钻。

1. **组头信号化，禁发明性命名**（方案 §7.2a 核心裁决）：组头只由成员内容
   自身信号构成——成员共享词（jieba 抽词后**逐词验证在每个成员文本中子串
   出现**才上榜，无 LLM 参与，组头词可在组内任一条目验证）、共享分类路径
   （组内每条都挂接的最短公共路径）、共享站点 host、代表条目摘句（距簇心
   最近成员）。不造「相似主题」这类不可验证标题，不造「未分类」分组。
2. **聚合策略自动选择**（纯查询期计算，不写任何表，零数据风险）：
   `group_hits()`（pipeline/embed_index.py）≥2 条命中带向量 → 语义贪心聚类
   （56 批 `_greedy_clusters` 抽共用，阈值 0.72 同 `--cluster-report`）；
   无向量（bge-m3 未装机现状）→ 「主分类+同 host」结构聚合（host 为合取：
   同分类不同 host 不并组）。不成组条目 `singles` 平铺，前端降级渲染。
3. **端点**：`GET /api/sets/group?ids=`（只读，≤200 条去重），返回
   `{mode: semantic|structural|none, threshold, groups[{size,signals[
   {kind: word|category|host,value}],excerpt,excerpt_title,entries[]}],
   singles[]}`；同步 def（批量向量/挂接查询走线程池，不占事件循环）。
4. **前端 index.html**：检索同时拉 hybrid 混合检索——sim 通道并入合并结果
   （`语义相关 <余弦>` 徽标，向量未启用时该路静默降级无痕迹）；命中多时
   请求 /api/sets/group 渲染集分组列表（组头信号徽标分色 + 摘句 + 未成组
   兜底组），聚合失败回落平铺；全部交互（放射/分类定位/下钻）对组内条目
   照常生效。
5. **词云噪音表下沉共用**：58 批定稿的噪音停用词 + 准入规则移入
   `semantic/keywords.py`（word_ok/shared_words），web/api.py 词云改引用，
   行为逐字不变；知识集组头共享词同规则准入。
6. **测试**：test_embed 新增 4 项——语义路径（聚类 + 共享词可验证探针）、
   结构路径（主分类+host 合取/不合取不成组）、无共性全平铺、端点形状与
   空 ids。pytest 收集 331（HEAD 基线 327 + 新增 4）全绿（1 skip，EXIT=0）；
   历史日志「356 项」口径经查为汇总行被吞环境下的失真记录（HEAD 实测
   327），无测试丢失。SOP 增 §2.16。
   7. **边界**：不建 KnowledgeSet 表（方案明确查询期聚合，零数据风险）；
       LLM 零参与；真实库验证现状 0 向量 → serve 走结构聚合路径，语义路径
       待 bge-m3 装机 + `ksync --embed` 后自动生效。

## 0.2.0 第六十一批：关系图纯层级下钻模式（Phase 7 批次 63，方案 §7.4）

**背景**：用户理念 4.1-4.3——关系图粒度应从大类逐层下钻（技术开发 → 前端 →
javascript），现有 showSubtree 子孙分类+挂接条目混显+祖先链，一层看不全也下不去。

1. **后端**：`get_graph_subtree` / `GET /api/graph/subtree` 增 `hierarchy` 参数——
   只出下一级子分类（child 边 + value=子树可消费数定气泡，空类剪枝口径与
   经典视图一致），不出条目/域名/祖先链；叶子层（无子类或子类全空）自动出
   本子树条目（不带祖先链，上位路径由面包屑负责）。
2. **前端 graph.html**：新增「层级模式」开关（默认开，localStorage
   `knowatlas.graphHier` 记忆，58 批折叠纪律同款）——开时点分类逐层下钻，
   关时回到经典混显视图；非叶子层给「📋 显示条目」按钮显式展开本子树条目
   （切经典视图，面包屑顶改「条目:X」）；开关切换就地重放当前视图。
3. **顺手修（批次 60 发现）**：`cloud_data` 两个早退分支键名 `children` →
   `categories`（/api/cloud 正常路径读 `data["categories"]`，空库时词云 500）。
4. **测试**：test_datalayer 增 3 项（只出下一级/叶子出条目无祖先链/子类全剪
   落叶子）、test_web_api 增 2 断言（端点 hierarchy=true/1、叶子层条目）、
   test_cloud 增 1 项（空库早退键名契约）；pytest 331 → 335 全绿。
   SOP 增 §2.17。零 DDL/canary/config 变更；api.py+db.py 改动，serve 需重启。

## 0.2.0 命名统一：串联工作区 → 线索库（2026-10-22 用户定调，不占批次号）

**背景**：用户批注「串联工作区一言难尽」——页签「串联」/标题「串联工作区」/
核心对象「线索」三层混乱（内部文案早已统一用「线索」）。候选 线索库/专题/
阅读线/会话 经评审后用户拍板「按方案来」，采纳推荐项**线索库**（改动最小）。

- 用户可见文案：index.html 页签「串联」→「线索库」+ iframe title + 固化为线索
  tooltip；thread.html `<title>` 与 h1；graph.html 固化确认框；均为「线索」系
  统一，旧名不再出现在任何界面。
- SOP 现行描述同步：§2.5 标题改「线索库」并标注原名与定调日期，入口描述修正为
  页签入口（59 批起无侧栏）；§2.6/2.7/2.8/2.10/2.15 相关字句跟随。
- config/knowatlas.example.toml 邮件源注释同步。
- 历史性引用不改：CHANGELOG 历史批次记录、TODO/完整方案 §9.4、代码注释与迁移
  文件头（第三十二批历史名）；test_contract/test_threads docstring 同此。
- 无代码行为变更（纯文案/文档）；pytest 356 全绿；改动文件 UTF-8 无 BOM + LF。

## 0.2.0 空状态修复：检索页首页板 + 关系图总览计数（2026-10-22 用户抽检反馈，不占批次号）

**背景**：用户抽检夜间五批截图批注「啥也没有」——59/58/63 批三条纪律叠加出的空状态
缺陷：左栏默认收起后检索页主区只剩一行「点击左侧分类」提示（左栏根本看不见，自相
矛盾）；关系图层级模式总览只有光秃秃的大类气泡，初始信息量近零。数据完好，纯 UX。

- **检索页空状态首页板**（index.html）：启动后主区渲染「🧭 从这里开始——已归类
  N 条」+ 顶级大类按钮（名称+子树条目数徽标，点击自动展开左栏并进入该类——58 批
  折叠纪律不回退，只是给入口）+ 检索/展开引导；/api/tree 一次请求两用（loadTree
  改为返回 data）；只在启动渲染一次，任何检索/分类交互 renderEntries 覆盖后不复活。
- **关系图总览气泡计数**（graph.html）：大类气泡标签变「名称 · 子树条目数」（如
  「技术开发 · 787」）；经 `_ovText` 标记透传——render 逐字段重建节点，直接设
  per-node label 会被丢弃（首轮实现实测 FAIL 的根因）；formatter 对无标记节点回退
  原名，子树/放射视图零影响。
- browser 验收：首页板渲染 1732 条/四按钮、点击自动展开左栏进类、重载复活、总览
  四气泡计数全过；下钻无后缀由代码保证（无标记必回退）。pytest 356 全绿；改动
  文件 UTF-8 无 BOM + LF；纯静态改动刷新即生效，serve 无需重启。
## 0.2.0 第六十二批：知识点抽取流水线（Phase 7 批次 61a，方案 §7.1）

**背景**：方案 §7.1 点层独立表 + §9 批次 61 的**工程子集**（61a）：迁移 007 +
形态判定/切点/规范化 hash 去重/一点多溯源流水线 + ≤10 条小样本试跑验证链路。
**不做**全量判定（硬闸门：无人值守 LLM 预算 ≤¥1；全量须用户先裁决模型档位）。

1. **迁移 007_points.sql**：`points`（id/content_hash UNIQUE 去重键/text/summary/
   source_type/judge integral|split/created_at/meta 存判定理由 judge_reason）+
   `point_sources`（point_id+entry_id 复合 PK/char_offset/anchor/created_at，双 FK
   ON DELETE CASCADE——条目物理删除时指针级联消失、点本体保留）。points 不进
   entries_fts/content_fts 触发器体系（方案 §7.1），点检索独立演进。canary 同步升版：
   ddl 8fe61eb2057d→57f5e928913e、capabilities 13b73497bbc5→a6856a36fd52（point_extract@1.0.0 注册）。
2. **point_extract 任务**（semantic/tasks/point_extract.py）：形态判定与切点合并
   **单次 LLM 调用**（两步一请求省一半费用；判定理由必落 meta.judge_reason 供抽检——
   SOP §7.7 总纪律第 2 条）。integral→归一单点（结构化压缩正文），split→2-8 个
   自包含点（硬信息保留）；输出非法/为空降级带 error，绝不臆造。llm.py 增
   extract_json_object（对象版容错提取，容忍 markdown 围栏）。
3. **kpoints 流水线**（pipeline/points.py + CLI 子命令）：候选=active+有正文
   （inline_content 优先、content_store 兜底，>6000 字截断控成本）+非待清理+
   未抽过（point_sources 游标幂等，重跑零重复）；点正文规范化=去零宽/压空白/
   casefold（标点不归一——宁漏勿误，去重键错会错误合并不同观点）；content_hash
   命中即 put_point 合并溯源（一点多溯源，溯源数=可信度信号）；LLM 未启用 SKIP
   （exit 3）、单条失败记 error 不阻塞。数据层增 put_point/count_entries/count_points/
   list_points（meta 已解析）/point_sources_of/point_source_entry_ids。
4. **小样本试跑（真实库）**：dry-run 10 条（4 integral/6 split→37 点零错误）→
   真实写入三批共 25 条次处理、22 条目去重后 101 点 101 溯源全落库；判定理由可抽检
   （如「该条目是 phpredis README 参考文档，包含项目定位、安装配…」）；integral
   整条即点不碎切、split 点自包含带摘句锚点。LLM 费用 ~¥0.2（≤¥1 闸门内）。
   **运维留痕**：22≠25 因试跑期间一次后台重跑与前台 --limit 5 并发，3 条目被
   双重判定（LLM 非确定性输出各自成点，轻微冗余）——工具层使用事故非流水线缺陷
   （无人值守队列本就串行）；点层可重建，全量前统一重抽即可。试跑数据不清理
   （硬闸门：不物理删除）。
5. **测试**：tests/test_points.py 15 项（规范化 hash 空白/大小写/零宽不敏感+标点
   不归一、迁移 007 两表、一点多溯源合并+重放幂等、integral/split/非法输出/故障
   降级、流水线幂等重跑零调用、LLM 故障记录不阻塞、dry-run 不写库不推游标、
   长文截断走 content_store）；test_threads 迁移断言 6→7（新表纳入）；
   test_contract 能力集增 point_extract。pytest 349 项全绿（334+15：348 passed
   +1 skip，EXIT=0）。SOP 增 §2.18。db.py/cli.py 改动，serve 需重启。

## 0.2.0 第六十三批：老化三级·代码部分（Phase 7 批次 64a，方案 §7.5）

**背景**：方案 §7.5 老化三级补全 + §9 批次 64 的**工程子集**（64a）：L1 规则
（41 批 freshness guard）已有，本批落 **L2 LLM 复核代码 + L3 人裁删除出口代码**。
**不做**全量 suspect 判定（现库 ~87 条，硬闸门：无人值守 LLM 预算 ≤¥1、全量须
用户先裁决模型档位）；删除出口**落库不批量执行**（真实库零删除）；验证全用
人造 fixture（临时库）+ LLM 替身，零真实 LLM 费用。

1. **aging_judge 任务**（semantic/tasks/aging_judge.py，CapabilitySpec
   aging_judge@1.0.0）：对 suspect 逐条问「是否过时+理由+建议」（batch 20 单次
   调用，降级纪律同 delta_summarize）。结论三值：**stale**=确证过时升级
   freshness_flag=stale（退出消费面）/ **ok**=规则误报否决置 ok（不再标记）/
   **keep**=判不了（如 LLM 知识截止后的新版本）维持 suspect 自然下沉人裁
   （与三级设计自洽）。**防幻觉闸门**：stale 必须附可核查依据（技术事实/版本
   号/官方口径），给不出依据自动降级 keep——宁漏勿误（§7.6 勘误同款口径）。
   结论落 meta（aging_verdict/aging_reason/aging_suggest/aging_checked_at 可抽检）。
2. **kaging 流水线 + CLI**（pipeline/aging.py + cli.py 子命令）：候选=active+
   freshness_flag=suspect+未经 L2 复核（aging_checked_at 游标幂等）；--limit
   默认 10（试跑口径）、--dry-run、--sweep（手动触发删除出口清扫）；LLM 未启用
   SKIP（exit 3）、单批失败记 error 不阻塞。
3. **L3 删除出口**（db.py sweep_expired_rejections + REJECT_COOLING_DAYS=30）：
   人裁废弃（Web 舍弃按钮）→ 即刻 rejected 全面不可见（既有语义）→ **30 天
   冷却**（meta.rejected_at 起点；restore 清起点=反悔窗口）→ **冷却期满自动
   物理删除**（ksync 主流程每轮顺手执行 + kaging --sweep 手动）：FK 级联清
   entry_locators/entry_categories/point_sources（点本体保留，可重建溯源）、
   entries_fts 触发器同步；**content_store 引用计数回收**——多条目共享同一内容
   块只减计数，删到零才连 content_fts 清正文；**task_log 审计链留痕**（被删
   条目历史日志不动 + 追加 sweep_delete 记录）；无 rejected_at 的历史 rejected
   条目不删（非本机制裁决不自动清）；dry_run 只出报告。删出口只吃「人裁过」
   的 rejected，物理删除=用户裁决的执行而非自动决策。
4. **Web**：/api/entries/{id}/reject 落 rejected_at（时效候选区「🚫舍弃」即
   确认废弃入口）；restore 清 rejected_at；/api/rejected 增 rejected_at +
   cooling_days_left 倒计时；index.html 已舍弃区增冷却徽标（⏳ 冷却剩 N 天/
   冷却期满/不计冷却）与 30 天纪律说明，时效候选区说明补「舍弃=确认废弃，
   30 天冷却期内可在已舍弃找回」。
5. **测试**：tests/test_aging.py 16 项（三值结论+防幻觉降级+非法输出/未启用/
   故障降级、幂等重跑+limit+batch 单调用、dry-run 不写库、独占内容块回收+
   共享块只减计数、冷却未满/历史 rejected 不动、point_sources 级联点保留、
   task_log 审计留痕、ksync 顺手执行、reject 落冷却起点/restore 清起点、
   历史舍弃不计冷却）；test_contract 能力集增 aging_judge；canary capabilities
   升版 a6856a36fd52→37e239ecaeaf（零 DDL 变更）。pytest 349 → 365 全绿
   （364 passed + 1 skip，EXIT=0）。SOP 增 §2.19。api.py/db.py/cli.py/
   sync.py 改动，serve 需重启。

**复检探针**（TODO Phase 7 批次 64 口径，本批可验子集）：
- [x] 裁决废弃后条目从全部视图/检索/词云/导出消失（rejected 既有语义 +
      _consumable 口径回归通过；冷却徽标可见于管理页已舍弃区）；
- [x] 冷却期满后物理行删除、审计链留痕、共享内容块只减计数
      （test_sweep_expired_unique_content_recycled / test_sweep_shared_content_
      only_decrements / test_ksync_runs_sweep）；
- [ ] 全量 suspect LLM 判定与真实库删除——**等用户裁决**（模型档位 + 是否执行）。

## 0.2.0 第六十四批：勘误三级·代码部分（Phase 7 批次 65a，方案 §7.6）

**背景**：方案 §7.6 勘误三级 + §9 批次 65 的**工程子集**（65a）：L1 确定性
错误检查 + L2 带依据核查代码 + L3 勘误附注层（errata 并显，原文永不改写）。
**不做**全量 L2 核查（技术类 ~600 条，硬闸门：无人值守 LLM 预算 ≤¥1、全量
须用户先裁决模型档位）；L1 扫描零费用，真实库由用户下次 `ksync --errata-scan`
自然执行，本批不主动对真实库落标记；测试全用人造 fixture（临时库）+ LLM 替身，
零真实 LLM 费用。

1. **L1 确定性检查**（semantic/errata.py，纯函数零费用，**只做确定性错误**
   防误报——L1 误报会淹没裁决队列毁掉功能信誉）：完整 Python 围栏代码块
   ast.parse 语法验证 + **已移除 API 对照表**（标准库 PEP 594/632 移除批
   14 模块 + 著名第三方 removed API，每条附官方依据与替代方案）。
   **防误报纪律（宁漏勿误）**：节选特征（REPL `>>>`/首行缩进/`...` 占位/
   语言未标）一律不下结论；对照表只收 removed 级（deprecated 仍能跑不收）；
   正文提及不算（讲废弃的文章是正常内容）只查代码块；`np.float64` 词边界
   后向断言防合法名误报。死链（确定性错误第三类）已有 kcheck→link_status=dead
   独立通道，不重复承接。
2. **L2 errata_check 任务**（semantic/tasks/errata_check.py，CapabilitySpec
   errata_check@1.0.0）：事实一致性核查「该说法在当前版本是否仍然成立」
   （batch 20 单次调用，降级纪律同 aging_judge）。结论三值：**error**=确认
   错误进裁决队列（**必须附可核查依据**：官方文档 URL/版本号，给不出依据
   自动降级 suspect——防幻觉闸门 §7.6 定稿口径）/ **ok**=成立否决不再标 /
   **suspect**=疑似证据不足——**不到确认级不出裁决队列**（探针钉死）。
3. **kerrata 流水线 + CLI**（pipeline/errata.py + cli.py）：L1 `run_errata_scan`
   （freshness_scan 同构：无游标全量重扫，跳过 ok 否决/待清理/死链；命中打
   meta.errata_flag=error+errata_kind+errata_reason）挂 `ksync --errata-scan`
   与 `kerrata --scan`；L2 `run_errata_check`（候选=active+有正文+
   errata_checked_at 游标幂等，--limit 默认 10 试跑口径、--dry-run；LLM 未
   启用 SKIP exit 3、单批失败记 error 不阻塞）。
4. **L3 勘误附注层 + Web**（方案 §7.6 定稿：改正=附注并显，**原文永不改写**
   ——溯源链保住，同 55 批摘要哲学）：GET /api/errata 裁决队列（**只出
   确认级 error**，suspect 不出队；附 errata 附注数组并显返回）；
   POST /api/entries/{id}/errata 人裁改正=meta.errata 追加（多次附注累加）
   + 清 errata_flag 退出队列，inline_content/content_store 一字不动；
   POST .../errata/dismiss 误报否决置 ok（L1/L2 不再标记，freshness 同口径）；
   废弃复用 64 批 reject→30 天冷却→物理删除出口。全部动作 task_log 留痕。
   index.html 管理页第七子页签「🩹 勘误裁决」：确认错误列表 + 错误类型/
   依据徽标 + ✍️附勘误/↩误报保留/🚫舍弃三裁决按钮 + 已附勘误并显（📌 勘误
   附注块）。条目详情端点 meta 全量返回，附注数据源天然可用。
5. **测试**：tests/test_errata.py 26 项（代码块提取/节选四特征/语法确认/
   对照表命中附依据/正文提及不误报/词边界防误报/干净文本零结论、L1 扫描
   打标+ok·待清理·死链三跳过+dry-run+ksync 挂钩、L2 三值+防幻觉降级+
   非法输出/未启用/故障降级、游标幂等+limit+dry-run、裁决队列只出确认级、
   附注追加原文 diff 为零+二次附注累加+详情并显+task_log、误报否决+L1 重扫
   不翻转、写端点 403 守卫）；test_contract 能力集增 errata_check；test_web_api
   管理页静态探针六→七入口。pytest 365 → 391 全绿（390 passed + 1 skip，
   EXIT=0）。canary capabilities 升版 37e239ecaeaf→a5755f57d4f2（零 DDL 变更）。
   SOP 增 §2.20。api/db/cli/sync 改动，serve 已按三条件重启（/api/sources 与
   /api/errata 均 200）。

**复检探针**（TODO Phase 7 批次 65 口径，本批可验子集）：
- [x] 疑似错误不到确认级不出裁决队列
      （test_task_error_without_evidence_downgrades_to_suspect /
      test_queue_only_confirmed_not_suspect）；
- [x] 改正以附注并显、原文 diff 为零
      （test_errata_add_appends_note_original_untouched：inline_content 一字
      不动 + meta.errata 追加 + 详情端点并显返回）；
- [ ] L2 全量核查（~600 条技术类）——2026-10-22 用户裁决：开跑（模型=配置默认
      V4.1-Flash）；执行批次号 65b，见下批记录。

## [0.2.0] - 2026-10-22

### 第六十五批：emmx 全删重灌 + 形态判定适配器（Phase 7 批次 62，方案 §7.8）

**背景**：用户裁决（2026-10-22 四项裁决之三）「动手」——此前 emmx 脑图按节点
碎切入库（802 条），方案型脑图被拆得支离破碎（用户痛点：设计方案的图被切碎后
半点用处无）。执行前 kbackup --snap 快照（备注：当日快照首次执行遇库 I/O 故障
失败一次，库修复后重灌链路跑通，见下方「当日事故」）。

**数据事实**：源目录现存 .emmx 文件 9 个 / 226 节点（用户已自行清理过源）；
purge 旧 802 条 → 重灌 226 条 = 库与源一致。判定分布：integral 5 / split 4
（LLM=配置默认 V4.1-Flash，判定理由落 meta.judge_reason 可抽检，缓存键=文件
sha256）。抽检例：「考勤工时计算与验厂日报」图判 integral（整图围绕同一处理
方案，各分支相互依赖拆开不完整）；「泛型/类型参数化」问答式节点属 split 切分。

**适配器改造**（adapters/emmx.py，+269 行）：
1. 结构化解析成功且 [llm] 可用时，每文件先 LLM 形态判定（integral/split +
   一句话理由；判定依据=主题+一级分支大纲，`_JUDGE_OUTLINE_DEPTH=2`、输入
   截断 1800 字——判定不需要全文，省 token）；
2. integral（方案型）→ **整图一条目**：节点树确定性压缩为结构化大纲入正文
   （`_BODY_CHARS=20000` 上限超长截断留痕），locator=`emmx://<相对路径>#<map>`，
   source_key=文件相对路径（重同步幂等）；
3. split（讨论型）→ 节点照旧切条目（source_key=文件相对路径#页名/节点id），
   meta 附 judge 供区分；
4. 判定缓存 `KNOWATLAS_HOME/emmx_judge_cache.json`（键=文件字节 sha256）：
   文件未变不重判（二次 dry-run 实测 calls=0 / cache_hits=9，零重复费用）；
5. 降级纪律：LLM 不可用/解析失败 → 旧式节点切分 + stats.judge.errors 计数，
   不阻塞同步。

**配套**：datalayer/db.py `purge_source()`（按 source_type 物理删除全部条目，
FK 级联 + content_store 引用计数回收，调用方须先有快照）；pipeline/sync.py
judge 统计接入 sync stats；cli.py 参数透传。测试 +244 行（integral/split/
缓存/降级/契约）。

**当日事故（非本批代码问题）**：库文件 WAL/SHM 状态损坏 → serve 全部 API
disk I/O error（界面「聚合中…」挂死）+ 独立进程开库同炸 + 首次快照失败。
按 SOP §2.2 流程修复：停 serve → 三件备份至临时目录 → 删 -wal/-shm → 重启
→ 全链路恢复。根因未实锤（疑似 VACUUM INTO 中断留下坏 WAL 状态），挂账观察；
大库（656MB，conv_messages 全量正文）+ 多进程并发场景建议后续给 kbackup 加
VACUUM 失败重试与快照存在性校验。

**验证**：pytest 355 全绿（1 skip）；ksync --dry-run 真实库全源跑通（emmx
reachable / 9 files / judge cache 命中）；serve 重启后 /api/tree 254ms。
改动文件 UTF-8 无 BOM + LF。

### 第六十六批：知识点口径规则化 + emmx 宁整勿碎（Phase 7 批次 66，用户口径 2026-10-22）

**背景**：六十五批重灌后用户抽检发现方案型脑图仍被 LLM 误判 split 碎切
（「供应链流程」被切 23 条碎块，用户痛点：方案被切碎后半点用处无；LLM 误判
与人判工作量两难）。用户口径定调：「所有脑图，和文学创作相关的肯定都是知识点，
剩下的，全是方案」——知识点形态判定从 LLM 主导改为**确定性规则**，LLM 退役为
备用路径；并确认后续落地 ③两层形态共存+默认聚合呈现、④消费时一键合并/拆开
（批次 67 主体；另收目录信号粗规则：项目内文档≈方案、杂烩目录≈知识点，仅作
先验信号）。

**知识点抽取规则化**（pipeline/points.py + semantic/tasks/point_extract.py）：
1. 条目分类祖先链含「文学创作」→ forced split：LLM 只切点不判定
   （`_SPLIT_ONLY_PROMPT`，judge/reason 由代码固定落口径理由，省判定 token）；
2. 其余条目 → integral 整条即点，**零 LLM**（`_POINT_BODY_CAP=20000` 全文保真，
   超长才截断留痕）——错误成本不对称（误切=灾难、漏切=温和）下判定宁整勿碎；
3. LLM 未启用：integral 照产（原文永在），split 记 error 不产出。

**emmx 宁整勿碎**（adapters/emmx.py）：
1. LLM 未启用/判定失败/输出非法 → **整图保全 + meta.judge="degraded" 显式
   标记**，不再回落节点碎切；缓存不写失败结果，下次同步自动重判；
2. 判定 prompt 偏置反转：「拿不准 → split」→「拿不准 → integral」（原偏置
   正是误判碎切的 prompt 病根）；
3. 修 judge 统计 degraded 双计数 bug（分支 +1 后统一计数再 +1）。

**全量重抽（真实库）**：purge 旧 1100 points（只清点层，条目零影响；db.py
新增 `purge_points()` + kpoints `--purge-points`，task_log 留痕）→ 967 条
处理 = integral 963（零 LLM）+ split 4（文学创作，LLM 仅 4 次调用 ≈¥0.01，
比旧口径省 99%）→ 910 点落库，79 个重复观点自动合并，零错误。emmx 判定缓存
9 文件全改 integral 强判（规则覆盖 LLM，键=sha256，人工可改写）并重灌：
226 碎块 → 9 整图，「供应链流程」等方案完整性恢复（整图 + 正文命中验证）。

**测试**：test_points.py 按规则口径重写（18 项：规则 integral 零 LLM/祖先链
命中/no-llm 降级/一点多溯源/幂等/失败不推进游标/dry-run/purge/长文保真）；
test_emmx.py 适配 degraded 语义（15 项，purge 断言 8→4）。全量 pytest
404 通过（1 skip）。改动文件 UTF-8 无 BOM + LF。

### 第六十七批：两层形态聚合呈现 + 一键合并/拆开 + 目录信号三路（Phase 7 批次 67，2026-10-22）

**背景**：用户确认落 ③两层形态共存+默认聚合呈现（可逆架构）④一键合并/拆开
（消费时人纠）；目录信号粗规则（用户原话：「在某个项目内的文档，多半就是方案，
其他的多数是知识点——同一目录底下有若干内容相差颇大的文件……这个判断很粗疏」）。
另收截图 bug：检索条目分类徽标重复叠层（「几个意思？」）。

**A 徽标竞态修复**（web/static/index.html）：attachCatChips 加调用令牌（连续
渲染只认最新一轮，迟到响应丢弃）+ div 级幂等守卫（data-cats-done，DOM 重建
标记随节点消失天然允许重挂）——数据层已验证零重复（纯前端竞态）。

**D 目录信号三路**（pipeline/points.py）：形态判定从两路扩三路——
1. 文学创作祖先链 → forced split（不变）；
2. **杂烩目录（新）**：folder 源 + 目录末段含暗示词（其他/杂项/临时/归档/
   misc/archive…）或代码/文本类后缀 ≥3 种 → 走 LLM 全判定（宁整勿碎偏置，
   judge 可 integral 可 split——只取消零 LLM 豁免，不 forced split，误伤成本
   =一次调用）；**办公后缀不计数**（真实库教训：「Data/百卓/PECOS」79 条
   docx/xlsx/pdf 混杂是同一项目工作流，机械按后缀多样性会误伤）；
   .emmx 条目排除（走 emmx 自有判定缓存口径）；
3. 其余 integral 零 LLM（不变）。

**③默认聚合呈现**（db.py + api.py + index.html）：条目=方案级照常检索，点级
收进条目卡「◆ N 点 ▸」可展开区（聚合默认、下钻可选，检索零改动）。数据层
`points_of_entries()`（text 服务端截 500 字防检索页背 20K 整图大纲）+ 端点
`GET /api/entries/points?ids=`（声明在 /api/entries/{id} 之前防路径参数吞掉）；
前端令牌+幂等双守卫（同 A）。两层共存可逆：点数据本就独立成层（迁移 007），
呈现只加不改。

**④一键合并/拆开**（api.py + index.html）：emmx 形态人工裁决——判定缓存即
裁决入口。端点 `POST /api/sources/emmx/rejudge`（rel+form）：改
emmx_judge_cache 强判（fkey=sha256 人工可改写既定设计）→ run_sync 单源
purge 重灌（同步 def 纪律：重 I/O 不占事件循环）；前端条目卡 hover 注入
黄色按钮（#map→「⧉切分」/ #page/→「◫整图」/ #file 降级不给），点按即
裁决+重灌+刷新，点层下次 kpoints 自动重抽（溯源已随 purge 级联删除）。

**真实库落地**：杂烩条目重抽——24 条全处理零错误：**LLM 判 integral 14 /
split 10**，产 86 点（split 理由抽检：「电话联络表各部门可独立复用」「29 条
评审提示词清单」「仓库级操作手册按场景组织」——LLM 判定命中用户「杂烩目录
多数是知识点」直觉）；点层 910 → 978（split 点 4 → 93），清孤儿 18（杂烩
旧 integral 残留，无溯源指向）。rejudge 全流程未真库演练（防误重灌，按钮由
浏览器验收注入正确性）。

**测试**：test_points.py +4（暗示词路由 LLM/代码后缀路由/办公混杂不误伤/
emmx-manual 免疫——顺带修 .emmx folder 条目被目录规则二次判定的漏网）；
test_web_api.py +2（points 批量端点含截断与空态/rejudge 参数校验 400/404/403）。
全量 pytest 410 通过（1 skip）。浏览器验收三项 PASS（徽标唯一/点聚合展开
收起/rejudge 按钮注入与文案）+ 控制台零报错。改动文件 UTF-8 无 BOM + LF。

### 第六十八批：入库缓冲三层 + 批量流转 + 脑图路径面包屑（Phase 7 批次 68，2026-10-22）

**背景**：用户截图三问——①批量操作缺失（「舍弃十个点十次」）；②rejudge 语义
「工具知道哪些点合为整图么？人也不知道啊，因为啥都看不到」；③脑图碎片再现
（真库诊断：62 批 LLM 版判 split 入库 207 碎片，66 批改缓存强判后重灌**没带
purge**——9 整图是新增、旧碎片没删，验收只查正面没查反面，抽检漏洞再犯）。
用户定调入库闸门：「正常入库，但入库后操作数据前，人工判断删除……否则做好后
又得删一大堆」。另：知识梳理合成层（原 68）顺延 69——用户「还没有可以合成层
的知识，或不需要」。

**碎片修复（真库，先于代码）**：`ksync --purge-source emmx` 全清 230 条
（207 碎片+旧整图）重灌 9 整图（缓存全命中零 LLM 费用）；验收查双向
（map=9/page=0）；用户 15:33 舍弃的培训积分整图置回 rejected 保持意愿。

**①入库缓冲（pending 状态，三层过滤的事后层）**：models.STATUSES +pending；
sync 主循环按源配置 `new_entries="pending"` 把新建条目置 pending（默认 active
**零行为变化**——给未来高噪音源聊天记录/AI 会话/邮件立闸门，现有源已靠
exclude_globs/include_exts 治理）；pending 条目**不分类不抓正文不抽点**
（categorize targets/fetch_missing 过滤——垃圾不烧钱）；消费面全部按
status='active' 查询天然隔离。源级排除（事前配置 exclude）与目录放行（白名单）
已有机制不重复造。

**②批量流转**：`POST /api/entries/bulk-status`（ids≤500，action=
activate/reject——reject 带冷却起点，每条 task_log 留痕 bulk_*，missing 列出）；
bulk-bar 加「✅ 转正」「🗑 舍弃」（多选条复用第五十二批 selection 基础设施）——
待审/已舍弃/暂存区队列通用。管理页加「🆕 待审」页签（GET /api/pending）。

**③脑图路径面包屑**：/api/entries/linkage 扩展 mind_paths（emmx 条目
meta.mind_path）；前端条目行紫色「🗂 主题 › 路径」——同图上下文可见，
一键合并/拆开的决策依据（「啥都看不到」批注的正面回答）。

**测试**：test_folders.py +2（pending 缓冲全链：置位/分类跳过/二跑不重置/
转正；默认 active 零变化）；test_web_api.py +2（bulk-status 全路径含 403/
missing；linkage mind_paths 含空态）。全量 pytest 414 通过（1 skip）。
浏览器验收三项 PASS（待审页签空态/批量按钮常驻/面包屑「🗂 编码规则」）；
首轮 FAIL 为浏览器缓存假阴性（serve 端直查确认新代码）。改动文件 UTF-8 无
BOM + LF。

### 关系图去域名节点（第六十八批后用户截图反馈修正，2026-10-22）

**用户截图批注**：「域名也作为关联项，毫无意义」——子树/搜索/总览图里，≥2 条
同 host 条目会聚合出一个 `d:<域名>` 灰色枢纽节点，纯噪音。

**裁决**：域名不作为关联项出图。同域关系只在两个带解释的位置保留：
radiate 放射视图的 `same_host:<host>` 通道（条目↔条目，悬停见理由）与反查
面板的「同域名」列表项——那里域名是解释，不是节点。

**改动**：
- db.py：`get_graph_data`（v0 总览）/`get_graph_subtree`（经典+层级叶子层）/
  `search_graph` 三个构建器移除域名节点与 same_host 边；删 `_host_group_links`；
  条目节点不再携带仅用于分组的 host 字段
- graph.html：清理域名渲染死分支（尺寸 10/灰色 #999/恒显标签/统计行「域名 N」/
  点击恒走放射）
- 测试：test_datalayer 图断言去 d: 节点（3 处）+ `test_graph_search_no_domain_nodes`
  （原 groups_same_host 反转）；test_web_api `test_graph_data_shape` 反转
  （断言无域名节点/无 same_host 边）。radiate/reverse 域名焦点测试不变（API 能力保留）

**真库验证**：serve 重启后 `/api/graph` 416 节点 / 4592 边——domain 节点 0、
same_host 边 0；graph.html 部署面无 domain 渲染分支。全量 pytest 414 通过
（1 skip）。UTF-8 无 BOM + LF。

### 第七十批：条目级形态覆盖——非 emmx 文档的拆/合（Phase 7 批次 70，2026-10-22）

**背景**：用户问「脑图有个切分整合命令，其他类型文档是否也要有？」——emmx 的
⧉/◫ 是源级重灌（判定缓存按文件粒度，rejudge=改缓存→整源 purge→重灌），其他
文档形态判定发生在点抽取时（批次 66/67 规则），改单个文档只需条目级操作。
需求不对称：拆（integral→split）是真缺口（口径「剩下的全是方案」下，某份方案
文档想要它的知识点，无手段）；合（split→integral）需求弱但顺手补齐。
用户选项裁决：「落批次 70，拆+合都做」。

**机制**（meta.force_form 优先于目录/分类规则）：
- form="integral"（合）：强制整条即点，零 LLM，理由标注「用户强制覆盖」；
- form="split"（拆）：强制走 LLM 切点（forced_judge=split 切点-only prompt），
  拆一次几分钱；llm 未启用 → 覆盖已写但重抽记 error 不静默（下次跑批补）；
- form="auto"（回归）：merge_meta 删键（None=删键语义），回归目录/分类规则；
- 覆盖**永久生效**：全量重抽也尊重标记（用户修正不返工，可逆架构同思路）；
- emmx 条目拒绝此端点（400）——源级 rejudge 已有，两套不打架。

**改动**：
- db.py：`purge_entry_points`——单条目清 point_sources，孤儿点级联删（一点多
  溯源口径下共享点保留），游标 point_source_entry_ids 派生自溯源随清，task_log
  审计
- points.py：`_candidates` 加 only_ids（指定条目直取跳过游标——调用方已清溯源）；
  run_points_extract 加 entry_ids 参数与 force_form 判定（integral 强制在
  mixed/规则分支之前）；_integral_result 加 reason 覆盖参数；stats 加
  force_overrides 计数
- api.py：`POST /api/entries/{entry_id}/form`（guard→校验 form→404/400→写覆盖
  →purge_entry_points→run_points_extract(limit=1, entry_ids=[id]) 即时重抽
  →task_log 留痕→返回 points_created/errors/points）；同步 def（LLM 网络调用
  禁占事件循环，同 emmx_rejudge）
- index.html：attachFormBtns——非 emmx/http 条目 hover「⧉拆」「◫合」；已覆盖
  条目（entryHTML data-force）显示「↺回归」单按钮；bookmark（网页无本地正文）
  不给按钮

**测试** +5：test_points 4（integral 覆盖 split 规则零 LLM/split 覆盖 integral
规则走切点/entry_ids 跳游标重抽且幂等归并/purge_entry_points 共享留孤儿删游标清）+
test_web_api 1（form 全路径：合成功/拆无 LLM 记 error/auto 清覆盖/400/404/403/
emmx 拒绝）。全量 pytest 419 通过（1 skip）。方案文档 §9 批次表 +70 行、
§10 裁决记录 +10/11 条。UTF-8 无 BOM + LF。

### 术语统一与 rejected 口径排查（批次 70 后用户反馈，2026-10-22）

- **「时效候选」页签更名「老化候选」**（用户裁决「失效那个，还是改成老化吧」
  ——术语与批次表「老化三级」统一）：页签名/空态文案/badge title 三处 +
  注释。纯文案零逻辑。
- **rejected 口径排查结论**（真库）：当前 rejected=1408——294 条带
  meta.rejected_at（冷却起点在，批次 65a 引入字段后舍弃的）；1114 条无时间戳
  （=历史挂账「1116」的真身，早期 reject 动作先于字段存在）：folder 868
  （百卓工作文档批量舍弃）+ bookmark 245（失效/低质网页）+ manual 1。
  task_log reject 动作 1496 条与之吻合。**风险**：无冷却起点 → kaging 物理
  删除出口扫不到这批（永不自动删）。处置挂账等用户裁决（补 rejected_at 起
  冷却 / 保持人工）。

### 第七十一批：条目命名体系 + 合并 + 预览（Phase 7 批次 71，2026-10-22）

**背景**：用户截图批注——①书签标题是网页原标题（「以MVP思维，解析最小的进销存
产品 | 人人都是产品经理」），「能不能按知识的名字来命名」；②PECOS×3 同主题
重复「这种就该合并」；③点条目直接跳 file://（浏览器拦）或离开站内，「点开啥
也看不出来」。另用户四问裁决了批次顺序：分类浏览集分组/关系图密度→72，
bge-m3/PG 真机→73。

**①改名（display_name 覆盖层）**：`POST /api/entries/{id}/rename` 写
meta.display_name（1..120 字，空串=清除覆盖）；_row_to_entry 统一应用——
列表/检索/图全部消费面自动生效，full 重同步冲不回（覆盖层在 meta，upsert
只冲 entries.title）。前端 ✏️ 按钮 + prompt 输入。

**②合并**：db.merge_entries——被并条目 locator 挂主条目（entry_locators，
INSERT OR IGNORE）、点溯源 UPDATE OR IGNORE 转移（点不丢，共享点归并）、
分类挂接搬移（confidence/origin/task_run_id 原样带）、自身置 rejected
（rejected_at 冷却起点，30 天老化出口物理删）、merged_into/merged_from
双向锚（Python 侧读改写——SQL json_set 拼数组易 malformed，本批教训）。
`POST /api/entries/merge`（primary_id + merge_ids≤50）；前端多选 ≥2 条
「⇒合并」，第一条为主条目（confirm 明示主被并名单）。

**③预览面板**：`GET /api/entries/{id}/preview`（display_name/正文前 2000 字
content_store/分类/附加 locator 数/点数/merged_from）；前端点条目标题弹
dialog（不跳走），「打开原文 ↗」保留原 locator 新标签；Ctrl/Shift 点击
保留浏览器默认（新标签直达）。

**④AI 批量起名**：semantic/naming.py——正文 1500 字交 LLM 起 8-20 字知识化
短名（默认提示词前端可改，POST body.prompt 覆盖）；已有 display_name 跳过
（force 重起）；无正文降级剪「| 站点名」尾巴（正则，零费用）；LLM 失败单条
记录不中断。`POST /api/entries/auto-name`（ids≤50，同步 def）；前端多选
「✨AI 起名」+ 提示词 prompt 编辑 + 结果摘要（起名/跳过/降级/失败计数）。

**测试**：test_web_api +2（rename 全路径含空名清除/120 上限/404/403；merge
全路径含 locator 挂接验证/点溯源转移验证/400×3/403；preview 含正文与
extra_locators；auto-name 含跳过/降级剪尾/400/403）。全量 pytest 421 通过
（1 skip）。修复过程：ContractError 导入缺失/entry_categories 列名
（confidence/task_run_id 非 weight/run_id）/point_sources 无 content_hash
列（经 points JOIN）/put_content 走 FetchResult。孤儿点 627 清理（folder
purge 挂账，并入本批收尾）。UTF-8 无 BOM + LF（naming.py Write 落盘 CRLF
转 LF——Write 工具在 Windows 的默认行为，收尾扫描必查）。

### 第七十二批：分类浏览集分组 + 关系图层级密度（Phase 7 批次 72，2026-10-22）

**背景**：用户四问裁决（批次 71 后做 72）——①点左树分类右侧条目列表按知识集
聚合呈现；②关系图节点多的子树分层铺开/稀疏分支折叠，看图看清结构。纯查询/UI
批次，零 LLM 零数据风险。

**①分类浏览集分组**：showCategory 接入批次 60 GET /api/sets/group（复用
group_hits 语义贪心聚类/主分类+同host 结构聚合，分类视图接入而非新造）——
>5 条自动聚合渲染（组头信号徽标 + 组内条目卡保留预览/改名/改分类/舍弃全功能，
「未成组」归组尾），filter 下拉变化对过滤后条目重聚合（查询期零写库）；
「📐 按集分组 / 📄 平铺」双态切换，localStorage 记忆（knowatlas.catGrouped，
58 批折叠纪律同款）；聚合失败/不成组平铺兜底；视图令牌防迟到响应覆盖
（attachCatChips 同款教训）。

**②关系图层级密度**：
- 稀疏折叠（后端）：get_graph_subtree 增 compact 参数（API ?compact=1 透传）
  ——直挂 ≤2 条的子分类（非根）藏其条目与挂接边，分类节点带 folded=N 徽标
  （label「名 · N条」）；只藏边不藏类，点分类下钻信息零丢失；条目另挂稠密
  分类时边保留、仅孤立时节点隐；直挂数独立于 limit 全量 SQL 统计（截断样本
  计数会失真）；根分类直挂不折叠（当前层主体信息）。hierarchy 层级模式不受
  影响（本来不出条目）。
- 分层铺开（前端）：经典视图分类节点带 depth（root=0，多父 DAG 取最短链，
  不动点松弛；祖先 ctx=-1），前端节点 ≥25 时 layeredCoords 按 depth 分行、
  条目挂其最深挂接分类下一行（layout none），自上而下看清结构；放射/搜索/
  总览/层级模式无 depth 字段自动回退 force。
- 图页 header 增「🗜 稀疏折叠」开关（默认开，localStorage knowatlas.graphFold），
  切换就地重放当前视图；tip 提示折叠生效。

**测试**：test_graph_radial +8（depth 字段/多父取最短/折叠藏边与 folded 计数/
共享条目经稠密支保留/默认关闭回归/层级模式隔离/API 透传与默认）。全量
pytest 429 通过（1 skip）。真库冒烟：/api/graph/subtree compact=1 folded
生效、/api/sets/group 分类条目聚合正常。

