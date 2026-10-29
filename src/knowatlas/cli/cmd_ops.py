"""CLI 子命令注册与参数解析（完整方案 §7；argparse，不引 click）。"""

# 拆分自 src/knowatlas/cli.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


import argparse
import os
import sys
from pathlib import Path
from ..config import load_config
from ..logging_setup import setup_logging
from ..registry.builtins import build_registries
from ._shared import EXIT_BUSINESS, _EXIT_OK, _apply_serve_overrides, _open, _warn_if_llm_unavailable


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
    from ..web.app import create_app

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
    from ..web.api import token_fingerprint

    if host not in ("127.0.0.1", "localhost", "::1"):
        # 局域网访问（TODO P1）：只把**本机网卡地址**加进 Host/Origin 白名单
        # （见 web/api.py::allowed_hosts）——不放开整个内网段，Host 校验仍能挡 DNS rebinding。
        from ..web.api import lan_urls

        urls = lan_urls(port)
        if urls:
            print(f"局域网可达：{'  '.join(urls)}")
            print("提示：同网段设备打开页面即自动获得写凭据（/api/session 种 Cookie），"
                  "只想手机只读就别长期挂 0.0.0.0。")
            print(f"手机打不开先放行端口 {port}（Windows 防火墙入站规则）。")
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

    from ..config import load_config
    from ..pipeline import export as export_mod

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
    from ..pipeline.backup import restore as _restore
    from ..pipeline.backup import snapshot as _snapshot
    from ..pipeline.backup import verify_snapshot as _verify

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
    from ..config import load_config
    from ..pipeline.regress import run_regress, seed_from_log

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
    from ..pipeline.health import run_health_check

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
