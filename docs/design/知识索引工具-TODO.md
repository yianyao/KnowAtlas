---
title: 个人知识统一索引与分类导航工具 · TODO
summary: Phase 0 契约冻结到 Phase 8 数据源全覆盖的分阶段任务清单（2026-10-19 第二次定稿 + 契约返工 + 2026-10-24 需求澄清后新增 Phase 8 与对账修复清单），每项含验收探针，每阶段设 Gate
date: 2026-10-19
updated: 2026-10-24
status: 定稿（Phase 8 的源接入顺序待用户拍板）
reader: 执行者（人与 agent）
---

# 个人知识统一索引与分类导航工具 · TODO

使用说明：

- 状态标记：`[ ]` 未开始 / `[~]` 进行中 / `[x]` 完成。
- 每项任务自带验收探针；探针不过，该项不算完成。
- 每个 Phase 设 Gate，Gate 不过不进入下一 Phase。
- 配套文档：docs/design/知识索引工具-设计方案.md（设计依据）、docs/design/知识索引工具-完整方案.md（工程契约，编码直接依据）、docs/design/知识索引工具-SOP.md（操作流程）、docs/design/知识索引工具-知识集与知识生命周期方案.md（知识组织模型升级规划，2026-10-21，待确认）。
- 变更记录：handoff/变更工单-2026-10-19-第二次定稿.md、handoff/变更工单-2026-10-19-B站收藏夹.md、handoff/变更工单-2026-10-19-契约返工.md、handoff/变更工单-2026-10-19-安全与API修正.md。
- **2026-10-24 修订（对账）**：① Phase 7 第 59–63 项按 CHANGELOG 回勾——台账冻结于第 58 批，勾选已失真；② 新增 Phase 8「数据源全覆盖 + 统一清洗层」与文末「对账修复清单」；③ 需求侧最高依据改为 `需求澄清与裁决-2026-10-24.md`（用户七点需求 + 三点裁决），与本文件冲突时以后者为准。

## Phase 0 — 契约冻结

> Gate：契约测试全绿；改动任一字段名/scheme 名，canary 测试报警。

- [x] 建 git 仓库 + `docs/design/` + CHANGELOG（K3）：handoff 六份文档作为首批内容提交进 `docs/design/`，以仓库版本为准；此后变更工单不再新增文件、一律追加 CHANGELOG（当前契约跨文件拼的问题是历史包袱，从本项目起终止）——2026-10-21 补勾（第 49 批核对）：仓库与 CHANGELOG 自首批提交起运转，后续变更全部以批次追加 CHANGELOG
      - 探针：git log 可见 `docs/design/` 首批提交；CHANGELOG 存在且已回填前两次定稿摘要 ✅
- [x] CI 工作流兜底（借鉴 specSkill：本地 pre-commit 只能拦住"记得装且没 --no-verify"的提交，CI 是不依赖记性的底线）：推 GitHub 触发 pytest + schema canary；判定分级 FAIL/WARN/SKIP/INFO 语义与 specSkill 一致（SKIP 计退出码，不伪装通过）——2026-10-21 补勾（第 49 批核对）：.github/workflows/ci.yml push/PR 触发 `pytest -q` 全量（含 schema canary），历次推送均绿；specSkill 式 FAIL/WARN/SKIP/INFO 显式分级未照搬（pytest 退出码即 FAIL 判据）；"故意提交破坏看 CI 红"演练未单独做过，canary 拦截能力由套件内 canary 测试同源保证
      - 探针：故意提交一处契约破坏，CI 红并指名 canary 项；本地 --no-verify 绕过 hook 后 CI 仍拦截（探针实验未做，如实挂账）
- [x] 统一条目字段定稿（id / source_type / title / locator / native_path / inline_content / content_hash / meta / created_at / exported_at / status），含字段约束表；source_type 枚举含 manual / wxchat / wxarticle；meta 约定 seed_entry_id（公众号文章回溯收藏种子条目）——2026-10-21 补勾（第 49 批核对）：entries dataclass + 必填校验落地（缺字段写入报错并含字段名），canary 覆盖 dataclass 契约
      - 探针：fixture 构造一条缺必填字段的条目，写入被拒并报出字段名 ✅
- [x] locator scheme 命名规范定稿（http/https/file/mail/ima/txdoc/emmx/db/session/wxfav/bili；手动链接直接复用 https，不新增 scheme）——2026-10-21 补勾（第 49 批核对）：scheme 注册表落地，未注册 scheme 明确报错不静默跳过，canary 覆盖 scheme 清单
      - 探针：未注册 scheme 的 locator 触发明确报错，而非静默跳过 ✅
- [x] 注册表接口签名定稿（Locator Handler / Semantic Task，含能力描述格式 name/input_contract/output_contract/version）——2026-10-21 补勾（第 49 批核对）：CapabilitySpec 定稿 + kinit 注册内置能力，canary 覆盖 version
- [x] SQLite DDL 定稿（entries（含 locator_canonical）/ entry_locators / categories（path 不落库，CTE 派生）/ category_parents / entry_categories / content_store / content_fts / task_log / runs / entries_fts）——2026-10-21 补勾（第 49 批核对）：DDL 定稿并随迁移机制演进（002_threads 起），canary 覆盖 DDL
      - 探针：一条条目挂两个分类成功；一个分类挂两个父分类成功（验证 DAG）✅
- [x] 时间戳纪律落地（ISO 8601；无法解析置 NULL 不臆造；epoch 秒/毫秒自动识别）——2026-10-21 补勾（第 49 批核对）：解析工具落地，测试背书
- [x] schema canary 测试（仿 session-harvester 做法：契约结构变化即时报警；覆盖 DDL / dataclass / scheme 清单 / CapabilitySpec version / source_type 白名单 / config schema 键集）——2026-10-21 补勾（第 49 批核对）：tests/test_canary.py 六类覆盖全在，历次契约变更均由 canary 报 hash 变化驱动同步

## Phase 0.5 — 首个垂直切片（M0.5，K2 返工新增）

> Gate：200 条真实链接经 kadd 跑通全链路（建条目 → 抓取 → 归类 → 检索 → 树 UI）；"10 大类"不用预设，先用真实数据检验。

- [x] 项目骨架：目录结构（设计方案 §9.3）、venv、依赖清单（core/optional 分组）、配置加载（env 覆盖）、README——2026-10-21 补勾（第 49 批核对）：src-layout + requirements 分组 + config env 覆盖 + README 全在
      - 探针：新机器按 README 从零跑通 `python -m knowatlas ksync --dry-run` ✅
- [x] 数据层读写接口（唯一入口，禁其他模块直连 SQLite）——2026-10-21 补勾（第 49 批核对）：datalayer/ 唯一入口，历批复审 grep 无外部直连 SQL
      - 探针：grep 代码库，除 datalayer/ 外无直接 SQL ✅
- [x] 手动链接入口 v0：CLI `kadd <url...>` + Web UI 输入框（bookmarklet 可选）——2026-10-21 补勾（第 49 批核对）：kadd CLI 与 Web UI 输入框均在；bookmarklet 同批补上（跳转 index.html?add= 复用手动收录链路，见 SOP §2.4）
      - 探针：粘贴一个 URL 后条目进"未分类"暂存区，task_log 有 manual 导入记录；重复粘贴同一 URL 不新建条目 ✅
- [x] http 内容获取器 · simple 后端（httpx + readability-lxml；GitHub 仓库页/release 特化分支）——2026-10-21 补勾（第 49 批核对）：fetchers/http_simple.py + 特化分支，抓取测试在库
      - 探针：fixture 文章页提取出正文，导航/页脚等噪音被剔除 ✅
- [x] FTS5 全文检索（entries_fts + content_fts 正文索引；trigram + 两字词 LIKE 兜底）——2026-10-21 补勾（第 49 批核对）：FTS5 + 兜底落地，检索链路（/api/search、工作台聚合）日常使用中
      - 探针：两字词（如"入库"）标题无命中、正文有命中时可检索到（会红的测试钉住）✅
- [x] 分类树 UI v0：点击下钻、面包屑、暂存区常驻——2026-10-19 完成（M0.5 提前）：点击分类右侧显示子树条目（含 source_type 筛选）、面包屑跳转、暂存区常驻按钮；另含分类节点管理（新建子类/重命名/移动/合并，写操作带 X-KnowAtlas-Token，全部写 task_log）
- [x] web 安全中间件：Host/Origin 校验 + 写操作 token（`X-KnowAtlas-Token`）+ content-type 白名单（H5）——2026-10-21 补勾（第 49 批核对）：middleware + check_write_access 落地，伪造 Host/无 token/非 JSON 正反例测试在库
      - 探针：伪造 Host 的请求 403；无 token 的 POST 403；非 JSON body 415；正常本机访问全绿 ✅
- [~] 回归测试集 v0：从 200 条真实链接人工确认 50-100 条（同时作为 LLM few-shot 底稿）——2026-10-21 机制完成（第五十一批）：regress_cases 表（迁移 004）+ 确认入口（条目行 ✓ 按钮 POST confirm-category，manual 优先）+ 历史改类回填（ktest regress --seed-from-log，recategorize 取最后一次 new_path）+ 报告 runner（pipeline/regress.py：只跑 L1/L2 零 LLM 费用，exact/prefix/miss 三级判级，报告落 task_log）+ CLI（ktest regress/canary）；真实库冒烟 4 案例回填跑通。**进行中**：案例积累（目标 50-100 条，日常浏览点 ✓ 累积）；首轮报告暴露规则误判（Google→华为云、Agent→文学创作）待修订 priors/rules 后复跑
      - 探针：跑完后回头核对 10 大类草案，该合并的合并、该拆的拆，结论落进 priors.py（待案例攒够后执行）

