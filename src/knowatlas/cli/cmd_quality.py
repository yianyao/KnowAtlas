"""CLI 子命令注册与参数解析（完整方案 §7；argparse，不引 click）。"""

# 拆分自 src/knowatlas/cli.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


import argparse
from pathlib import Path
from ..config import load_config
from ..logging_setup import setup_logging
from ._shared import _EXIT_OK, _EXIT_SKIP, _EXIT_USAGE, _open


def _cmd_kaging(args: argparse.Namespace) -> int:
    import json as _json

    from ..pipeline.aging import run_aging_judgment, sweep_rejections

    if args.lifecycle and (args.points or args.sweep):
        print("ERROR --lifecycle 不能与 --points/--sweep 同用（三者入口不同，分开跑）")
        return _EXIT_USAGE
    cfg = load_config()
    setup_logging(cfg.log_level)
    limit = 10 if args.limit is None else max(1, args.limit)
    dl = _open(cfg)
    try:
        if args.lifecycle:
            from ..pipeline.lifecycle import run_lifecycle
            stats = run_lifecycle(cfg, dl, limit=max(0, args.limit or 0),
                                  dry_run=args.dry_run)
        elif args.points:
            from ..pipeline.aging import run_point_aging
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
            from ..pipeline.errata_points import backfill_reason_codes

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
        from ..pipeline.errata_points import run_point_errata

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

    from ..pipeline.errata import run_errata_check, run_errata_scan

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
