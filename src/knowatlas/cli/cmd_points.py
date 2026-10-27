"""CLI 子命令注册与参数解析（完整方案 §7；argparse，不引 click）。"""

# 拆分自 src/knowatlas/cli.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


import argparse
from pathlib import Path
from ..config import load_config
from ..logging_setup import setup_logging
from ._shared import _EXIT_OK, _EXIT_SKIP, _EXIT_USAGE, _open, _warn_if_llm_unavailable


def _cmd_kpoints_triage(cfg, args: argparse.Namespace) -> int:
    """P0 点分诊：dupe 标记 + 种子导入（零 LLM）+ 新点 LLM 增量，幂等落 meta.kind。"""
    import json as _json

    from ..pipeline.triage import run_point_triage

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
    from ..pipeline.points import run_points_extract

    cfg = load_config()
    setup_logging(cfg.log_level)
    # 定向补抽（--entry）的默认上限 = 点名条数：用户点名几条就抽几条，
    # 不被「抽取默认 10」这个池子口径悄悄截断。
    if args.limit is None:
        limit = len(args.entry) if args.entry else 10
    else:
        limit = args.limit
    if args.triage:
        if args.purge_points or args.retry_blocked or args.entry:
            print("ERROR --triage 不能与 --purge-points / --retry-blocked / --entry 同用"
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
                                   entry_ids=args.entry,
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
    if stats.get("chunked"):
        print(f"  CHUNK {stats['chunked']} 条长文在管道内分块抽取"
              f"（{stats.get('chunks_total', 0)} 块，meta.points_chunked；"
              f"溯源 char_offset 已折算回全文坐标）")
    if stats.get("pending_kpe"):
        detail = "、".join(f"{d['title']}（{d['chars']:,} 字）"
                          for d in stats.get("pending_kpe_detail", [])[:5])
        print(f"  PENDING {stats['pending_kpe']} 条正文超过分块上限"
              f"{cfg.points_chunk_total_max:,} 字"
              f"（meta.points_pending_kpe）：{detail}")
        print("    这些长文（书/长报告）不截断抽点；自动通道：`kauto`（或 serve 内置巡检）"
              "会按类型走 KPE，见 [ingest] allow_kpe。手工等价步骤：")
        print("      uv run python -m kpe chunks <源文件> --out temp/kpe-<名>")
        print("      uv run python -m kpe extract temp/kpe-<名> --base-url <url>"
              " --model <model> --api-key-env <KEY_ENV>")
        print('      uv run python -m knowatlas kpeimport temp/kpe-<名> --match "<书名通配>"')
    if not args.dry_run:
        print("（点列表：points 表；溯源数=可信度信号；判定理由在点 meta.judge_reason）")
    return _EXIT_OK


def _cmd_kpeimport(args: argparse.Namespace) -> int:
    import json as _json

    from ..pipeline.kpe_import import import_kpe_dir

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


def _cmd_kauto(args: argparse.Namespace) -> int:
    import json as _json

    from ..pipeline.ingest import activate_pending, run_ingest_pass

    cfg = load_config()
    setup_logging(cfg.log_level)
    _warn_if_llm_unavailable(cfg, "kauto")
    dl = _open(cfg)
    try:
        if args.activate_only:
            stats = activate_pending(cfg, dl, dry_run=args.dry_run)
        else:
            stats = run_ingest_pass(cfg, dl, None, None, dry_run=args.dry_run,
                                    limit=args.limit,
                                    do_aging=not args.no_aging,
                                    activate=not args.no_activate)
    finally:
        dl.close()
    head = "OK 试跑完成（dry-run 未写库）" if args.dry_run else "OK 巡检完成"
    print(f"{head}：{_json.dumps(stats, ensure_ascii=False, default=str)}")
    if stats.get("activate") and stats["activate"].get("rejects"):
        for r in stats["activate"]["rejects"][:5]:
            print(f"  REJECT {r['entry_id']} {r['title']}：{r['reason']}")
    for err in (stats.get("errors") or [])[:5]:
        print(f"  ERROR {_json.dumps(err, ensure_ascii=False)[:200]}")
    return _EXIT_OK