## Phase 1 — 最小可用闭环（M1）

> Gate：书签、文件夹、万兴脑图三源接入；分类树可下钻、可双向联动；人工校正可用且进 task_log。（前置：M0.5 已跑通，10 大类经真实数据修订）

- [x] 浏览器收藏夹适配器（Chrome/Edge 先行；Firefox places.sqlite、Safari plist 排后）——2026-10-19 提前完成（M1 提期），adapters/bookmark.py + ksync 落地，390 条真实书签入库，探针全过（CHANGELOG 0.2.0）
      - 探针：fixture 书签 JSON → 条目数、native_path 与收藏夹层级一致
- [x] 文件夹适配器（遍历 + 文档/PDF/其他分类标记）——2026-10-19 提前完成（M1 提期）：adapters/folder.py + ksync 落地，meta.file_kind 四类标记，file:// 补抓打通（--fetch-limit 对文件生效），探针全过（CHANGELOG 0.2.0）
      - 探针：嵌套目录路径正确进入 native_path ✅
- [x] 万兴脑图适配器（.emmx = ZIP + XML 解析节点树；page.bin 二进制情况下降级标题级并标记 degraded）——2026-10-19 真实格式定稿完成：解剖 9 个真实样本发现实际为 MindMaster 9.x Shape 结构（page/page.xml + Shape Type=MainIdea/MainTopic/SubTopic + 文本在 Text/TextBlock/Text 的 <tp> + 层级为 LevelData/Super 引用而非嵌套），**与最初假设的 content.xml topic 树完全不同**，解析器按真实格式重写（CHANGELOG 0.2.0 第十二批）；真实验收：9 文件全结构化解析、0 降级、865 节点条目，mind_path 层级最深 d10 正确
      - 探针：真实样本解析出中心主题与主分支 ✅（PECOS进度.emmx → PECOS进度/采购/特殊计算需求 等）
- [x] 先验映射规则表（native_path → 分类分支，origin=prior, confidence=1.0）——2026-10-21 补勾（第 49 批核对）：semantic/priors.py 落地，书签路径映射日常生效
- [x] 顶层大类定稿（10 类，已经 M0.5 真实数据修订）+ 未分类暂存区——2026-10-21 补勾（第 49 批核对）：10 大类经真实数据修订定稿；暂存区（/api/uncategorized + 树 UI 常驻按钮）为日常动线
      - 探针：无法归类的条目进暂存区而非硬猜 ✅
- [x] L0 价值守卫 + 价值体检通道（URL 结构规则判「非知识内容」：资源直链/站点首页/列表子页，零费用不调 LLM；`ksync --value-scan` 打标进待清理候选，用户可否决）——2026-10-20 完成（0.2.0 第十八批，实测 390 条书签中 124 条结构可判）
      - 探针：三类规则正反例单测 + classify_coarse 短路零 LLM 调用 + 打标后二次同步不翻转 ✅
- [x] 分类树 UI 完整版：点击下钻、面包屑、条目列表按 source_type 筛选、双向联动高亮；路径由 category_parents 递归 CTE 派生（不存 path）——2026-10-20 收口（0.2.0 第二十三批）：双向联动①点树看条目（早已有）+②条目列表「📁分类路径」徽标点击 → 左树滚动定位+闪烁高亮（/api/entries/linkage 批量取挂接，检索/暂存/待清理各视图通用）；下钻/面包屑/筛选为 M0.5 提前完成项
      - 探针：移动分类位置后，其子树路径派生正确（无级联重写）✅（CTE 派生 + 多父 DAG 测试在库）
- [x] 人工校正 UI：改类/合并/移动/多父挂接，全部写 task_log——2026-10-21 收口（第五十二批）：分类侧管理（新建子类/重命名/移动/合并）随 M0.5 树 UI 交付；条目侧本批补齐——单条改类弹窗（早有）+ **多父挂接**（recategorize keep_existing=true 只追加不摘旧，对话框勾选）+ **批量改类**（底部浮动条多选模式，POST batch-recategorize 逐条 task_log、batch_id 串联）+ **拖拽**（条目拖到左树节点=改挂该分类，预填路径）；task_log 统一记 old_paths/new_path（含模式），任意校正可复现前后值
      - 探针：任意一次校正可在 task_log 复现前后值 ✅（tests/test_corrections.py：keep/replace/batch/多父/复现性 5 项）

## Phase 2 — 内容层（M2）

> Gate：DeepSeek Fetch 后端 + 邮件适配器跑通；同一 URL 跨源只抓一次正文并正确合并（attach_locator，双 locator 可跳转）；默认全量同步不触发任何抓取。

- [x] http 内容获取器 · DeepSeek Fetch 后端（可插拔：默认 simple，超时/正文过短/已知难站自动升级；429 指数退避；hash 缓存保证同一 URL 不重复计费）——2026-10-20 完成（0.2.0 第二十四批）：Fetch API 2026-10-17 官方上线（POST /v1/tools/fetch 返回 Markdown，5 元/千次成功请求，仅成功计费），接入 fetchers/http_deepseek.py（429 指数退避 0.8s×2ⁿ、URL 预检 ≤8192、key 复用 KNOWATLAS_LLM_API_KEY）；fetch_with_fallback 升级路由早已就绪，用户 config 已启用 fallback_backend=deepseek
      - 探针：mock 一个 simple 失败的 URL，自动走 DeepSeek 且内容入 content store ✅（7 项 mock 测试）+ 真实冒烟（升级路由/鉴权/200 解析全通；知乎/B站连 DeepSeek 抓取器也过不去，属官方「受目标站点访问策略影响」，错误透明不计费）
- [x] kadd 联动补全：手动粘贴的 URL 自动抓正文并跑语义分类——2026-10-20 核实收口（0.2.0 第二十六批）：pipeline/kadd.py 全链路已实现（建条目 → 抓正文 → put_content → classify_coarse → 有类挂接/无类暂存），本次核查代码+测试在位，无需新代码
      - 探针：kadd 一个文章 URL，同步结束后该条目有正文且离开暂存区（或被明确标记无法抓取）✅（tests/test_kadd.py::test_kadd_full_chain + test_kadd_title_only_on_fetch_failure）
- [x] content store（正文按 content_hash 缓存，fetcher 只抓一次）——早随补抓链路落地（datalayer put_content/get_content；同 hash 不重复存）
- [x] 跨源去重（0.2.0 第三十八批，确定性判据先行）：canonical URL / content_hash 完全一致
      → 组内最早可消费条目为主，副条目 locator 走 attach_locator（双 locator 进
      entry_locators 表可跳转）+ meta 打 dedupe_master 标（只标不删，可逆），
      消费面守卫 _consumable 统一隐藏副条目；sync 入库自动判重 + ksync --dedupe-scan
      存量扫描（真实库副本冒烟：合并 77 条、幂等、消费面消失）。**simhash 近似与
      embedding 余弦（M4）后置**——误合成本高于漏合，待真实需求驱动再立项（届时先调研
      开源 simhash 实现）
      - 探针：同一篇文章在书签与邮件中各出现一次，数据层合并为一条、两个 locator 均保留
        可跳转 ✅（tests/test_dedupe.py：书签+manual 同 URL / 两 folder 同正文；
        find_by_locator 反查主条目；邮件源待 M3 接入后补真实场景）
- [x] 书签扩散抓取（0.2.0 第四十批：像微信收藏步骤三「全扒」一样，书签不只抓原文，
      还抓同一目录页同一主题内容）——种子页内链接中**与种子同目录**者（同
      scheme+host+父目录；整站同 host 链接不收，防演变成全站爬取）；新条目
      source_type='expand' + meta 记 seed_entry_id / expand_reason='series_same_dir'
      （关联解释；bookmark 类型不可用——会被书签源 full 同步归档）✅
      - 约束：显式触发 `ksync --expand <entry_id>`（不自动跑）✅；每种子默认上限
        20（--expand-limit）✅；扩散候选先过 L0 价值守卫（portal/资源页不抓）✅；
        复用 fetch_with_fallback 与 content store ✅；抓到的条目照常走分类链路 ✅
      - 探针：种子扩散出同系列条目且带 seed_entry_id ✅；被价值守卫拦截的不产生
        条目 ✅；重复扩散不产生重复条目（canonical 去重）✅
        （tests/test_expand.py 5 项，本地 HTTP fixture）
- [x] 邮件适配器（0.2.0 第三十九批：本项目**不做 IMAP 直连、不碰凭证**——外部同步工具
      （offlineimap 等）落 maildir → 本地解析；邮箱账号/文件夹/发件人/时间入 meta）✅
      - 探针：凭证错误的报错信息明确指向配置项 ✅（路径缺失/非 maildir 的 AdapterError
        message+hint 均指向 sources.mail accounts.<账号名>.path；
        tests/test_maildir.py::test_missing_path_error_points_to_config）
      - 线程增补（完整方案 §9.4 第三十一批）：还原原始会话线程（In-Reply-To/References
        + Subject 归一化）落 threads(thread_type='source') + conv_messages（迁移 003）
        ✅；引用剥离走 quote_strip（mail-parser-reply 底座【开源核实：PyPI 1.36，MIT，
        零依赖】+ 中文回复头自补规则【zh 词典缺「在…写道：」的「在」前缀与
        「------ 原始邮件 ------」分隔】，适配器本身不调 LLM）✅
      - 探针：同一回复链多封邮件还原为一条 source 线程、轮次顺序正确 ✅；多层引用邮件
        剥离后增量正文不含引用块且锚点指向被引用轮 ✅（tests/test_maildir.py 12 项）

