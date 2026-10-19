"""CLI 子命令注册与参数解析（完整方案 §7；argparse，不引 click）。"""

from __future__ import annotations

import argparse
import sys
import uuid
from typing import Sequence

from . import __version__
from .config import load_config
from .datalayer.db import DataLayer
from .errors import KnowAtlasError
from .logging_setup import setup_logging
from .registry.builtins import build_registries

_EXIT_OK, EXIT_BUSINESS, _EXIT_USAGE = 0, 1, 2


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

    ksync = sub.add_parser("ksync", help="同步编排（批量源 M1 起接入）")
    ksync.add_argument("--full", action="store_true", help="全量遍历型源全量拉取")
    ksync.add_argument("--incremental", action="store_true", help="游标型源增量")
    ksync.add_argument("--source", help="只同步指定源")
    ksync.add_argument("--dry-run", action="store_true", help="只探测源可达性，不写库")
    ksync.add_argument("--limit", type=int, default=None)
    ksync.add_argument("--fetch-limit", type=int, default=None,
                       help="显式开启本次抓取，最多 N 条（默认 on_sync=false 不抓）")

    serve = sub.add_parser("serve", help="启动本地 Web 服务（默认 127.0.0.1:8420）")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    kexport = sub.add_parser("kexport", help="数据导出（json|obsidian|opml）—— M5")
    kexport.add_argument("--format", default="json")
    kexport.add_argument("--out", required=True)

    kbackup = sub.add_parser("kbackup", help="快照与恢复（VACUUM INTO）—— M5")
    kbackup.add_argument("--snap", action="store_true")
    kbackup.add_argument("--restore", metavar="FILE")

    ktest = sub.add_parser("ktest", help="回归集 / 契约金丝雀运行器")
    ktest.add_argument("what", choices=["regress", "canary"])

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
    from .pipeline.sync import run_sync

    cfg = load_config()
    setup_logging(cfg.log_level)
    dl = _open(cfg)
    locators, semantics = build_registries(cfg)
    try:
        stats = run_sync(cfg, dl, locators, semantics, full=args.full,
                         source=args.source, dry_run=args.dry_run,
                         limit=args.limit, fetch_limit=args.fetch_limit)
    finally:
        dl.close()
    print(f"OK 同步完成：{stats}")
    return _EXIT_OK


def _cmd_serve(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg.log_level)
    dl = _open(cfg)
    locators, semantics = build_registries(cfg)
    from .web.app import create_app

    app = create_app(cfg, dl, locators, semantics)
    host = args.host or str(cfg.get("general.server_host", "127.0.0.1"))
    port = int(args.port or cfg.get("general.server_port", 8420))
    import uvicorn

    print(f"KnowAtlas 服务：http://{host}:{port}（写操作需 KNOWATLAS_WEB_TOKEN）")
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        dl.close()
    return _EXIT_OK


def _unimplemented(name: str, phase: str) -> int:
    print(f"[{name}] 尚未实现（计划于 {phase} 交付，见 docs/design/知识索引工具-TODO.md）",
          file=sys.stderr)
    return EXIT_BUSINESS


def _cmd_kexport(args: argparse.Namespace) -> int:
    return _unimplemented("kexport", "Phase 5（M5）")


def _cmd_kbackup(args: argparse.Namespace) -> int:
    return _unimplemented("kbackup", "Phase 5（M5）")


def _cmd_ktest(args: argparse.Namespace) -> int:
    return _unimplemented("ktest", "运行测试请用 pytest（tests/ 已覆盖 canary 与回归骨架）")


_COMMANDS = {
    "kinit": _cmd_kinit,
    "kadd": _cmd_kadd,
    "ksync": _cmd_ksync,
    "serve": _cmd_serve,
    "kexport": _cmd_kexport,
    "kbackup": _cmd_kbackup,
    "ktest": _cmd_ktest,
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
