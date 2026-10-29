"""CLI 子命令注册与参数解析（完整方案 §7；argparse，不引 click）。"""

# 拆分自 src/knowatlas/cli.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


import argparse
from ..config import load_config
from ..logging_setup import setup_logging
from ..registry.builtins import build_registries
from ._shared import _EXIT_OK, _EXIT_SKIP, _open, _warn_if_llm_unavailable


def _cmd_ksync(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg.log_level)
    _warn_if_llm_unavailable(cfg, "ksync")
    dl = _open(cfg)
    locators, semantics = build_registries(cfg)
    try:
        if args.embed or args.embed_force:
            from ..semantic.embed import from_config as embedder_from_config
            from ..semantic.llm import LlmClient
            from ..pipeline.embed_index import dedup_points, embed_entries, embed_points

            embedder = embedder_from_config(cfg)
            if embedder is None:
                print("SKIP 向量索引未启用（[embedding] enabled=true 且安装"
                      " requirements-optional）——主链路不受影响")
                return _EXIT_SKIP
            stats = embed_entries(dl, embedder, force=args.embed_force)
            pstats = embed_points(dl, embedder, force=args.embed_force)
            # 批次 94：向量就绪后语义去重（可逆标记）；R30：边界对交 LLM 裁定
            # （llm=None 时边界对一律不并——宁漏勿误）
            dstats = dedup_points(dl, llm=LlmClient.from_config(cfg))
            print(f"OK 向量索引完成：条目 {stats} | 点 {pstats} | 去重 {dstats}")
            return _EXIT_OK
        if args.cluster_report:
            from ..semantic.embed import from_config as embedder_from_config
            from ..semantic.llm import LlmClient
            from ..pipeline.embed_index import cluster_report

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
            from ..pipeline.expand import expand_seed

            stats = expand_seed(cfg, dl, locators, semantics,
                                args.expand, limit=args.expand_limit)
            print(f"OK 扩散完成：{stats}")
            return _EXIT_OK
        from ..pipeline.sync import run_sync

        stats = run_sync(cfg, dl, locators, semantics, full=args.full,
                         source=args.source, dry_run=args.dry_run,
                         limit=args.limit, fetch_limit=args.fetch_limit,
                         entry_ids=args.entry,
                         reclassify=args.reclassify, value_scan=args.value_scan,
                         dedupe_scan=args.dedupe_scan,
                         freshness_scan=args.freshness_scan,
                         errata_scan=args.errata_scan,
                         purge_source=args.purge_source,
                         purge_reason=args.purge_reason)
    finally:
        dl.close()
    for name, src_stats in (stats.get("sources") or {}).items():
        for warning in (src_stats.get("warnings") or []):
            print(f"WARN [{name}] {warning}")
    print(f"OK 同步完成：{stats}")
    return _EXIT_OK