## Phase 3 — 在线源（M3）

> Gate：IMA、腾讯文档、AI 会话、B站收藏夹、数据文件接入；凭证过期与限流有明确处理并写入 SOP 故障表。

- [x] AI 会话适配器（映射 session-harvester 输出的 SessionRecord/Message 双结构）
      ——0.2.0 第五十七批：adapters/session.py 读 harvester exports 结构化 .json
      （manifest/坏文件跳过计数），条目含 title/session_id/created_at/turns 摘要
      （前 12 轮 role:首行），全量对话正文（剔除 note/[context] 系统注入轮）落
      content_store；每会话一条 🤖 source 线程 + conv_messages 全轮次
      （msg_key=session_id#序号，引用头如实空——产物平铺无父子结构）
      - 探针：harvester 产物目录 → 条目含 title/session_id/created_at/turns 摘要 ✅
      - 线程增补（完整方案 §9.4 第三十一批）：threads(thread_type='source') +
        conv_messages（msg_key=轮次 id）已落；thread_items 为条目级粒度，轮次
        顺序由 msg_key 序号 + sent_at 承载（产物平铺，如实无父子）
      - 探针：多轮会话入库后 conv_messages 轮次/父子关系与 harvester 产物一致；
        原文不复制进 conv_messages ✅（test_session_source 端到端钉住）
- [ ] B站收藏夹适配器（官方 API：list-all 取收藏夹列表 + resource/list 分页内容；SESSDATA 走 KNOWATLAS_BILI_SESSDATA 环境变量；收藏夹名进 native_path；简介作 inline_content；WBI 签名可开关）
      - 探针：SESSDATA 失效时报错含 F12 获取指引且旧条目保留；收藏夹名正确映射 native_path；同一视频进两个收藏夹只产一条且 meta.fav_folder_ids 含两个 id；下架视频看 attr 位保留标题级并记 meta.invalid
- [ ] IMA 适配器（官方 OpenAPI：list_notebooks / list_notes / get_note_content；凭证走配置）
      - 探针：token 失效时报错含"重新获取 Client ID/API Key"指引
- [ ] 腾讯文档适配器（OpenAPI v2：文件夹列表 + async-export；429 队列降速；doc/slide 导 PDF 后二次解析）
      - 探针：模拟 429 时间隔重试成功；PDF 解析失败降级标题级
- [~] 数据文件适配器（sqlite：schema 自省 + 采样；PostgreSQL：连接串走配置，psycopg
      连接后同样 schema 自省 + 采样）——0.2.0 第五十七批：adapters/dbfile.py，
      每用户表一条目（source_key=文件名::表名，inline=行数+列清单+前 5 行采样，
      视图/系统表排除；SQLite mode=ro 缺文件 fail loud；psycopg 缺依赖/坏 DSN
      报错含指引）；sync 端到端 + 二跑幂等有测试
      - 探针：SQLite 表清单与采样行正确进入条目 ✅；连一个测试 PostgreSQL 实例
        （或 docker 起的）真机探针**挂账**（代码路径与报错指引已测，待环境）

## Phase 4 — 语义与视图（M4）

> Gate：规则 → embedding → LLM 三级流水线跑通（LLM 默认云端、配置可切本地）；混合检索、词云（三态词元）、关系图（focus 模式）可用；回归集通过率记录在案。

- [x] 规则分类器（关键词/正则/先验映射补漏）——早已在产线（L1 priors.py 先验映射 +
      L2 rules.py 关键词命中 0.8/origin=rule，kadd/sync 链路在用）；0.2.0 第五十四批
      侦察补勾（勾选遗漏，非新实现）
- [x] 会话线程语义任务（完整方案 §9.4 第三十一批，后置——先规则后 LLM）：quote_strip
      （mail-parser-reply 底座 + 中文回复头自补规则，纯规则不调 LLM；第三十九批实现）
      → delta_summarize / thread_digest——0.2.0 第五十五批完成：delta 落
      entries.meta.delta_summary（1-3 句「本轮新增了什么」）、thread_digest 落
      threads.digest（迁移 005，问题→关键进展→当前结论/待办，读全量重组不拼各轮）；
      LLM 走 [llm] 后端池；Web POST /api/threads/{id}/digest + thread.html 摘要框
      - 探针：关闭 LLM 后 quote_strip 仍工作（纯规则降级）✅；thread_digest 关闭
        不影响检索与线程视图 ✅（不写库，test_thread_digest 钉住）
- [x] 本地 embedding（bge-m3 类中文模型，optional 依赖）+ 聚类——0.2.0 第五十六批：
      semantic/embed.py（LocalEmbedder 惰性加载 + 纯标准库向量数学）+ 迁移 006
      entry_vectors + `ksync --embed/--embed-force` 增量索引 + `--cluster-report`
      （暂存区贪心聚类 + LLM 簇命名候选报告，**不建类**——§6.2「人工确认后生效」，
      确认后用既有改类 UI 挂接）；未启用/依赖缺失全部静默降级
      - 探针：FakeEmbedder 全链路测试（test_embed.py 17 项）；bge-m3 真机冒烟挂账
- [x] LLM 兜底（OpenAI 兼容接口，默认云端、配置可切本地；先聚类后命名）——L3 已提前
      接入（classify_deep，0.2.0）；few-shot 来自回归集第五十四批补上；降级探针由
      测试背书（classify 链、thread_suggest、delta/digest、聚类命名全链 llm=None 路径）
      - 探针：关闭 LLM 后系统仍可运行（纯规则降级模式）✅（各任务 llm=None 降级测试在库）
- [x] FTS5 全文检索（entries_fts + content_fts 正文索引；trigram + 两字词 LIKE 兜底）
      + jieba 关键词统计——001_init 早已建表（trigram tokenizer + 触发器同步，
      bm25/snippet 检索在产线）；两字词（<3 字符 trigram 零命中）走 search_fts 内
      LIKE 兜底（H2 返工定稿，test_two_char_query_finds_content 钉住）；jieba 关键词
      统计随词云落地（第四十三批 tf-idf top8/条聚合）；0.2.0 第五十四批侦察补勾
      （勾选遗漏，非新实现）
- [x] 混合检索（关键词 + 语义，结果可解释排序理由）——0.2.0 第五十六批：
      GET /api/search?mode=hybrid，FTS top30 + 向量余弦 top30 → RRF 融合（常数 60），
      每条带 reasons（fts / sim:<余弦>）；错字 query 纯语义命中可用；topic_recall
      第五路 sim 通道（主题词模式）；radiate sim 通道（db.py:844 挂账收口）；
      未启用降级 fts + note（探针钉住）
- [x] 时效/可信守卫（freshness guard，2026-10-20 用户需求：把过期的、容易误导的知识清出来）——
      与 L0 价值守卫同构的规则信号：页面/正文含 deprecated/已废弃/过期 类关键词、
      发布日期过旧且同主题（同 host 同标题聚类）已有更新版本、死链比例超阈值 →
      打 meta.freshness_flag=stale/suspect 进待清理候选，**只标记不自动删**（用户否决权同
      value_flag 口径）；「易误导」的语义判断成本高，LLM 判定后置（YAGNI，规则信号不够再上）
      （0.2.0 第四十一批：keyword→stale / date_old·newer_version→suspect，
      `ksync --freshness-scan`，UI「时效候选」；死链比例信号后置——单条死链已由
      link_status=dead 承接，host 级比例批量标待真实需求定义）
      - 探针：deprecated 关键词样本被打 stale ✓；同主题新旧并存时旧的进候选 ✓；
        用户否决后二次同步不翻转（与 value_flag 一致）✓
- [x] 词云视图（三态词元：scoped cloud 范围随焦点分类子树变化；分类词元点击进入子分类并联动分类树；内容词元点击 = facet 过滤当前范围；字号 ∝ √权重；按主导顶层分类着色）
      （0.2.0 第四十三批 v0：`GET /api/cloud`；词元=jieba tf-idf top8/条聚合，噪音词三道闸；逐级回退后置——「↩ 全库」一步复位）
      - 探针：切到某大类，词云只反映该子树条目 ✓；点分类词元树同步跳转 ✓；点内容词元条目列表按该词过滤 ✓
- [x] 关系图视图 v0.5（0.2.0 第二十二批落地，终态形态 2026-10-20 用户两轮定调收敛：
      **大类总览 → 搜索驱动的按需子图 / 点击下钻**——全量力导会拖垮，初始只显示一级大类
      （气泡大小=子树 active 数）；搜索框按条目标题/分类名出相关子图（只带命中条目+分类链，
      不扩散拉全子树）；点分类下钻子树（祖先链灰底作上下文），点条目打开原文；
      旧 v0 全量力导图（/api/graph）保留兼容。相似度语义边随 M4 接入——0.2.0
      第五十六批 radiate sim 通道（条目焦点向量邻域 reason=sim:<余弦>）；共现边
      （cocategory）已由 topic_recall 承载，图内共现边待真实需求驱动再立项）
