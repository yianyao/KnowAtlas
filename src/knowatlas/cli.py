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

    kcheck = sub.add_parser("kcheck", help="链接体检：检测可达性（404/410 标记 dead）")
    kcheck.add_argument("--limit", type=int, default=100, help="本次最多检测条数（默认 100）")
    kcheck.add_argument("--qps", type=float, default=4.0, help="检测速率（默认 4 条/秒）")

    kpoints = sub.add_parser(
        "kpoints", help="知识点抽取：形态判定 integral/split → 切点 → hash 去重一点多溯源（方案 §7.1）")
    kpoints.add_argument("--limit", type=int, default=10,
                         help="本次最多处理条数（默认 10——试跑口径，全量判定须用户裁决模型档位）")
    kpoints.add_argument("--dry-run", action="store_true",
                         help="只判定与报告，不写库（LLM 费用照常发生）")

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
    dl = _open(cfg)
    locators, semantics = build_registries(cfg)
    try:
        if args.embed or args.embed_force:
            from .semantic.embed import from_config as embedder_from_config
            from .pipeline.embed_index import embed_entries

            embedder = embedder_from_config(cfg)
            if embedder is None:
                print("SKIP 向量索引未启用（[embedding] enabled=true 且安装"
                      " requirements-optional）——主链路不受影响")
                return _EXIT_SKIP
            stats = embed_entries(dl, embedder, force=args.embed_force)
            print(f"OK 向量索引完成：{stats}")
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
                         freshness_scan=args.freshness_scan)
    finally:
        dl.close()
    print(f"OK 同步完成：{stats}")
    return _EXIT_OK


def _cmd_serve(args: argparse.Namespace) -> int:
    import secrets

    cfg = load_config()
    setup_logging(cfg.log_level)
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
    host = args.host or str(cfg.get("general.server_host", "127.0.0.1"))
    port = int(args.port or cfg.get("general.server_port", 8420))
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
    dl = _open(cfg)
    try:
        stats = run_health_check(cfg, dl, limit=args.limit, qps=args.qps)
    finally:
        dl.close()
    print(f"OK 体检完成：{stats}（dead=永久失效，error=疑似临时故障；"
          f"Web UI「失效链接」视图可批量舍弃）")
    return _EXIT_OK


def _cmd_kpoints(args: argparse.Namespace) -> int:
    from .pipeline.points import run_points_extract

    cfg = load_config()
    setup_logging(cfg.log_level)
    dl = _open(cfg)
    try:
        stats = run_points_extract(cfg, dl, limit=max(1, args.limit),
                                   dry_run=args.dry_run)
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
    if not args.dry_run:
        print("（点列表：points 表；溯源数=可信度信号；判定理由在点 meta.judge_reason）")
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
