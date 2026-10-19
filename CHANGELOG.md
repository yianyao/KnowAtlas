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