- [x] 串联工作区（主题工作区，契约草案见完整方案 §9.4——用户 2026-10-20 定调最高优先：
      痛点「知道要什么但散落各处难串联」）——threads/thread_items 表 + topic_recall 多路召回
      （FTS/共现/同源/显式关联/语义相似，每条带 relation_reason）+ 线索编辑保存复用 +
      thread_suggest 排序建议——2026-10-20 完成（0.2.0 第三十二批）：迁移 002 落
      threads/thread_items（thread_type 列就绪，source 型随邮件/AI 会话适配器用）；
      DataLayer 线索 CRUD + 条目增删移（task_log 审计）；topic_recall 四路纯规则召回
      （fts/cocategory/same_host/thread，语义相似通道留待 M4 embedding）；thread_suggest
      LLM 排序建议（llm 缺失原序降级）；Web API 端点组 + static/thread.html 工作区 +
      index.html 入口与「固化为线索」；14 项测试 + canary 升版
      - 探针：输入主题聚合出跨源条目（带关联解释）✅；串成线索保存后重开不丢 ✅（持久化测试）；探索路径可固化 ✅（POST /api/threads entry_ids + 检索视图按钮）
- [x] 放射导航增强（在关系图三视图上迭代，不推翻）——2026-10-20 完成（0.2.0 第三十三批）：
      radiate/reverse_reach 数据层（纯查询无 DDL，canary 不变）+ /api/graph/radiate|reverse
      端点（只读免令牌）+ graph.html 导航层重写——导航栈与面包屑任一级回跳、放射模式开关
      （焦点居中黄标、域名节点恒走放射）、边带 relation_reason（tooltip 恒显 + 🏷开关）、
      反查面板（分类带路径可跳、线索跳 thread.html）、展开更多 ×3 渐进披露（封顶 40）、
      空层降级不压栈、🧵固化为线索；thread 通道与第三十二批串联工作区双向打通
      - 探针：放射出去的每个节点能回答「为什么和当前焦点关联」✅（reasons/reason 完备性
        测试 + 真实库冒烟）；面包屑任一级可回跳 ✅（nav 栈截断重放）
- [x] 统一入口工作台——2026-10-20 完成（0.2.0 第三十四批）：搜索框升级为工作台入口，
      检索提交后三视图切换（默认聚合结果）——「聚合结果」= FTS ∪ topic_recall 按条目
      去重合并、每条带关联解释徽标；「线索」= 批量 /api/threads-lookup 聚合命中条目
      所属线索（跳 thread.html）；「放射」= 焦点条目邻域按通道分组列表（点邻域切焦点
      持续下钻）+「🕸️ 在图中打开」深链（graph.html ?node= 直达放射）。模式是视图切换
      不是启动分叉（§9.4 定位条款）；零新增 LLM 调用、不建新表
      - 探针：检索后三视图切换无报错、聚合无重复 ✅；放射切焦点正常、深链直达 ✅；
        既有功能不回退 ✅（其余视图零改动）
- [x] 时间线视图 + 陈旧分支提醒（长期无新内容的分支提示清理或归档）——
      scoped timeline：范围随焦点分类子树；时间轴走 created_at（内容时间，
      exported_at 入库时间无分布意义不用）；跨度 >24 个月→年粒度否则月粒度
      （可手动切换）；空桶补齐；柱点击下钻该桶条目；created_at 缺失只进
      「时间未知」计数不编造时间；陈旧分支=子树内叶子分类最新条目超 2 年
      （阈值可调）→ 只提醒不删，清理/归档走左侧树管理按钮；时间未知的分支
      不判陈旧（时间未知 ≠ 陈旧）
      - 探针：切到某子树桶只反映该子树 ✅；粒度自适应+显式覆盖 ✅；停滞叶子
        进提醒、有新内容不命中、无 created_at 不判陈旧 ✅；bucket 下钻可消费
        口径（待清理不出、空桶不炸）✅；阈值参数化 ✅

## Phase 5 — 导出与运维（M5）

> Gate：三种导出格式验证通过；备份恢复演练一次成功；MCP 端点可被 agent 调用。

- [x] JSON 全量导出（Schema 版本化，含 schema 版本字段）——
      schema_version=1.0 常量；全量含 archived/rejected；entries 带
      locators/categories/meta + inline_content 内联（content_store 全量正文
      不内联，SOP-E 注明自行拷贝）；categories 带 parents DAG + threads 同投影
      - 探针：schema_version 存在且 counts 对账 ✅；关联完整（locators/categories/meta）✅
- [x] Obsidian vault 导出（条目笔记 + 分类 MOC 笔记）——
      条目笔记（frontmatter + inline_content + 回链全部父 MOC）放主分类目录；
      MOC=分类名（安全化避撞）列全部直挂条目 + 子分类链接；active 全量
      （防锁定优先），archived/rejected 不进
      - 探针：每分类有 MOC ✅；条目笔记有 frontmatter + [[MOC]] 回链 ✅；
        多父条目在所有父 MOC 出现 ✅；文件名安全化重名不互覆 ✅；
        导出目录可直接被 Obsidian 打开且双链可用（短链全局解析；重名分类
        短链歧义为 v0 已知限制）✅
- [x] OPML 导出（书签类条目往返）——
      书签类=active 且 locator_canonical 以 http 开头（可解释判据）；
      分类 DAG 展平 outline 树（多父重复出现），未分类落「（未分类）」根；
      导出文件可被标准 XML 解析重建无损树（往返保真）
      - 探针：XML 可解析 ✅；outline 嵌套=分类层级 ✅；叶子数=http 条目数 ✅；
        往返重建无损 ✅；OPML 导入回路已实现（0.2.0 第五十批：ksync 批量源
        [sources.opml]，source_type=opml，往返回吃探针 ✅）
- [x] 自动备份（同步前 VACUUM INTO 快照，保留 10 份轮换）+ 恢复演练——
      SQLite 官方 VACUUM INTO 一致性快照（WAL 安全，不自己拷文件）；同步前
      自动快照 + 节流（默认 24h，backup_min_interval_hours）；契约=没快照不
      同步（备份失败中断、不写库；backup_on_sync=false 可关）；轮换删除白名单
      （backup_dir 内 + knowledge- 前缀 + .db 后缀 + 时间戳名，绝不碰用户文件）；
      恢复自包含（安全网快照 → 关连接 → 删 -wal/-shm → 拷回 → integrity + 条目数
      对账），只接受 backup_dir 内自家快照（防路径穿越）
      - 探针：WAL 开启状态下从快照恢复（含删 -wal/-shm）后条目数与快照时一致 ✅
        （真实库副本演练：active 1837/全库 6976 破坏 -50 后完整恢复）
- [x] MCP 只读查询端点（检索 + 树遍历，供 agent 查询）——
      v0 = REST 只读投影：GET /api/mcp/search（FTS 检索）/ /api/mcp/tree
      （树遍历）/ /api/mcp/entry/{id}（详情 + 正文前缀 substr 截取）；真 MCP
      协议（stdio/SSE，mcp SDK）后置不加依赖；GET 无副作用不走写令牌，仍受
      本机 Host 白名单约束
      - 探针：只读校验——端点无任何写操作 ✅（AST 扫描三 handler：无写方法
        调用、不摸私有 _conn、无非 SELECT SQL，测试钉死）
- [ ] 打包安装：任意目录可用（2026-10-19 用户需求）
      - 内容：构建 wheel 发布（PyPI 或私有源）；数据目录策略——默认 `%USERPROFILE%/.knowatlas/`（db/config/data 均在此），环境变量 `KNOWATLAS_HOME` 覆盖；config 自动发现顺序 = `KNOWATLAS_HOME` → cwd → `~/.knowatlas`；路径推导禁硬编码用户名/盘符（项目可迁移铁律第 4 条）
      - 探针：新机器 `pip install knowatlas` 后在任意目录跑 `knowatlas serve`，数据落在 `~/.knowatlas/`；换 `KNOWATLAS_HOME` 后数据落新目录

## Phase 6 — 高风险源（M6，可选，最后做）

> Gate：脚本失败不影响主流程；收藏链接路线三步骤跑通；聊天记录导出产物按文件源扫描纳入。

- [ ] 微信收藏 · 步骤一取链接：从 favorite.db 轻量提取标题 + URL（或用户手动粘贴链接清单），落固定目录 JSON（一条一行含 title/url）
      - 探针：链接清单生成；主工具不依赖 favorite.db 全量解密
- [ ] 微信收藏 · 步骤二解析 biz：mp.weixin.qq.com 链接提取 `__biz`；非公众号链接触发普通 http 抓取
      - 探针：混合链接清单正确分流
- [ ] 微信收藏 · 步骤三全扒：按 biz 调 wechat-article-exporter 拉该博主全部文章，Markdown 入 content store；条目 meta 记 seed_entry_id + biz，视图支持"展开该博主全部相关文章"
      - 探针：一个种子收藏条目可展开显示该博主全部相关文章；exporter 失败不影响主流程
- [ ] 主工具按文件源扫描（wxfav scheme + wxfav_reader；扒取产物按 file:// 处理）
- [ ] 微信聊天记录源：集成 WeChatMsg / MemoTrace 活跃 fork 解密导出（HTML/MD/sqlite），主工具按文件源扫描产物目录
      - 探针：fork 版本失效时明确报错，主流程不受影响

## Phase 7 — 知识模型升级（K7，2026-10-21 新增；依据 docs/design/知识索引工具-知识集与知识生命周期方案.md 定稿 v2）

