"""CLI 子命令注册与参数解析（完整方案 §7；argparse，不引 click）。"""

# 拆分自 src/knowatlas/cli.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


import argparse
from .. import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="knowatlas",
        description="知道 KnowAtlas —— 个人知识统一索引与分类导航工具",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("kinit", help="初始化数据层：建表 + 注册内置能力 + 首条 run 记录")

    kadd = sub.add_parser("kadd", help="手动入口：贴 URL，自动 抓正文 → 归类 → 入树")
    kadd.add_argument("urls", nargs="+", metavar="URL")

    ksync = sub.add_parser("ksync", help="同步编排：书签等批量源 → 幂等入库 → 分类")
    ksync.add_argument("--full", action="store_true", help="全量遍历型源全量拉取")
    ksync.add_argument("--prune-missing", action="store_true",
                       help="旧删除检测（需配合 --full）：源里本次未见的 active 条目置 archived，"
                            "只标不删；默认不做——源消失只记 meta.source_state=missing，"
                            "收录的条目照常检索（2026-10-30 工单《收录与源脱节》）")
    ksync.add_argument("--incremental", action="store_true", help="游标型源增量")
    ksync.add_argument("--source", help="只同步指定源")
    ksync.add_argument("--dry-run", action="store_true", help="只探测源可达性，不写库")
    ksync.add_argument("--limit", type=int, default=None)
    ksync.add_argument("--fetch-limit", type=int, default=None,
                       help="显式开启本次抓取，最多 N 条（默认 on_sync=false 不抓；"
                            "候选只取 active，刚转正的排最前）")
    ksync.add_argument("--entry", action="append", metavar="ENTRY_ID", default=None,
                       help="定向补抓：只处理指定条目（可重复）——不看状态、默认抓正文，"
                            "且不归档（定向≠全量遍历，--full 在此模式下不生效）")
    ksync.add_argument("--reclassify", action="store_true",
                       help="对库中全部条目重跑分类（跳过人工校正过的；[llm] 启用且 key 已设时走 LLM 语义分类）")
    ksync.add_argument("--value-scan", action="store_true",
                       help="价值体检：纯规则标记非知识内容（资源直链/站点首页/列表子页），零费用、不动分类树；配合 --dry-run 只出报告")
    ksync.add_argument("--dedupe-scan", action="store_true",
                       help="跨源去重存量扫描：canonical/正文 hash 完全一致的条目合并为一条（主条目保留全部 locator 可跳转，副条目隐藏、可逆）；配合 --dry-run 只出报告")
    ksync.add_argument("--freshness-scan", action="store_true",
                       help="时效体检：纯规则标记过期/疑似过旧的知识（废弃关键词/正文日期过旧/同主题新旧并存），只标不删、可否决；配合 --dry-run 只出报告")
    ksync.add_argument("--errata-scan", action="store_true",
                       help="勘误 L1 体检：纯规则确定性错误扫描（完整 Python 代码块语法验证/已移除 API 对照表），只标不删、可否决；配合 --dry-run 只出报告")
    ksync.add_argument("--purge-source", metavar="SOURCE", default=None,
                       help="全删重灌第一步：物理删除指定源全部条目（含 archived/rejected，FK 级联"
                            "+ content_store 引用计数回收 + task_log 留痕）后接着同步该源；"
                            "先快照后删除（快照失败自动中止）；配合 --dry-run 只探测不删除")
    ksync.add_argument("--purge-reason", metavar="REASON", default="reingest",
                       help="purge 留痕原因标记（默认 reingest；emmx 重灌用 emmx_rebuild）")
    ksync.add_argument("--expand", metavar="ENTRY_ID", default=None,
                       help="书签扩散抓取（显式触发）：对指定书签/http 条目抓取其同目录系列页（同一目录页同一主题）")
    ksync.add_argument("--expand-limit", type=int, default=20,
                       help="扩散每轮最多新建条数（默认 20）")
    ksync.add_argument("--embed", action="store_true",
                       help="构建/增量更新条目向量索引（M4，需 [embedding] + optional 依赖）")
    ksync.add_argument("--embed-force", action="store_true",
                       help="重算全部向量（换模型后用）")
    ksync.add_argument("--cluster-report", action="store_true",
                       help="暂存区条目聚类 + LLM 命名候选报告（不建类，人工确认后生效）")

    serve = sub.add_parser("serve", help="启动本地 Web 服务（默认 127.0.0.1:8420）")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    kexport = sub.add_parser("kexport", help="数据导出（json|obsidian|opml）—— M5")
    kexport.add_argument("--format", default="json")
    kexport.add_argument("--out", required=True)

    kbackup = sub.add_parser("kbackup", help="快照与恢复（VACUUM INTO）—— M5")
    kbackup.add_argument("--snap", action="store_true", help="立即快照 + 轮换")
    kbackup.add_argument("--restore", metavar="FILE", help="从快照恢复（恢复前自动安全网快照）")
    kbackup.add_argument("--verify", metavar="FILE", help="恢复演练验证：integrity_check + 条目数")
    kbackup.add_argument("--keep", type=int, default=None, help="轮换保留份数（默认配置 backup_keep=10）")
    kbackup.add_argument("--no-throttle", action="store_true", help="忽略节流，强制快照")

    ktest = sub.add_parser("ktest", help="回归集 / 契约金丝雀运行器")
    ktest.add_argument("what", choices=["regress", "canary"])
    ktest.add_argument("--seed-from-log", action="store_true",
                       help="（regress）先把历史 recategorize 改类动作回填进回归集再跑")
    ktest.add_argument("--dry-run", action="store_true",
                       help="（regress --seed-from-log）只统计回填规模，不写库")

    kcheck = sub.add_parser("kcheck", help="库体检：链接可达性（404/410 标记 dead）"
                                            " / 正文库孤儿回收（--gc-content）")
    kcheck.add_argument("--limit", type=int, default=100, help="本次最多检测条数（默认 100）")
    kcheck.add_argument("--qps", type=float, default=4.0, help="检测速率（默认 4 条/秒）")
    kcheck.add_argument("--gc-content", action="store_true",
                        help="回收无条目引用的正文块（content_store 孤儿；不联网、"
                             "不动条目/点/向量，正文可重抓）")
    kcheck.add_argument("--gc-days", type=float, default=1.0,
                        help="（--gc-content）只回收抓取时间早于 N 天的孤儿正文"
                             "（默认 1；阈值防同步进行中的竞态）")
    kcheck.add_argument("--dry-run", action="store_true",
                        help="（--gc-content）只统计不删除")

    kpoints = sub.add_parser(
        "kpoints", help="知识点抽取：规则判定（文学创作=split 切点，其余 integral 整条即点，"
                        "用户口径 2026-10-22）→ hash 去重一点多溯源")
    kpoints.add_argument("--limit", type=int, default=None,
                         help="本次最多处理条数（抽取默认 10；--triage 默认不限；"
                              "--limit 0 仅 purge）")
    kpoints.add_argument("--dry-run", action="store_true",
                         help="只判定与报告，不写库（split 切点的 LLM 费用照常发生）")
    kpoints.add_argument("--entry", action="append", metavar="ENTRY_ID", default=None,
                         help="定向补抽：只抽指定条目（可重复）。注意沿用批次 70 语义——"
                              "跳过游标、会重新调用 LLM（点 hash 相同只归并溯源，不重复建点）；"
                              "想先看费用用 --dry-run")
    kpoints.add_argument("--purge-points", action="store_true",
                         help="先清空点层（points/point_sources）再抽取——形态判定口径"
                              "变更后的推倒重来；条目与原文零影响")
    kpoints.add_argument("--retry-blocked", action="store_true",
                         help="把被自洽性闸门拦下的条目（meta.points_gate）清标记后"
                              "重抽——口径/prompt 调整后的重试入口")
    kpoints.add_argument("--triage", action="store_true",
                         help="点分诊（P0）：给点打 kind=hard|opinion|unjudgeable|dupe，"
                              "落 meta；后续勘误/老化只吃 hard（领域闸门）。幂等，"
                              "已有 kind 的跳过")
    kpoints.add_argument("--from-json", metavar="PATH", default=None,
                         help="--triage 时导入既有分诊产物（{point_id:{kind,why}}，零 LLM 费）；"
                              "推荐的默认种子：temp/errata_full_triage.json")

    kaging = sub.add_parser(
        "kaging", help="老化三级：L2 LLM 复核 suspect（升级 stale/否决/下沉人裁）；"
                       "--sweep 执行冷却期满删除出口（方案 §7.5）")
    kaging.add_argument("--limit", type=int, default=None,
                        help="本次最多复核条数（条目/点级默认 10=试跑口径，全量须用户裁决；"
                             "--lifecycle 默认不限=全库）")
    kaging.add_argument("--dry-run", action="store_true",
                        help="只判定与报告，不写库（LLM 费用照常发生；--sweep 时只出删除报告）")
    kaging.add_argument("--sweep", action="store_true",
                        help="执行删除出口清扫：冷却期满（30 天）的 rejected 条目物理删除"
                             "+ content_store 引用计数回收（审计留痕）；默认每轮 ksync 自动执行")
    kaging.add_argument("--points", action="store_true",
                        help="点级老化 L2（批次 93，裁决 #14）：对溯源条目被标"
                             " suspect/stale 的点逐点复核——条目过时不连坐点，"
                             "确证过时的点退出消费面（溯源条目保留，永不物理删除）")
    kaging.add_argument("--lifecycle", action="store_true",
                        help="点级老化两型（P2）：版本型按官方 EOL 表确定性判（零 LLM）+ "
                             "退场型按技术栈 LLM 判（必附官方依据否则 keep）；只吃 kind=hard，"
                             "stale 退出消费面，只标不删；幂等（meta.lifecycle.at 游标）")

    kerrata = sub.add_parser(
        "kerrata", help="勘误三级：--scan 跑 L1 确定性错误扫描（零费用）；"
                        "--points 跑点级事实核查（P1，只吃 kind=hard）；"
                        "默认跑 L2 带依据核查（方案 §7.6）")
    kerrata.add_argument("--limit", type=int, default=None,
                         help="本次最多核查条数（条目 L2 默认 10=试跑口径；--points 默认不限）")
    kerrata.add_argument("--dry-run", action="store_true",
                         help="只判定与报告，不写库（LLM 费用照常发生；--scan 时只出报告）")
    kerrata.add_argument("--scan", action="store_true",
                         help="跑 L1 确定性错误扫描（完整 Python 代码块语法验证 + 已移除"
                              " API 对照表，零费用；同 ksync --errata-scan）")
    kerrata.add_argument("--points", action="store_true",
                         help="点级事实核查（P1）：hard 点判 wrong/suspect/ok，结论落"
                              " point.meta.fact_check；wrong 进 /api/errata/points 队列，"
                              "suspect 只进筛选视图；只标不删、幂等")
    kerrata.add_argument("--from-json", metavar="PATH", default=None,
                         help="--points 时回放既有核查产物（{point_id:{verdict,reason,evidence}}，"
                              "零 LLM 费）；推荐的默认种子：temp/errata_full_verify.json")
    kerrata.add_argument("--backfill-codes", action="store_true",
                         help="--points 时只回填原因码（P1b）：给已判 wrong 但 reason_code "
                              "为空的点补 fact_error/overclaim，不重判 verdict/reason/evidence；"
                              "幂等，与 --from-json 互斥")

    kpeimport = sub.add_parser(
        "kpeimport", help="导入 KPE 长文抽取产物（manifest.json + points.jsonl）到点层"
                          "（变更工单-2026-10-25-KPE导入适配器）")
    kpeimport.add_argument("out_dir", metavar="OUT_DIR",
                           help="kpe --out 目录（含 manifest.json / points.jsonl）")
    kpeimport.add_argument("--entry", dest="entry_id", metavar="ENTRY_ID",
                           help="目标条目 id（最稳；不给则按 manifest.book 精确匹配标题）")
    kpeimport.add_argument("--match", metavar="PATTERN",
                           help="按标题/locator 通配匹配条目（必须唯一命中）")
    kpeimport.add_argument("--replace", action="store_true",
                           help="先清该条目的旧点溯源（孤儿点一并删、共享点保留）再导入")
    kpeimport.add_argument("--dry-run", action="store_true", help="只算账不写库")
    kpeimport.add_argument("--no-backup", action="store_true", help="跳过写库前快照")
    kpeimport.add_argument("--limit", type=int, default=0, help="最多导入 N 个点（调试用）")

    kauto = sub.add_parser(
        "kauto", help="入库即处理（工单 2026-10-27）：待审激活 → 补抓正文 → 按类型分流抽点"
                      "（管道/KPE）→（到点）自动老化。serve 内置同名巡检线程，本命令是无界面等价物")
    kauto.add_argument("--dry-run", action="store_true", help="只出计划不写库/不烧 LLM")
    kauto.add_argument("--limit", type=int, default=None,
                       help="本轮总条数上限（缺省 [ingest] max_entries_per_run；0=不限）")
    kauto.add_argument("--activate-only", action="store_true",
                       help="只跑待审激活（L0 守门 → 拒绝/转正），不抓不抽")
    kauto.add_argument("--no-aging", action="store_true", help="本轮不跑老化")
    kauto.add_argument("--no-activate", action="store_true", help="本轮不做待审激活")

    return parser
