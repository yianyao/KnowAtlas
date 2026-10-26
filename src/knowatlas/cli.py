"""CLI 子命令注册与参数解析（完整方案 §7；argparse，不引 click）。"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import load_config
from .datalayer.db import DataLayer
from .errors import KnowAtlasError
from .logging_setup import setup_logging
from .registry.builtins import build_registries

_EXIT_OK, EXIT_BUSINESS, _EXIT_USAGE, _EXIT_SKIP = 0, 1, 2, 3  # SKIP 计退出码，不伪装通过


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
    ksync.add_argument("--incremental", action="store_true", help="游标型源增量")
    ksync.add_argument("--source", help="只同步指定源")
    ksync.add_argument("--dry-run", action="store_true", help="只探测源可达性，不写库")
    ksync.add_argument("--limit", type=int, default=None)
    ksync.add_argument("--fetch-limit", type=int, default=None,
                       help="显式开启本次抓取，最多 N 条（默认 on_sync=false 不抓）")
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

    return parser


def _open(cfg) -> DataLayer:
    dl = DataLayer(cfg.db_path)
    dl.init_schema()
    return dl


def _cmd_kinit(args: argparse.Namespace) -> int:
    cfg = load_config()
    log = setup_logging(cfg.log_level)
    dl = _open(cfg)
    locators, semantics = build_registries(cfg)
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "kinit")
    dl.finish_run(run_id, {
        "capabilities": [s.name for s in (*locators.specs(), *semantics.specs())],
    })
    dl.close()
    log.info("数据层初始化完成", extra={"component": "cli", "run_id": run_id,
                                       "db": str(cfg.db_path)})
    print(f"OK 初始化完成：{cfg.db_path}（能力 {len(list(locators.specs()) + list(semantics.specs()))} 个）")
    return _EXIT_OK


def _cmd_kadd(args: argparse.Namespace) -> int:
    from .pipeline.kadd import ingest_url

    cfg = load_config()
    setup_logging(cfg.log_level)
    _warn_if_llm_unavailable(cfg, "kadd")
    dl = _open(cfg)
    locators, semantics = build_registries(cfg)
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "kadd")
    exit_code = _EXIT_OK
    try:
        for url in args.urls:
            summary = ingest_url(cfg, dl, locators, semantics, url, run_id)
            flag = "已存在（canonical 命中）" if summary["status"] == "duplicate" else "已收录"
            fetch_note = "" if summary["fetched"] else "（未抓到正文，暂存区）"
            cat_note = "已归类" if summary["categorized"] else "未归类"
            print(f"OK [{flag}/{cat_note}{fetch_note}] {url} -> {summary['entry_id']}")
            if summary.get("fetch_error"):
                print(f"   抓取失败：{summary['fetch_error']}")
    finally:
        dl.finish_run(run_id, {"urls": len(args.urls)})
        dl.close()
    return exit_code


def _cmd_ksync(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg.log_level)
    _warn_if_llm_unavailable(cfg, "ksync")
    dl = _open(cfg)
    locators, semantics = build_registries(cfg)
    try:
        if args.embed or args.embed_force:
            from .semantic.embed import from_config as embedder_from_config
            from .pipeline.embed_index import dedup_points, embed_entries, embed_points

            embedder = embedder_from_config(cfg)
            if embedder is None:
                print("SKIP 向量索引未启用（[embedding] enabled=true 且安装"
                      " requirements-optional）——主链路不受影响")
                return _EXIT_SKIP
            stats = embed_entries(dl, embedder, force=args.embed_force)
            pstats = embed_points(dl, embedder, force=args.embed_force)
            dstats = dedup_points(dl)  # 批次 94：向量就绪后语义去重（可逆标记）
            print(f"OK 向量索引完成：条目 {stats} | 点 {pstats} | 去重 {dstats}")
            return _EXIT_OK
        if args.cluster_report:
            from .semantic.embed import from_config as embedder_from_config
            from .semantic.llm import LlmClient
            from .pipeline.embed_index import cluster_report

            embedder = embedder_from_config(cfg)
            if embedder is None:
                print("SKIP 聚类报告需要向量索引（先 ksync --embed）")
                return _EXIT_SKIP
            report = cluster_report(dl, embedder, LlmClient.from_config(cfg))
            import json as _json

            print(_json.dumps(report, ensure_ascii=False, indent=2))
            print("—— 候选报告仅供参考，不自动建类；确认后用改类 UI 挂接。")
            return _EXIT_OK
        if args.expand:
            from .pipeline.expand import expand_seed

            stats = expand_seed(cfg, dl, locators, semantics,
                                args.expand, limit=args.expand_limit)
            print(f"OK 扩散完成：{stats}")
            return _EXIT_OK
        from .pipeline.sync import run_sync

        stats = run_sync(cfg, dl, locators, semantics, full=args.full,
                         source=args.source, dry_run=args.dry_run,
                         limit=args.limit, fetch_limit=args.fetch_limit,
                         reclassify=args.reclassify, value_scan=args.value_scan,
                         dedupe_scan=args.dedupe_scan,
                         freshness_scan=args.freshness_scan,
                         errata_scan=args.errata_scan,
                         purge_source=args.purge_source,
                         purge_reason=args.purge_reason)
    finally:
        dl.close()
    print(f"OK 同步完成：{stats}")
    return _EXIT_OK


def _apply_serve_overrides(cfg, host: str, port: int) -> None:
    """把 serve 实际监听的 host/port 回写进 cfg（R8，2026-10-24 对账修复）。

    为什么必须回写：安全中间件的 Host 白名单是按 ``cfg.general.server_port`` 生成的
    （web/api.py::install_security_middleware），而 ``serve --port 9000`` 只改 uvicorn
    的监听端口、不动 cfg —— 浏览器访问 http://127.0.0.1:9000 会带 Host: 127.0.0.1:9000，
    不在白名单内，直接被 FORBIDDEN_HOST 拒掉（表现为"换了端口就打不开"）。
    桌面壳 desktop/main.py 早就是同口径（create_app 之前覆盖 cfg 值），CLI 这条补齐。
    """
    general = cfg.raw.setdefault("general", {})
    general["server_host"] = host
    general["server_port"] = int(port)


def _warn_if_llm_unavailable(cfg, command: str) -> None:
    """R10：LLM 声明启用却读不到任何 key —— 语义层会静默降级，必须显式告知。

    真实踩坑（2026-10-24 样本验证）：key 配在用户级环境变量，进程早于 `setx` 启动
    读不到，`kpoints` 安安静静产出「整篇 4023 字 integral」点、split 文档归零，
    用户与 agent 都看不出"其实没连上 LLM"。降级本身可以接受，**沉默**不行。
    """
    if not bool(cfg.get("llm.enabled", False)):
        return
    names: list[str] = []
    for backend in cfg.get("llm.backends", []) or []:
        if isinstance(backend, dict):
            names.extend(str(backend.get("api_key_env", "")).split(","))
    ordered = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    if not ordered:
        ordered = ["KNOWATLAS_LLM_API_KEY"]
    if any(os.environ.get(name) for name in ordered):
        return
    print(f"WARN 语义层降级：{command} 需要 LLM，但 [llm] enabled=true 且这些环境变量全为空"
          f"（{'/'.join(ordered)}）——分类停在规则级、点抽取退化为「整篇照抄 integral」、"
          "split 文档归零。配好 key 后重跑即可。")


def _cmd_serve(args: argparse.Namespace) -> int:
    import secrets

    cfg = load_config()
    host = args.host or str(cfg.get("general.server_host", "127.0.0.1"))
    port = int(args.port or cfg.get("general.server_port", 8420))
    _apply_serve_overrides(cfg, host, port)
    setup_logging(cfg.log_level)
    _warn_if_llm_unavailable(cfg, "serve")
    dl = _open(cfg)
    locators, semantics = build_registries(cfg)
    from .web.app import create_app

    # 写令牌：未设时自动生成本次会话令牌（体验优化 0.2.0：免用户自造密码；
    # 安全不降级——token 仍必填，仅由工具代生成。H5 第 3 条约束不变）
    token_env = str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN"))
    token = os.environ.get(token_env, "")
    auto_generated = False
    if not token:
        token = secrets.token_urlsafe(16)
        os.environ[token_env] = token
        auto_generated = True

    app = create_app(cfg, dl, locators, semantics)
    import uvicorn

    print(f"KnowAtlas 服务：http://{host}:{port}")
    from .web.api import token_fingerprint
    if auto_generated:
        print(f"本次会话写令牌（写操作时在网页弹窗粘贴一次即可）：{token}")
        print(f"令牌指纹：{token_fingerprint(token)}（核对用）")
        print(f"如需固定令牌，请设置环境变量 {token_env} 后重启 serve")
    else:
        print(f"写令牌：来自环境变量 {token_env}，指纹 {token_fingerprint(token)}")
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        dl.close()
    return _EXIT_OK


def _cmd_kexport(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .config import load_config
    from .pipeline import export as export_mod

    cfg = load_config()
    setup_logging(cfg.log_level)
    dl = _open(cfg)
    try:
        out = Path(args.out)
        if args.format == "json":
            stats = export_mod.export_json(dl, out)
        elif args.format == "obsidian":
            stats = export_mod.export_obsidian(dl, out)
        elif args.format == "opml":
            stats = export_mod.export_opml(dl, out)
        else:
            print(f"ERROR 未知格式：{args.format}（支持 json|obsidian|opml）")
            return EXIT_BUSINESS
    finally:
        dl.close()
    print(f"OK 导出完成：{stats}")
    if args.format == "json":
        print("（inline_content 已内联；content_store 全量正文未内联——"
              "需要完整正文请自行拷贝 content_store 目录）")
    return _EXIT_OK


def _cmd_kbackup(args: argparse.Namespace) -> int:
    from .pipeline.backup import restore as _restore
    from .pipeline.backup import snapshot as _snapshot
    from .pipeline.backup import verify_snapshot as _verify

    cfg = load_config()
    setup_logging(cfg.log_level)

    if args.verify:
        v = _verify(Path(args.verify))
        print(f"{'OK' if v['ok'] else 'ERROR'} 快照验证：{v}")
        return _EXIT_OK if v["ok"] else EXIT_BUSINESS

    if args.restore:
        # restore 自包含：内部先做安全网快照、再 close、换文件、sanity 对账
        dl = _open(cfg)
        r = _restore(cfg, dl, Path(args.restore))
        print(f"{'OK' if r['ok'] else 'ERROR'} 恢复：{r}")
        if r["ok"]:
            print("提示：原库已自动快照留底（安全网），确认恢复无误后可手动清理旧快照。")
        return _EXIT_OK if r["ok"] else EXIT_BUSINESS

    # 默认/--snap：立即快照 + 轮换
    dl = _open(cfg)
    try:
        stats = _snapshot(cfg, dl, keep=args.keep if args.keep is not None else cfg.backup_keep,
                          min_interval_hours=0 if args.no_throttle else cfg.backup_min_interval_hours,
                          force=args.no_throttle)
    finally:
        dl.close()
    if stats.get("status") == "skipped":
        print(f"SKIP 节流跳过（{stats['reason']}，最新快照 {stats['latest']}，"
              f"{stats['age_hours']}h 前）；--no-throttle 可强制")
        return _EXIT_OK
    print(f"OK 快照完成：{stats}（目录 {cfg.backup_dir}）")
    return _EXIT_OK


def _cmd_ktest(args: argparse.Namespace) -> int:
    if args.what == "canary":
        # 契约金丝雀 = tests/test_canary.py（DDL/dataclass/scheme/config 键集
        # 漂移即红）；转交 pytest，退出码透传
        import subprocess
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/test_canary.py",
                            "-q", "--tb=short"], cwd=repo)
        return _EXIT_OK if r.returncode == 0 else EXIT_BUSINESS

    # ktest regress：回归集报告（v0 只验证 L1/L2 规则层，零 LLM 费用）
    from .config import load_config
    from .pipeline.regress import run_regress, seed_from_log

    cfg = load_config()
    setup_logging(cfg.log_level)
    dl = _open(cfg)
    try:
        if args.seed_from_log:
            stats = seed_from_log(dl, dry_run=args.dry_run)
            print(f"OK 回填统计：{stats}")
            if args.dry_run:
                return _EXIT_OK
        report = run_regress(dl, cfg)
    finally:
        dl.close()
    if report["total"] == 0:
        print("SKIP 回归集为空——在 Web UI 条目行点「✓」确认归类，"
              "或用 ktest regress --seed-from-log 从历史改类回填")
        return _EXIT_OK
    print(f"OK 回归报告：{report['total']} 案例 | exact {report['exact']}"
          f"（{report['exact_rate']:.1%}）| prefix {report['prefix']}"
          f"（累计方向正确 {report['prefix_rate']:.1%}）| miss {report['miss']}")
    for r in report["prefixes"][:10]:
        print(f"  PREFIX  {r['title'][:40]}  期望 {r['expected']} → 实际 {r['actual']}")
    for r in report["misses"][:10]:
        print(f"  MISS    {r['title'][:40]}  期望 {r['expected']}"
              f" → {r['actual'] or '（无输出/' + r['origin'] + '）'}")
    shown = len(report["misses"]) + len(report["prefixes"])
    if shown > 20:
        print(f"  …其余 {shown - 20} 条明细见全量输出（--verbose 后续批扩展）")
    return _EXIT_OK


def _cmd_kcheck(args: argparse.Namespace) -> int:
    from .pipeline.health import run_health_check

    cfg = load_config()
    setup_logging(cfg.log_level)
    if args.gc_content:
        dl = _open(cfg)
        try:
            stats = dl.gc_orphan_contents(max_age_days=args.gc_days,
                                          dry_run=args.dry_run)
        finally:
            dl.close()
        head = "OK 试跑完成（dry-run 未删除）" if args.dry_run else "OK 正文库回收完成"
        print(f"{head}：孤儿 {stats['candidates']} 行 / 可回收 {stats['eligible']} 行 / "
              f"已删 {stats['deleted']} 行 / 释放 {stats['freed_chars']:,} 字符"
              f"（阈值 {stats['max_age_days']} 天，过新跳过 {stats['skipped_recent']} 行）")
        return _EXIT_OK
    _warn_if_llm_unavailable(cfg, "kcheck")
    dl = _open(cfg)
    try:
        stats = run_health_check(cfg, dl, limit=args.limit, qps=args.qps)
    finally:
        dl.close()
    print(f"OK 体检完成：{stats}（dead=永久失效，error=疑似临时故障；"
          f"Web UI「失效链接」视图可批量舍弃）")
    return _EXIT_OK


def _cmd_kpoints_triage(cfg, args: argparse.Namespace) -> int:
    """P0 点分诊：dupe 标记 + 种子导入（零 LLM）+ 新点 LLM 增量，幂等落 meta.kind。"""
    import json as _json

    from .pipeline.triage import run_point_triage

    limit = 0 if args.limit is None else max(0, args.limit)
    seed = args.from_json
    if not seed:
        default_seed = Path("temp/errata_full_triage.json")
        if default_seed.exists():
            print(f"提示：检测到既有分诊产物 {default_seed.as_posix()}，加 "
                  f"--from-json {default_seed.as_posix()} 可零 LLM 费导入")
    dl = _open(cfg)
    try:
        stats = run_point_triage(cfg, dl, limit=limit, dry_run=args.dry_run,
                                 seed_path=seed)
    finally:
        dl.close()
    written = stats["imported"] + stats["dupes_marked"] + stats["triaged"]
    if stats.get("llm_skipped") and not written:
        print(f"SKIP {stats['llm_skipped']}")
        return _EXIT_SKIP
    head = "OK 试跑完成（dry-run 未写库）" if args.dry_run else "OK 分诊完成"
    summary = {k: v for k, v in stats.items() if k != "errors"}
    print(f"{head}：{_json.dumps(summary, ensure_ascii=False)}")
    for err in stats.get("errors", [])[:5]:
        print(f"  ERROR {err}")
    if stats.get("llm_skipped"):
        print(f"  WARN {stats['llm_skipped']}")
    if not args.dry_run:
        print("（领域闸门：勘误/老化只吃 kind=hard；声明在 pipeline/triage.py::is_hard；"
              "重跑幂等，已有 kind 的点不会重判）")
    return _EXIT_OK


def _cmd_kpoints(args: argparse.Namespace) -> int:
    from .pipeline.points import run_points_extract

    cfg = load_config()
    setup_logging(cfg.log_level)
    limit = 10 if args.limit is None else args.limit
    if args.triage:
        if args.purge_points or args.retry_blocked:
            print("ERROR --triage 不能与 --purge-points / --retry-blocked 同用"
                  "（清点/重抽请单独跑）")
            return _EXIT_USAGE
        return _cmd_kpoints_triage(cfg, args)
    _warn_if_llm_unavailable(cfg, "kpoints")
    dl = _open(cfg)
    try:
        if args.purge_points:  # 口径变更推倒重来（2026-10-22）：只清点层，原文零影响
            n = dl.purge_points(reason="用户口径变更：文学创作=split，其余 integral"
                                       "（规则判定取代 LLM 判定）")
            print(f"OK 点层已清空：{n} points（points/point_sources；条目零影响）")
            if limit == 0:
                return _EXIT_OK
        stats = run_points_extract(cfg, dl, limit=max(1, limit),
                                   dry_run=args.dry_run,
                                   retry_blocked=args.retry_blocked)
    finally:
        dl.close()
    if stats.get("skipped"):  # 仅 LLM 未启用时存在（str）；跳过计数器在 skip_counts
        print(f"SKIP {stats['skipped']}")
        return _EXIT_SKIP
    import json as _json

    head = "OK 试跑完成（dry-run 未写库）" if args.dry_run else "OK 抽取完成"
    print(f"{head}：{_json.dumps(stats, ensure_ascii=False)}")
    for err in stats.get("errors", [])[:5]:
        print(f"  ERROR {err['entry_id']} {err['title']}：{err['error']}")
    if stats.get("points_rejected") or stats.get("gate_blocked"):
        reasons = "、".join(f"{k}×{v}" for k, v in
                            (stats.get("reject_reasons") or {}).items())
        print(f"  GATE 拦下 {stats.get('points_rejected', 0)} 点（{reasons or '无明细'}）；"
              f"整条阻断 {stats.get('gate_blocked', 0)} 条"
              f"（meta.points_gate；改口径后用 --retry-blocked 重抽）")
    if stats.get("pending_kpe"):
        detail = "、".join(f"{d['title']}（{d['chars']:,} 字）"
                          for d in stats.get("pending_kpe_detail", [])[:5])
        print(f"  PENDING {stats['pending_kpe']} 条正文超管道上限"
              f"（meta.points_pending_kpe）：{detail}")
        print("    这些长文不截断抽点；用 kpe 分块后导入：")
        print("      uv run python -m kpe chunks <源文件> --out temp/kpe-<名>")
        print("      uv run python -m kpe extract temp/kpe-<名> --base-url <url>"
              " --model <model> --api-key-env <KEY_ENV>")
        print('      uv run python -m knowatlas kpeimport temp/kpe-<名> --match "<书名通配>"')
    if not args.dry_run:
        print("（点列表：points 表；溯源数=可信度信号；判定理由在点 meta.judge_reason）")
    return _EXIT_OK


def _cmd_kaging(args: argparse.Namespace) -> int:
    import json as _json

    from .pipeline.aging import run_aging_judgment, sweep_rejections

    if args.lifecycle and (args.points or args.sweep):
        print("ERROR --lifecycle 不能与 --points/--sweep 同用（三者入口不同，分开跑）")
        return _EXIT_USAGE
    cfg = load_config()
    setup_logging(cfg.log_level)
    limit = 10 if args.limit is None else max(1, args.limit)
    dl = _open(cfg)
    try:
        if args.lifecycle:
            from .pipeline.lifecycle import run_lifecycle
            stats = run_lifecycle(cfg, dl, limit=max(0, args.limit or 0),
                                  dry_run=args.dry_run)
        elif args.points:
            from .pipeline.aging import run_point_aging
            stats = run_point_aging(cfg, dl, limit=limit, dry_run=args.dry_run)
        elif args.sweep:
            stats = sweep_rejections(dl, dry_run=args.dry_run)
            head = "OK 清扫报告（dry-run 未删除）" if args.dry_run else "OK 清扫完成"
            print(f"{head}：{_json.dumps(stats, ensure_ascii=False)}")
            if not args.dry_run and stats["swept"]:
                print("（审计链在 task_log：被删条目历史日志保留 + sweep_delete 留痕；"
                      "共享内容块只减计数，删到零才清正文）")
            return _EXIT_OK
        else:
            stats = run_aging_judgment(cfg, dl, limit=limit,
                                       dry_run=args.dry_run)
    finally:
        dl.close()
    if args.lifecycle:
        written = sum(stats[k] for k in ("version_stale", "version_ok", "version_suspect",
                                         "retired_stale", "retired_ok", "retired_keep"))
        if stats.get("llm_skipped") and not written:
            print(f"SKIP {stats['llm_skipped']}")
            return _EXIT_SKIP
        head = "OK 试跑完成（dry-run 未写库）" if args.dry_run else "OK 生命周期扫描完成"
        print(f"{head}：{_json.dumps({k: v for k, v in stats.items() if k != 'errors'}, ensure_ascii=False)}")
        for err in stats.get("errors", [])[:5]:
            print(f"  ERROR {err}")
        if stats.get("llm_skipped"):
            print(f"  WARN {stats['llm_skipped']}")
        print("（A 段版本型=官方 EOL 表，零 LLM；B 段退场型=按技术栈 LLM，须附官方依据；"
              "stale 已退出消费面，只标不删；重跑幂等）")
        return _EXIT_OK
    if stats.get("skipped"):  # 仅 LLM 未启用时存在（str）
        print(f"SKIP {stats['skipped']}")
        return _EXIT_SKIP
    head = "OK 试跑完成（dry-run 未写库）" if args.dry_run else "OK 复核完成"
    print(f"{head}：{_json.dumps(stats, ensure_ascii=False)}")
    for err in stats.get("errors", [])[:5]:
        print(f"  ERROR {err}")
    print("（结论三值：stale=确证过时退出消费面 / ok=规则误报已否决 / "
          "keep=判不下沉人裁，仍在时效候选）")
    return _EXIT_OK


def _cmd_kerrata(args: argparse.Namespace) -> int:
    import json as _json

    cfg = load_config()
    setup_logging(cfg.log_level)
    limit = 10 if args.limit is None else args.limit
    if args.points:
        if args.scan:
            print("ERROR --points 不能与 --scan 同用（条目级 L1 扫描请单独跑）")
            return _EXIT_USAGE
        if args.backfill_codes:
            if args.from_json:
                print("ERROR --backfill-codes 不能与 --from-json 同用"
                      "（回填只补原因码，不回放结论）")
                return _EXIT_USAGE
            from .pipeline.errata_points import backfill_reason_codes

            dl = _open(cfg)
            try:
                stats = backfill_reason_codes(
                    cfg, dl, limit=max(0, args.limit or 0), dry_run=args.dry_run)
            finally:
                dl.close()
            if stats.get("llm_skipped") and not stats["filled"]:
                print(f"SKIP {stats['llm_skipped']}")
                return _EXIT_SKIP
            head = "OK 试跑完成（dry-run 未写库）" if args.dry_run else "OK 原因码回填完成"
            print(f"{head}：{_json.dumps({k: v for k, v in stats.items() if k != 'errors'}, ensure_ascii=False)}")
            for err in stats.get("errors", [])[:5]:
                print(f"  ERROR {err}")
            if not args.dry_run and stats.get("filled"):
                print("（只补 fact_check.reason_code，verdict/reason/evidence 未动；"
                      "重跑幂等：有码即跳过）")
            return _EXIT_OK
        from .pipeline.errata_points import run_point_errata

        point_limit = 0 if args.limit is None else max(0, args.limit)
        seed = args.from_json
        if not seed:
            default_seed = Path("temp/errata_full_verify.json")
            if default_seed.exists():
                print(f"提示：检测到既有核查产物 {default_seed.as_posix()}，加 "
                      f"--from-json {default_seed.as_posix()} 可零 LLM 费回放")
        dl = _open(cfg)
        try:
            stats = run_point_errata(cfg, dl, limit=point_limit,
                                     dry_run=args.dry_run, seed_path=seed)
        finally:
            dl.close()
        written = stats["imported"] + stats["checked"]
        if stats.get("llm_skipped") and not written:
            print(f"SKIP {stats['llm_skipped']}")
            return _EXIT_SKIP
        head = "OK 试跑完成（dry-run 未写库）" if args.dry_run else "OK 点级核查完成"
        print(f"{head}：{_json.dumps({k: v for k, v in stats.items() if k != 'errors'}, ensure_ascii=False)}")
        for err in stats.get("errors", [])[:5]:
            print(f"  ERROR {err}")
        if stats.get("llm_skipped"):
            print(f"  WARN {stats['llm_skipped']}")
        if not args.dry_run:
            print("（队列：wrong 进 GET /api/errata/points（附理由+依据+溯源）；suspect 不进队列；"
                  "只标不删，重跑幂等）")
        return _EXIT_OK

    from .pipeline.errata import run_errata_check, run_errata_scan

    dl = _open(cfg)
    try:
        if args.scan:
            stats = run_errata_scan(dl, dry_run=args.dry_run)
            head = "OK L1 扫描报告（dry-run 未写库）" if args.dry_run else "OK L1 扫描完成"
            print(f"{head}：{_json.dumps(stats, ensure_ascii=False)}")
            print("（确定性错误直接进裁决队列；节选特征不下结论宁漏勿误；"
                  "裁决在 Web 管理页「勘误裁决」）")
            return _EXIT_OK
        stats = run_errata_check(cfg, dl, limit=max(1, limit),
                                 dry_run=args.dry_run)
    finally:
        dl.close()
    if stats.get("skipped"):  # 仅 LLM 未启用时存在（str）
        print(f"SKIP {stats['skipped']}")
        return _EXIT_SKIP
    head = "OK 试跑完成（dry-run 未写库）" if args.dry_run else "OK 核查完成"
    print(f"{head}：{_json.dumps(stats, ensure_ascii=False)}")
    for err in stats.get("errors", [])[:5]:
        print(f"  ERROR {err}")
    print("（结论三值：error=确认错误附依据进裁决队列 / ok=成立已否决 / "
          "suspect=疑似不出裁决队列留观）")
    return _EXIT_OK


def _cmd_kpeimport(args: argparse.Namespace) -> int:
    import json as _json

    from .pipeline.kpe_import import import_kpe_dir

    cfg = load_config()
    setup_logging(cfg.log_level)
    dl = _open(cfg)
    try:
        stats = import_kpe_dir(
            cfg, dl, args.out_dir, entry_id=args.entry_id, match=args.match,
            replace=args.replace, dry_run=args.dry_run,
            backup=not args.no_backup, limit=args.limit)
    finally:
        dl.close()
    head = "OK 试算完成（dry-run 未写库）" if args.dry_run else "OK 导入完成"
    print(f"{head}：{_json.dumps(stats, ensure_ascii=False)}")
    return _EXIT_OK


_COMMANDS = {
    "kinit": _cmd_kinit,
    "kadd": _cmd_kadd,
    "ksync": _cmd_ksync,
    "serve": _cmd_serve,
    "kexport": _cmd_kexport,
    "kbackup": _cmd_kbackup,
    "ktest": _cmd_ktest,
    "kcheck": _cmd_kcheck,
    "kpoints": _cmd_kpoints,
    "kaging": _cmd_kaging,
    "kerrata": _cmd_kerrata,
    "kpeimport": _cmd_kpeimport,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS[args.command]
    try:
        return handler(args)
    except KnowAtlasError as exc:
        print(f"错误（{type(exc).__name__}）：{exc}", file=sys.stderr)
        if exc.hint:
            print(f"下一步：{exc.hint}", file=sys.stderr)
        return EXIT_BUSINESS
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return EXIT_BUSINESS