> Gate：点层可溯源可去重；组头无发明性命名；老化裁决后有删除出口；勘误附注不篡改原文；全部批次 CHANGELOG 记账。
>
> **2026-10-24 对账回填**：第 59/60/61/62/63 项实际已完成——分别见第 59 批（59）、第 60 批（60）、
> 第 61 批（61/63）、第 65 批（62）；原 `[ ]` 系台账冻结于第 58 批所致，本次只回勾不改需求
> （详见 CHANGELOG 与 `需求实现对比表-2026-10-24.md` §8）；
> 64b（全量 suspect 判定）/ 65b（全量勘误核查）仍为**决策债**，等用户裁决是否开跑。

- [x] 59 布局三层信息架构（页签化/管理页/收录入口/bookmarklet 常驻；第五十八批左栏折叠已落第一步）
      - 探针：主视图页签化（检索/关系图/串联/词云/时间线/管理）；管理页集中暂存/待清理/失效链接/时效候选/数据管理；日常消费页无管理控件
- [x] 60 知识集列表（sim 通道 + 贪心聚类 + 信号组头接入检索视图；组头=成员自身信号，禁发明性命名——用户裁决第 1 条）
      - 探针：检索命中按集分组展示，组头词可在组内任一条目验证；无编造容器名
- [~] 61 知识点抽取（形态判定 integral/split → 切点 → 规范化 hash 去重一点多溯源；迁移 007 points/point_sources；首批 50 条抽检固化为回归集；衔接 delta/digest 对点跑——用户裁决第 2/3 条）
      ——2026-10-24 对账：核心已由第 61/62/65/66/92 批完成（点抽取、口径规则化、hash 去重、提炼式入库）；
      **「首批 50 条抽检固化回归集」未完成**（真库仅 4 条案例），单独挂 R6；另见裁决 1 新增的「自洽性闸门」（Phase 8.5）
      - 探针：split 型文档切出点带溯源指针与判定理由；同观点重复文档合并为一点多溯源；integral 型整条即点不碎切
- [x] 62 emmx 全删重灌（备份→全删→适配器形态判定改造：方案型整图即点/讨论型才切→重灌→抽检 20 文件——用户裁决第 2 条）
      ——2026-10-24 对账：第 65 批已执行（802 条 purge → 226 条重灌，integral 5 / split 4，抽检有判定理由）；
      第 92 批再整理为 integral + 中文结构化点
      - 探针：重灌后 integral 型无节点碎片、split 型挂 mind_path；判定理由可查；总条目数 ≤ 原 802
- [x] 63 关系图纯层级下钻（点分类只出下一级子分类，条目在叶子层或显式展开出现）
      ——2026-10-24 对账：第 61 批完成，`graph.html` `#hier` 默认开 + localStorage 记忆
      - 探针：技术开发→前端→javascript 逐层钻取符合用户 4.1-4.3 预期
- [x] 64 老化三级补全（LLM 级对 suspect 逐条判定；人裁废弃→即刻 rejected 全面不可见→30 天冷却→自动物理删除，含 content_store 引用计数——用户裁决第 4 条）**——批次 64a 代码部分完成（第六十三批）：L2 aging_judge（三值结论+防幻觉闸门 stale 无依据降级 keep）+ kaging CLI + 30 天冷却删除出口落库不批量执行 + Web 冷却徽标；pytest 365 全绿；全量 suspect 判定（~87 条）与真实库删除等用户裁决（64b）**
      - 探针：裁决废弃后条目从全部视图/检索/词云/导出消失（✓ 已验，fixture）；冷却期满后物理行删除、审计链留痕、共享内容块只减计数（✓ 已验，fixture）
- [x] 65 勘误三级（L1 只做确定性错误防误报；L2 结论必须附可核查依据否则只标疑似；L3 改正=勘误附注层原文不改写 or 废弃同 64 出口）**——批次 65a 代码部分完成（第六十四批）：L1 确定性检查（完整代码块语法验证 + 已移除 API 对照表，节选不下结论宁漏勿误）+ L2 errata_check（error 必附依据否则降 suspect，suspect 不出裁决队列）+ L3 附注层（meta.errata 并显原文不改写）+ kerrata CLI（--scan 零费用/--limit 10 试跑）；pytest 391 全绿；L2 全量核查（~600 条）等用户裁决（65b）**
      - 探针：疑似错误不到确认级不出裁决队列（✓ 已验，fixture）；改正以附注并显、原文 diff 为零（✓ 已验，fixture）
- [ ] 并行待办（不占批次编号，按触发条件穿插）：真 MCP 协议（Phase 5 挂账）/ B站·IMA·腾讯文档三凭证源（等凭证）/ Phase 6 微信收藏+聊天记录（等导出产物）/ wheel 打包（收官后）/ bge-m3 真机冒烟·PG 真机探针 / 回归集积累 50-100 条 + 规则误判修订（Google→华为云、Agent→文学创作）/ harvester exports 目录接入 config / 词云签名缓存

## Phase 8 — 数据源全覆盖 + 统一清洗层（2026-10-24 用户需求澄清后新增）

> Gate：八类源全部接通；**任一源入库后，检索/关系图/词云看到的都是知识聚合而非文件名**；
> 点层通过「自洽性」人工抽检（20 点，独立可读懂率 ≥ 90%）。
> 依据：`需求澄清与裁决-2026-10-24.md`（用户七点需求 + 三点裁决）、`知识索引工具-清洗层方案.md`（批 97 设计）。
>
> **执行序（用户 2026-10-24 裁决）**：先用**小样本可控源**把逻辑与表现跑顺，再上大数据量源。
> 用户原话：「AI 会话和邮件微信记录的数据量太大了。至少得先确保逻辑和表现都没问题，再做大的。」
> 阶段 A（先做）：8.1 → 8.2 → 8.3 → 8.4 → 8.5 → 8.6；
> 阶段 B（A 验收通过后再启）：8.7 → 8.8 → 8.9 → 8.10 → 8.11 → 8.12 → 8.13 → 8.14。

### 阶段 A — 小样本可控源（先做）

- [~] 8.1 统一清洗层 · 97a 通用段（**通用段已落 2026-10-24**：`clean.py`（`clean_common`/`CleanThresholds`/`CleanResult`/`redact`/`is_navigation_doc`）+ `sync._ingest_content` 单一收口（清洗→脱敏→SHA-256→content_store）+ `_store_bodies`（mail/session/emmx 只清正文库、不动 inline）+ `[clean]` 三键 + R10 降级 WARN；27 例单测、全量 508 passed）
      - 探针：真实文章 / 邮件 / 会话各 1 份清洗前后 diff 落 `temp/`；误杀用例（教 HTML 的文档、含签名但正文有实质的邮件）不误剔；真库重同步垃圾与重复条目零新增
      - **真实基线（样本验证 2026-10-24）**：20 份真实正文 105,846 行，识别噪声 4,896 行（页码 2,578 / 目录 1,555 / 重复行 751 / 推广 10），正文行保留率 **0.9999**；`agentic-design-patterns` 页码 1,347→0、目录 273→0；`agentic-ai-guide` 目录 994→0；`Harness`/`Obsidian-AI` 推广尾→0；`雪花写作法` 零删除；5 篇 PDF 各留 ≤1% 低占比数字行（阈值下按设计保留）
      - **顺延**：trafilatura 换装 → **8.1b（97a+）**，用同批样本 A/B（用户 2026-10-24 认可，避免两个变量混淆归因）；HTML 实体解码随换装；IMA 验收 → 8.12（本机无凭证）
- [x] 8.2 办公文档 / PDF（**97b 已完成 2026-10-24**：`fetchers/pdf_fast.py` PDFium 逃生通道 + `file_reader._read_pdf` 双通道 + `[fetch].pdf_backend` + `clean_paged` 页边界规则 + 大文件闸门 + 扫描件判定；11 例新测 + 7 例页边界用例，全量绿）
      - 探针：真实 docx / pptx / PDF 各 1 枚入库，页眉页脚与页码不进正文 —— **PDF 已验**（厦大删 60 个页边页码 + 410 行跨页重复讲义标题；正文残留的独立数字抽样确认是 `01/03` 步骤号、公式 `6`、`0.333` 等数据）；**docx/pptx 未验**（本批无样本，Office 页眉页脚继续靠通用段的"重复行 + 周期性"规则）
      - **实测（2026-10-24）**：`Hello-Agents` 97.9 MB/720 页 25 分钟 → **3.29 s**；`厦大讲义` 51 MB/882 页 8 分钟未完 → **1.96 s**；其余 9 份 PDF 留在 markitdown（pdfium 对 `agentic-ai-guide` 只取到 30% 字符、对 `AI-Agents-in-Depth` 43%，所以 auto 阈值定在 **30 MB / 1500 页**，pdfium 只做逃生通道）
      - **扫描件**：平均每页 <20 字符 → `DegradedParseError("scanned_pdf")`，不产条目正文（OCR 不在本期）
      - 遗留：`content_store` 6 行孤儿正文（反复 `--force` 重灌留下）→ 见 8.15
- [ ] 8.3 书签 + HTML 网页（`adapters/bookmark.py` 已就绪：配 `paths.edge|chrome` 后跑通；`http_simple` 接通用段清洗；导航/按钮墙/骨架不产条目）
      - 探针：真实 Bookmarks JSON 同步，条目数=有效书签数；抓取页清洗后正文无导航残留
