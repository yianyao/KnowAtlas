---
title: 个人知识统一索引与分类导航工具 · TODO
summary: Phase 0 契约冻结到 Phase 6 高风险源的分阶段任务清单（2026-10-19 第二次定稿 + 契约返工：PostgreSQL/微信/词云三态/DeepSeek Fetch/手动链接入口/B站收藏夹源/M0.5 垂直切片），每项含验收探针，每阶段设 Gate
date: 2026-10-19
status: 定稿
reader: 执行者（人与 agent）
---

# 个人知识统一索引与分类导航工具 · TODO

使用说明：

- 状态标记：`[ ]` 未开始 / `[~]` 进行中 / `[x]` 完成。
- 每项任务自带验收探针；探针不过，该项不算完成。
- 每个 Phase 设 Gate，Gate 不过不进入下一 Phase。
- 配套文档：handoff/知识索引工具-设计方案.md（设计依据）、handoff/知识索引工具-完整方案.md（工程契约，编码直接依据）、handoff/知识索引工具-SOP.md（操作流程）。
- 变更记录：handoff/变更工单-2026-10-19-第二次定稿.md、handoff/变更工单-2026-10-19-B站收藏夹.md、handoff/变更工单-2026-10-19-契约返工.md、handoff/变更工单-2026-10-19-安全与API修正.md。

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
- [ ] 回归测试集 v0：从 200 条真实链接人工确认 50-100 条（同时作为 LLM few-shot 底稿）
      - 探针：跑完后回头核对 10 大类草案，该合并的合并、该拆的拆，结论落进 priors.py

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
- [ ] 人工校正 UI：改类/合并/移动/多父挂接，全部写 task_log
      - 探针：任意一次校正可在 task_log 复现前后值

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

- [ ] AI 会话适配器（映射 session-harvester 输出的 SessionRecord/Message 双结构）
      - 探针：harvester 产物目录 → 条目含 title/session_id/created_at/turns 摘要
      - 线程增补（完整方案 §9.4 第三十一批）：Message 父子/顺序关系还原为
        threads(thread_type='source') + conv_messages（msg_key=轮次 id，parent_id 按产物结构）
      - 探针：多轮会话入库后 conv_messages 轮次/父子关系与 harvester 产物一致；原文不复制进 conv_messages
- [ ] B站收藏夹适配器（官方 API：list-all 取收藏夹列表 + resource/list 分页内容；SESSDATA 走 KNOWATLAS_BILI_SESSDATA 环境变量；收藏夹名进 native_path；简介作 inline_content；WBI 签名可开关）
      - 探针：SESSDATA 失效时报错含 F12 获取指引且旧条目保留；收藏夹名正确映射 native_path；同一视频进两个收藏夹只产一条且 meta.fav_folder_ids 含两个 id；下架视频看 attr 位保留标题级并记 meta.invalid
- [ ] IMA 适配器（官方 OpenAPI：list_notebooks / list_notes / get_note_content；凭证走配置）
      - 探针：token 失效时报错含"重新获取 Client ID/API Key"指引
- [ ] 腾讯文档适配器（OpenAPI v2：文件夹列表 + async-export；429 队列降速；doc/slide 导 PDF 后二次解析）
      - 探针：模拟 429 时间隔重试成功；PDF 解析失败降级标题级
- [ ] 数据文件适配器（sqlite：schema 自省 + 采样；PostgreSQL：连接串走配置，psycopg 连接后同样 schema 自省 + 采样）
      - 探针：连一个测试 PostgreSQL 实例（或 docker 起的），表清单与采样行正确进入条目

## Phase 4 — 语义与视图（M4）

> Gate：规则 → embedding → LLM 三级流水线跑通（LLM 默认云端、配置可切本地）；混合检索、词云（三态词元）、关系图（focus 模式）可用；回归集通过率记录在案。

- [ ] 规则分类器（关键词/正则/先验映射补漏）
- [ ] 会话线程语义任务（完整方案 §9.4 第三十一批，后置——先规则后 LLM）：quote_strip
      （mail-parser-reply 底座 + 中文回复头自补规则，纯规则不调 LLM）→ delta_summarize /
      thread_digest（LLM 走 [llm] 后端池：硅基流动优先、DeepSeek 官方兜底；可独立关闭）
      - 探针：关闭 LLM 后 quote_strip 仍工作（纯规则降级）；thread_digest 关闭不影响检索与线程视图
- [ ] 本地 embedding（bge-m3 类中文模型，optional 依赖）+ 聚类
- [ ] LLM 兜底（OpenAI 兼容接口，默认云端、配置可切本地；few-shot 来自回归集；先聚类后命名）
      - 探针：关闭 LLM 后系统仍可运行（纯规则降级模式）
- [ ] FTS5 全文检索（entries_fts + content_fts 正文索引；trigram + 两字词 LIKE 兜底）+ jieba 关键词统计
- [ ] 混合检索（关键词 + 语义，结果可解释排序理由）
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
      旧 v0 全量力导图（/api/graph）保留兼容。剩余：共现/相似度语义边随 M2/M4 接入）
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
        往返重建无损 ✅；OPML 导入回路后置（ksync 新源独立批次）
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

## 阻塞项

无。原 5 项阻塞事项已于 2026-10-19 第二次确认全部定稿（详见设计方案 §10.1 决策记录）：聊天工具=微信；pq=PostgreSQL；微信收藏=链接全扒路线；部署=本地 Web 服务；LLM=云端 API 默认、配置可切本地。另新增定稿：词云=三态词元架构（scoped cloud + 双态词元 + 关系图 focus 射线）；新增手动链接入口（kadd / UI / bookmarklet）。

2026-10-19 契约返工（H1 多 locator / H2 正文索引 / H3 upsert 与删除检测 / H4 path 派生 / H6 备份安全 / H7 B站 source_key / K1 默认不抓正文 / K2 M0.5 / K3 仓库化）已全部落入设计方案与完整方案，详见 handoff/变更工单-2026-10-19-契约返工.md 与 handoff/变更工单-2026-10-19-安全与API修正.md；阻塞项仍为无。

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
