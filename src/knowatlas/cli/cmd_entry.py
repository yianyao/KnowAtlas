"""CLI 子命令注册与参数解析（完整方案 §7；argparse，不引 click）。"""

# 拆分自 src/knowatlas/cli.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


import argparse
import uuid
from ..config import load_config
from ..logging_setup import setup_logging
from ..registry.builtins import build_registries
from ._shared import _EXIT_OK, _open, _warn_if_llm_unavailable


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
    from ..pipeline.kadd import ingest_url

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