- [ ] 8.4 本地文本/HTML 文件（`sources.folders` 先指一个**小目录**验 file:// 链路：md/txt/html 直读；Office/PDF 走 8.2）
      - 探针：10 个以内文件入库，native_path 与目录层级一致；空文件/乱码文件不产条目
- [x] 8.5 **知识点自洽性闸门**（裁决 1）：点必须是可独立读懂的完整单元——带论据的观点/结论、概念解释或术语描述、完整步骤、独立数据；**禁裸名词、禁截断步骤**；一个文件只产 1 个点是合法输出
      ——**2026-10-24 已完成**（工单 `变更工单-2026-10-24-8.5自洽性闸门.md`）：新增
      `pipeline/point_gate.py` 确定性闸门（7 个原因码：过短/裸名词/步骤缺首/跳号/缺尾/
      尾部截断/代码块未闭合）；`point_extract` 三份 prompt 增自洽性纪律并允许 `points: []`
      （= 无可独立成点的知识，不算故障）；`points.py` 逐点过闸、全拒条目记
      `meta.points_gate` 防重复烧钱、`kpoints --retry-blocked` 重抽；Web 条目级重抽清标记。
      真实库 27 点 **0 误杀**，6 类反例全拦；**"一句干巴巴结论"不做机器判定**（与单句
      术语定义不可分），交 prompt + 人工抽检。
      - 落实点：`semantic/tasks/point_extract.py` prompt 增自洽性纪律 + `pipeline/points.py` 守门（长度下限、裸名词判不合格、步骤缺首尾判截断）
      - 探针：抽检 20 点人工判「能否独立读懂」（**2026-10-24 已抽**：随机 20 点，**19/20 = 95%**
        可独立读懂，达到 Phase 8 Gate 的 ≥90%；唯一不合格点是 LLM 把提示词约束写进正文
        「该方法以中文输出，定位为短篇/都市小说创作指导」→ 下一小批 prompt 补"不得保留面向
        生成过程的指令性描述"）；反例已固化进 `tests/test_point_gate.py`（"JavaScript 数组"裸名词、步骤只有中间两步、跳号、尾部省略、未闭合代码块）
      - **已知残留**：LLM 偶发把提示词约束（输出语言/篇幅/格式）写进点正文；闸门无法确定性
        区分"方法确实规定用中文写作"与"模型复述指令"，需靠 prompt 纪律修正，已记入交接下一步
- [ ] 8.6 **三视图知识聚合验收**（裁决 1 + 用户第 4–7 点）：全库 / 关键词 / 精确词三级检索都给知识；关系图下钻逐层细化；词云词元来自点文本
      - 探针：搜「异步」与搜「async」分别复核——只出对应知识，不出文件名；**任一视图出现裸文件名条目即 FAIL**
      - 注：裁决 2 已明确「收敛非硬约束」，本项只考核精确词 top-N 精度，不考核结果数单调性

### 阶段 B — 大数据量源（阶段 A 验收通过后再启）

> **入库前置审（用户 2026-10-24 采纳，适用于 8.8–8.10 全部大源）**：
> 大体量/高噪音源**禁止全量直灌**，统一走三段——① 适配器层先按范围筛（联系人/群、时间窗、
> 关键词、发件人/邮件列表），② 源配置 `new_entries = "pending"` 让新条目进「🆕 待审」
> （不抓正文/不分类/不抽点，省抓取与 LLM 费用），③ 批量转正后抽样复核，拒绝理由反哺适配器
> 规则（让下一轮待审量单调下降）。**不做逐条人工确认**——几万条会话靠待审列表翻不完。
> 现有机制见 `pipeline/sync.py` 批次 68 + `/api/pending` + 管理页「🆕 待审」，本批只补适配器
> 范围筛选与待审预览信息（参与人数/消息数/字符数）。依据：`需求澄清与裁决-2026-10-24.md` §2
> 「只留知识」+ 用户 2026-10-24 会话口径。

- [ ] 8.7 万兴脑图接入验证（配置已指 `roots=["D:/sData/KnowLedge"]`，现存 1 个 `.emmx`；先 `enabled=true` 跑通「节点→点→检索→树浏览」全链，再决定是否扩到批量脑图库）
      - 探针：该文件 integral 判定 + 整图点入库；`/api/entries/{id}/emmx_tree` 树形浏览可开合
      - **格式缺口（样本验证 2026-10-24）**：样本是 `Document Version="14.0.3"`，`document.xml` 只有 `<Properties>`，节点树在 `mmpage/page*.bin` 二进制页里；适配器只认旧版 `page.xml` → `nodes=0, degraded=1`。已探明 bin 内节点文本为 **UTF-8 明文**（原型/原型链/作用域/闭包/箭头函数 4 页），可实现流式抽取；层级需从二进制记录解出 → 需单独立项（不属 97a）
- [ ] 8.8 AI 会话（97d：`sources.session.harvester_dirs` + 分支主干 + 平台思考块剔除 + redact）
      - 探针：真实导出会话清洗前后对比；条目含 title/session_id/turns 摘要
- [ ] 8.9 邮件（97c：furniture 补丁 + redact + 线程还原）
      - 探针：真实签名邮件剥离前后对比；线索库 thread_type=source 正常
- [ ] 8.10 微信聊天记录（97e：媒体处置 + 四类剔除 + 按日线程 + pending 缓冲；等导出产物）
      - 探针：垃圾轮次（寒暄/表情/系统消息）零入库
- [ ] 8.11 微信收藏链接（取链接 → 解析 biz → 全扒；`wxfav` reader 落地）
      - 探针：一个种子收藏展开该博主相关文章；exporter 失败不影响主流程
- [ ] 8.12 微信 IMA（等 Client ID / API Key）
      - 探针：token 失效报错含重新获取指引
- [ ] 8.13 腾讯文档（等 app_id；async-export + 429 队列降速）
      - 探针：429 按间隔重试成功；PDF 解析失败降级标题级
- [ ] 8.14 万兴图示（新源，现有只认 `.emmx` 脑图；格式与路线待用户样本：`.edx` 直解 / 导出件 / 截图 OCR）
      - 探针：真实图示文件解析出节点层级；与脑图共用形态判定与剪枝规则
- [x] 8.15 正文库孤儿回收（`kcheck --gc-content`）—— 97b 重灌留下的 6 行无条目引用 `content_store` 正文
      已回收（2026-10-26，`datalayer/db.py::gc_orphan_contents`）：只删「无任何 `entries.content_hash`
      指向、且 `fetched_at` 早于 `--gc-days`（默认 1 天）」的行，`content_fts` 同步清、`task_log(content_gc)`
      留痕、`--dry-run` 零写入；`fetched_at` 缺失/坏串的历史行按最老处理（正文是缓存，可重抓）。
      现场：6 行 / 2,552,280 字符 → content_store 55→49、orphans 0、有引用的 49 行原样；重跑 0。
      测试 `tests/test_content_gc.py`（4 例）。
## 对账修复清单（2026-10-24）

> 来源：`需求实现对比表-2026-10-24.md` §11 的 8 处文档与实况不一致。文档层已全部处理；R7/R8 代码已修（用户 2026-10-24 授权）；
> R6/R9 **受阻于本机无真实数据**，等阶段 A 灌入数据后再议。

已处理（文档层，本次）：
- [x] R1 TODO Phase 7 第 59–63 项回勾（以 CHANGELOG 为准，见 Phase 7 顶部对账说明）
- [x] R2 `完整方案` §8 增补「8.1 实施期修订」：端点实况 70 个 + 两处契约形态变更
- [x] R3 CHANGELOG 补第 96 批（代码已提交、账缺失）与第 97 批（设计立项，无代码）
- [x] R4 夜跑批次计划补注「97 为设计立项、代码未落地」
- [x] R5 新增 `需求澄清与裁决-2026-10-24.md` + `知识集方案` §7.1 自洽性增补

已处理（代码层，本次）：
- [x] R7 版本号统一：`__init__.py` 0.1.0 → **0.2.0**（`--version` 现输出 `knowatlas 0.2.0`，与 `pyproject.toml` 一致）
- [x] R8 `serve --port` 回写 cfg：新增 `cli._apply_serve_overrides(cfg, host, port)`，`create_app` 前覆盖
      `general.server_host/server_port`；回归测试 `test_serve_port_override_updates_host_whitelist`；
      实测 `serve --port 9101` → `/api/stats` 200、首页 200（修复前 403）

受阻（本机无数据，暂时做不了）：
- [ ] R6 回归集补齐 50–100 条——本机 `data/knowledge.db` 为**空库**（entries/points/regress_cases 均 0），
      `~/.knowatlas` 不存在。需阶段 A 接通小样本源并人工确认 ≥50 条后才能固化。
      （2026-10-24 18:0x 更新：样本已灌入 30 条目 / 32 点，**可开始人工确认**，但仍需用户逐条点 ✓）
- [ ] R9 64b（全量 aging suspect）/ 65b（全量勘误核查）——同上，现库 suspect=0、勘误=0，无从开跑；
      需真实库搬迁或阶段 A/B 灌数据后再议（费用 <¥1 与 ~¥3 的决策仍然有效）。

新增（本轮实证发现，待开工）：
- [ ] R10 **LLM 键缺失被静默降级**：`[llm] enabled=true` 但所有 `api_key_env` 指向的环境变量为空时，
      语义层安静退回规则降级 —— 表现是 `kpoints` 产出"整篇 4023 字"的 integral 点、split 文档归零，
      用户与 agent 都看不出"其实是没连上 LLM"（本轮实际踩到：key 早配在用户级环境变量，
      但进程晚于 `setx` 启动导致读不到）。建议启动时对该状态打 **WARN + 明确提示"语义层降级"**，
      并让 `kpoints` 报告里带上 `llm_available: false`。改动面：`config.py` 校验 + `cli` 启动输出 + 一处测试；
      建议随 97a-2 一并落（同一批改动都在启动/配置路径）。

## 阻塞项

无。原 5 项阻塞事项已于 2026-10-19 第二次确认全部定稿（详见设计方案 §10.1 决策记录）：聊天工具=微信；pq=PostgreSQL；微信收藏=链接全扒路线；部署=本地 Web 服务；LLM=云端 API 默认、配置可切本地。另新增定稿：词云=三态词元架构（scoped cloud + 双态词元 + 关系图 focus 射线）；新增手动链接入口（kadd / UI / bookmarklet）。

2026-10-19 契约返工（H1 多 locator / H2 正文索引 / H3 upsert 与删除检测 / H4 path 派生 / H6 备份安全 / H7 B站 source_key / K1 默认不抓正文 / K2 M0.5 / K3 仓库化）已全部落入设计方案与完整方案，详见 handoff/变更工单-2026-10-19-契约返工.md 与 handoff/变更工单-2026-10-19-安全与API修正.md；阻塞项仍为无。

**2026-10-24 新增两项待用户拍板**（Phase 8 排期前置，不影响已开工项）：

1. **万兴图示的文件形态**——决定 8.9 适配器路线：直解 `.edx` 二进制 / 扫导出件（PDF、图片）/ OCR。
2. **源接入顺序**——建议：8.1 清洗层 → 8.4 AI 会话 → 8.5+8.6 微信 → 8.7/8.8 需凭证源 → 微信收藏链接。

另：R9（64b 全量老化 / 65b 全量勘误是否开跑）属费用决策债，各 <¥1 与 ~¥3，不计入阻塞项。

## 2026-10-25 裁决：知识点生命周期机制 + 点层粒度（已排序，逐项开工）

> 来源：2026-10-25 用户三问（勘误/老化要成为机制、只针对非社科人文知识；检索/分类/词云/关系图出的是章节名；
> 关系图要 wiki 式点级关联）+ 当日 4,509 点全量勘误实测（hard 1,579 / wrong 37 / suspect 348）。
> 排序原则：**先立机制（便宜、当天可验收），再改点集（贵、要重抽全库）**；点级结论一律用
> `content_hash` 做键，P3 重抽后**同一文本的点自动继承结论**，不因重抽作废。

### P0 · 分诊落库 + 领域闸门（前置，小）

- [x] 把 `temp/errata_full_triage.json` 的三分诊写进 `point.meta.kind`
      （`hard` / `opinion` / `unjudgeable`，附 `kind_why`、`kind_at`、`kind_model`）。
- [x] 新增入口 `kpoints --triage [--limit N]`（幂等：已有 kind 的跳过；LLM 不可用则整批 skip 不写半成品）；
      附 `--from-json PATH` 导入既有分诊产物（零 LLM 费）。
- [x] **领域闸门**：后续勘误/老化只处理 `kind=hard`；`opinion`/`unjudgeable` 一律不判对错、不判过时。
- 验收：`select json_extract(meta,'$.kind'), count(*) from points group by 1` 与报告一致（1,579/2,016/914）。
- 契约：`points.meta` 新增键，不改表结构；需在 `_SOURCE_FIELDS` 保护说明里登记。
- **已实施（2026-10-25，工单 `变更工单-2026-10-25-点分诊.md`）**：实跑 4,552 点 →
  **dupe 43 / hard 1,579 / opinion 2,016 / unjudgeable 914**（dupe = `meta.dupe_of` 重复点，
  确定性标记、不进 LLM）；重跑 candidates 0、零写入（幂等）；闸门唯一出口
  `pipeline/triage.py::is_hard` / `HARD_SQL`，P1/P2 只准 import；测试 590 passed / 1 skipped。

### P1 · 勘误从「一次性」变「机制」

- [x] 新增 `kerrata --points`（点级事实核查）：分诊 hard → 分批复核 → 结论写 `point.meta.fact_check`
      （`verdict`/`reason`/`evidence`/`at`/`model`/`stage`），**只标不删**。
- [x] 幂等与增量：以 `content_hash` 为键 + `fact_check.at` 游标，已核的不重跑；新点自动入队。
- [x] 裁决队列：`wrong` 进「勘误裁决」页签（点级条目，带理由+依据+溯源）；`suspect` **不进队列**，
      只做筛选视图（§7.6 纪律：不到确认级不出队列）。
      **已实施（2026-10-25）**：只读 `GET /api/errata/points`（37 条）；UI 页签渲染留 P1b。
      **P1b 已接（2026-10-26）**：管理页「误报裁决」同页签双区（条目级 + 点级），
      点级带原因码徽标/理由/依据/溯源 + 「↩误报，保留」。
- [x] 原因码：`fact_error`（事实错）与 `overclaim`（绝对化表述：必须/只能/始终/有且仅有，且原文无限定条件）
      分开记——实测 wrong 的三大类正是「机制说错 / 规格细节错 / 绝对化」。
- 验收：用当日 37 条 wrong 回放，队列条目数 = 37；重跑一次零新增（幂等）；新入库一点后自动进待核。
- 成本：全库 hard 1,579 条 ≈ 交付实测约 12 分钟 / 4 线程。
- **已实施（2026-10-25，工单 `变更工单-2026-10-25-P1点级勘误.md`）**：种子回放 1,579 条 →
  **wrong 37 / suspect 348 / ok 1,194**（零 LLM）；重跑 candidates 0；队列 API 37 条带溯源；
  测试 598 passed / 1 skipped。
- **P1b 已补齐（2026-10-26）**：`kerrata --points --backfill-codes` 回填 37 条原因码
  （**32 fact_error / 5 overclaim**，2 次调用，重跑 candidates 0）；写接口
  `POST /api/points/{id}/fact-check/dismiss`（人裁出队，结论/依据/溯源保留）；
  管理页点级区块。测试 603 passed / 1 skipped，canary 零漂移。

### P2 · 老化从「被动」变「机制」，且分两型

- [x] **版本型**（确定性优先）：从点文本抽版本号（`Python 2.7`、`Django 2.x`、`jQuery 1.x`），对照可维护的
      EOL 表（python.org / nodejs / django 等官方支持矩阵，落 `data/` 或配置）；命中 EOL → `stale`。
      给不出官方依据不判 stale（降 `suspect`）。
      **已实施（2026-10-26）**：`semantic/eol.py` 内置表（8 个有官方矩阵的技术 + 官方 URL），
      `data/eol.json` 可覆盖；保守方向——未收录版本降 `suspect`，`LIVE_MAJORS` 防「Python 3.x」误杀，
      「或更高版本」语境过滤（真库自检抓到两类假阳性后补的）。
- [x] **退场型**（LLM + 依据）：判「该技术是否仍在被使用/维护」，必须附官方弃用公告或等价依据；
      给不出降 `keep`（沿用 `point_aging` 的防幻觉闸门）。
      **已实施**：`point_lifecycle@1.0.0`，按**技术栈分组**（20 组/批，同一技术只判一次）。
- [x] 触发方式：不再依赖「条目被日期规则标 suspect」——新增主动扫描入口（`kaging --lifecycle`），
      按 `kind=hard` + 技术栈分组批量跑；结论写 `point.meta.lifecycle`
      （`kind: version|retired`、`verdict`、`evidence`、`at`）。
      **已实施**：`pipeline/lifecycle.py`，`stale` 复用 `set_point_aging` 退出消费面，幂等游标 `lifecycle.at`。
- [x] 输出：`stale` 退出消费面（现成机制），`keep`/`suspect` 只进人裁列表；仍**不自动删**（30 天冷却后删）。
- 验收：造 6 条样本（Python 2.7 教程 / jQuery 插件教程 / Python 3.12 教程 / 通用方法论 / 观点文 / 未来预测），
      前两条 stale、后四条不判 stale；全库重跑幂等。
      **已通过（单测 `tests/test_lifecycle.py::test_version_type_acceptance_samples`）**；
      真库实跑 1,579 hard 点 → **0 stale / 39 ok**（本库无过时技术栈知识点，符合预期）。

### P3 · 点层粒度：把「章节名」变成「知识点」（大件，单独一批）

> 依据 `问题-点层粒度-2026-10-25.md`：条目=源文件、一文件一点、**只喂了开头 4,000 字**。
>
> **2026-10-26 成本测算结论（小样本已跑，全库待裁决）**：
> ① **不需要重抓**——`content_store` 里本来就有全文（Hello-Agents **674,468 字**、章节 **36,438 字**），
> 是 `_entry_body` 优先取 `inline_content`（`dbfile.py::_INLINE_CAP=4000` 的预览）才只看到 4,023 字；
> 修法是改取值优先级 + 分块，不是重新抓取。
> ② **分块抽取已有现成工具**：`tools/kpe`（`chunks/extract/review/stats`，4 并发、断点续跑、quote 校验），
> 入库走 `kpeimport`；本批不需要再在 `pipeline/points.py` 里另写一套切块。
> ③ 本轮实测（DeepSeek-V4.1-Flash、关思考、4 并发，¥2/M in + ¥8/M out）：

| 样本 | 规模 | 块数 | 实测（抽样） | 外推 |
|---|---|---|---|---|
| Hello-Agents（PDF 720 页） | 760,575 字 | 140 | 前 10 块 → **58 点**/1 拒，37,612+4,036 token，12.3s，¥0.11 | ≈**812 点**，¥1.5，~3 min |
| 5.智能体推理与规划（md） | 34,528 字 | 9 | 全跑 → **50 点**/0 拒，16,825+3,347 token，7.7s，¥0.06 | 同左 |
| **全库** | 30 条目 / 5,863,924 字 | ≈1,080 | 每块 ≈5.6 点、3,700 token in、400 out、1.2s | ≈**6,000 点**，≈4.0M+0.43M token，**≈¥11.6**，**≈22 分钟** |

> ④ **真正的成本不在抽取，在下游**：点数 1,579 → ≈6,000（4×）；P0 分诊 ≈300 批调用；
> P1 勘误按 hard 点**逐点**调用 ≈3,000 次（串行要十几小时），才是要裁的地方。
> 建议：先只导 3–5 本高价值书，P1 不自动跟进（要用时按需跑）；`kpeimport` 的 `--match` 支持逐本导。

- [x] **摸底**（2026-10-26）：确认全文在 `content_store`；`_entry_body` 优先级是「只看到 4,000 字」的真因；
      确认 KPE 工具链可用（两本书已有基线：65 块→385 点 / 69.8s；96 块→571 点 / ¥0.85 / 130s）。
- [x] `pipeline/points.py::_entry_body` 改为**取 inline 预览与 `content_store` 全文的较长者**（短文档行为不变）；
      正文 > `_BODY_CAP`（6,000）的长文**不再截断抽点**，落 `meta.points_pending_kpe` 交 `tools/kpe` 分块 + `kpeimport`；
      `kpeimport` 落地时清标记。块内抽点与跨块去重仍只在 kpe 一侧实现，管道不重复造轮子。
      **已实施（2026-10-26，工单 `变更工单-2026-10-26-P3点层取全文.md`）**：测试 616 passed / 1 skipped，
      canary 零漂移，真库 `kpoints --dry-run` 验证既有 4,552 点零扰动（`pending_kpe=0`）。
- [x] front matter 过滤：`kpe chunks` 已默认跳过前言/引言（`--keep-front` 关），落地时确认书名页/版权/目录未被抽点。
      **已核查（2026-10-26）：`FRONT_SECTIONS` 名下 0 点；`0.关于本书`（4,665 字）被正确丢弃。**
- [x] ~~**重抽全库**（用户裁决点）：实测 ≈¥11.6 / ≈22 分钟 / ≈6,000 点；建议先 3–5 本试点~~ ——
      **2026-10-26 核查后撤销**：全库已有 **4,552 点**（全部 `extractor=kpe`、带 `book`/`section_path`/`quote`，
      溯源 `char_offset` 最远 2,477,908 → 吃的是全文）；三本试点书（820/571/420）早已抽完。
      07:12 交接的「1,579 → 6,000（4×）」是把 **hard 子集** 当成了全库点数，属口径错误，不要据此重抽。
- 验收：`Hello-Agents`（674k 字整本）与 `5.智能体推理与规划`（36k 字章节）点数从 1 提到 ≥10 且无重复点；
      检索/词云/关系图的条目卡不再一篇一点。**真库已达（2026-10-26 核查）**：Hello-Agents **820 点**、
      `5.智能体推理与规划` **49 点**、AI-Agents-in-Depth **571 点**、agentic-design-patterns **420 点**；
      全库 4,552 点、`judge` 全为 `split`、点级检索已生效（`/api/search` 返回点优先）。
      **因此 P3 只剩 `_entry_body` 一项**（防未来新条目退化）。

### P4 · 点级图（wiki 式关联）——**已实施（2026-10-26）**

- [x] 点成为图节点：`kind=point`（id 前缀 `p:`），边来源四类——同书/同章节（`meta.book`+`section_path`）、
      同分类（溯源条目→分类）、语义近邻（点向量，已有 bge-m3）、引用/指涉（最贵，可后置）。
      落地：`db.radiate("p:<id>")` 四通道 `attach:` / `same_book:` / `same_section:` / `sim:`，
      每节点 `reasons[]`、每边 `reason`；引用/指涉按计划后置（见工单第 7 节）。
- [x] 聚焦视图：聚焦一个点 → 一跳邻域（沿用 `radiate` 的 `reasons[]`/`reason` 口径），支持「切焦点」下钻。
      落地：图页点节点点击即 `showRadiate("p:<id>")`，邻域点再点即下钻。
- [x] 初始层仍是分类 → 子分类 → 点（第三层由条目卡换成点卡）。
      落地：`/api/graph/subtree?layer=points`（默认 `entries` 保持旧行为）+ 图页「◆ 点层」开关
      （默认开、localStorage 记忆）；无点范围自动回退条目层并提示。
- 验收：任取一点，邻域 ≥5 且每条边有理由；点「切焦点」两次仍不空图。
      **真库验证（2026-10-26）**：`p:5c07508429801ddf` 邻域 18 节点 / 18 边、全部带理由，
      `same_book`/`same_section`/`sim`/`attach` 四通道齐全；连点两次切焦点均非空。
- 工单：`docs/design/变更工单-2026-10-26-P4点级图.md`；测试 `tests/test_graph_point_layer.py`（13 例）。
- 已知限制：引用/指涉通道**经实测判停**（2026-10-26）。
  **点级反查已补齐（2026-10-26）**：`reverse_reach("p:<id>")` 出溯源条目（`source:point`，带 `locator`）
  + 这些条目挂的分类（`attach:<origin>`，带 path），消费面闸门与 `radiate` 点焦点同源；
  对称边（同书/同章节/语义近邻）刻意不反向枚举。工单 `变更工单-2026-10-26-P4点级反查.md`。
- **引用/指涉负结果（2026-10-26 实测，避免重复调研）**：点正文 4,509 点中仅 **7 点（0.2%）** 出现任一
  引用形态、可解析到库内目标 **0**；条目正文层 29 条有正文（且被 4,023 字截断）里章节号命中全是**目录页**，
  URL 7 次 0 命中；原始语料 131 个 `.md` 中脚注 4 / 相对链接 9 / 参见 13。结论：本库（成书与白皮书，
  自包含）上照原计划实现会产出 0 条边，**不做**；启用门槛 = 候选点 ≥ 200 且可解析命中 ≥ 50 时再评估
  （判据写在 `变更工单-2026-10-26-P4点级图.md` §7）。探针：`temp/probe_cite_feasibility.py`、
  `temp/probe_cite_entries.py`。

### P5 · 扩散抓取加固（**已实施 2026-10-26**）

- [x] `_candidate_links` 过滤模板占位符（含 `${`）与解析后等于种子的项——实测廖雪峰教程页产出 4 条假链接。
      落地：占位符标记 `${` / `{{` / `<%` 在提取层剔除，自链接同样提取层剔除但仍按
      `already_known` 报账；`stats.filtered_placeholder` 计被剔的占位符数。
- [x] 索引页守卫：表格式书目页（`| 书名 | 作者 | [下载](…) |` 形态）判非知识，不进消费面——
      实测 `ebook-treasure-chest/md` 扩散进来的 20 条全是书目索引页（已批量舍弃）。
      落地：`semantic/value_guard.is_index_page`（四条件同时成立：表格成型 / 表头列名命中 ≥2 /
      数据行带链接 ≥50% / 表格占非空行 ≥40%，代码块内不统计）；扩散入库前拦（`stats.index_page`），
      `ksync --value-scan` 补判存量（`value_flag_reason="index_page"`，只读 `inline_content`、零额外 IO）。
      真库实测：49 条有正文条目中命中 20 条（全是那批书目页）、其余 0 误报。
- [x] 已知限制写进文档：扁平 ID 平台（知乎 `/p/`、掘金 `/post/`、简书 `/p/`、公众号 `/s/`）同目录≠同主题，
      扩散对这些源不适用。落地：`pipeline/expand.py` 模块 docstring「已知限制」+ 使用手册第 10 节第 5 条。

## 里程碑对照

| 里程碑 | 对应 Phase | 一句话判据 |
|---|---|---|
| M0.5 垂直切片 | 0.5 | 200 条真实链接跑通 kadd 全链路，10 大类经真实数据检验修订 |
| M1 最小可用 | 0 + 0.5 + 1 | 三源自带结构源接入，分类树可用可校正，kadd 可贴链接 |
| M2 内容层自洽 | 2 | 正文跨源只抓一次、双后端抓取、kadd 自动归类 |
| M3 全源接入 | 3 | 在线源（含 B站收藏夹）全部接入，凭证与限流故障处理有章可循 |
| M4 语义完备 | 4 | 三级分类流水线 + 三大视图全部可用 |
| M5 运维就绪 | 5 | 导出、备份、MCP 端点完成 |
| M6 高风险源 | 6 | 微信收藏链接路线 + 微信聊天记录以隔离方式纳入 |
| M7 知识模型升级 | 7 | 点层可溯源可去重（形态判定+去重），知识集组头信号化，老化有删除出口，勘误附注不改原文（方案定稿 v2，2026-10-21） |
| M8 数据源全覆盖 | 8 | 八类源接通且清洗前置；检索/关系图/词云只出知识聚合，不出文件名（2026-10-24 需求澄清） |
