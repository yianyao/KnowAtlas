"""点级勘误管道（P1，2026-10-25 裁决）：hard 点的事实核查落 meta.fact_check。

与条目级勘误（`pipeline/errata.py`）互补：条目级扫描回答「这份文档有没有问题」，
点级回答「这句话有没有错」——实测错误几乎都发生在点这一层，而一个条目里多数点是
对的，条目级标记会连坐整篇。

三件事，按代价从低到高：
1. 候选只取 `kind=hard` 且未核过的点（P0 领域闸门；opinion/unjudgeable/dupe 不判）；
2. 既有核查产物（`temp/errata_full_verify.json`，1,579 条）用 `seed_path` 回放，零 LLM；
3. 只有新入库的 hard 点才走 LLM（`point_errata` task，20/批，同 errata_check 口径）。

幂等：`content_hash` 是点 id（同文本点跨重抽复用）+ `fact_check.at` 游标，已核不重跑。
不写半成品：LLM 未启用/单批故障 → 该批不写，只记账。只标不删：改点 meta，原文与条目零改动。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..semantic.llm import LlmClient
from ..semantic.tasks import point_errata
from ..semantic.base import TaskContext

CHECK_BATCH = 20      # 单次 LLM 调用的点数（与 errata_check/aging 同口径）
TEXT_CAP = 500        # 送 LLM 的点文本上限（实测口径）


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_seed(seed_path: Path) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def _write_verdict(dl: Any, point_id: str, v: dict[str, Any], model: str,
                   stage: str, now: str) -> None:
    """结论落点 meta（整块 fact_check 浅合并）+ 审计留痕。只标不删。"""
    fact = {"verdict": v["verdict"], "reason": v.get("reason", "")[:400],
            "evidence": v.get("evidence", "")[:300],
            "reason_code": v.get("reason_code", ""), "at": now,
            "model": model, "stage": stage}
    dl.merge_meta_of_point(point_id, {"fact_check": fact})
    dl.log_task(now, "kerrata", "point_fact_check", point_id,
                {"verdict": fact["verdict"], "reason_code": fact["reason_code"],
                 "stage": stage})


def backfill_reason_codes(cfg: Any, dl: Any, *, limit: int = 0, dry_run: bool = False,
                          batch: int = CHECK_BATCH, llm: Any = None) -> dict[str, Any]:
    """给已判 wrong 但原因码为空的点补 `fact_check.reason_code`（P1b）。

    只补码不重判：verdict/reason/evidence/at 原样保留（读-改-写整块 fact_check，
    浅合并下直接写 {"fact_check": {"reason_code": ...}} 会把结论抹掉）。
    幂等：有码即跳过；LLM 不可用 → 整批 skip，不写半成品。
    """
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "kerrata")
    now = _now_iso()
    stats: dict[str, Any] = {
        "run_id": run_id, "dry_run": dry_run, "candidates": 0, "filled": 0,
        "llm_calls": 0, "llm_skipped": None, "errors": [],
    }
    try:
        cands = dl.points_wrong_without_reason_code(limit=0)
        if limit and limit > 0:
            cands = cands[:limit]
        stats["candidates"] = len(cands)
        if not cands:
            return stats
        if llm is None and cfg is not None:
            llm = LlmClient.from_config(cfg)
        if llm is None:
            stats["llm_skipped"] = ("llm 未启用（[llm] enabled=false 或 key 未设）——"
                                    "原因码未回填，可稍后重跑")
            return stats
        model = getattr(llm, "model_name", "") or "llm"
        for i in range(0, len(cands), max(1, batch)):
            b = cands[i:i + max(1, batch)]
            items = [{"point_id": c["id"], "text": c["text"],
                      "reason": (c["meta"].get("fact_check") or {}).get("reason", "")}
                     for c in b]
            res = point_errata.classify_codes(items, TaskContext(run_id=run_id, llm=llm))
            stats["llm_calls"] += 1
            if res.get("error"):
                stats["errors"].append(res["error"])
                continue
            ids = {x["id"] for x in b}
            for pid, code in res.get("codes", {}).items():
                if pid not in ids:
                    continue
                if dry_run:
                    stats["filled"] += 1
                    continue
                cur = dl.get_point_meta(pid)
                fact = dict((cur or {}).get("meta", {}).get("fact_check") or {})
                fact["reason_code"] = code
                dl.merge_meta_of_point(pid, {"fact_check": fact})
                dl.log_task(now, "kerrata", "point_reason_code_backfill", pid,
                            {"reason_code": code, "model": model})
                stats["filled"] += 1
    finally:
        dl.finish_run(run_id, {k: v for k, v in stats.items() if k != "errors"}
                      | {"errors": len(stats["errors"])})
    return stats


def run_point_errata(cfg: Any, dl: Any, *, limit: int = 0, dry_run: bool = False,
                     seed_path: str | Path | None = None, batch: int = CHECK_BATCH,
                     llm: Any = None) -> dict[str, Any]:
    """点级勘误：候选（hard 且未核）→ 种子回放 → 新点 LLM 增量；返回统计。

    `llm_skipped` 非空表示 LLM 不可用（确定性部分已落库，剩余点下次再核）。
    """
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "kerrata")
    now = _now_iso()
    stats: dict[str, Any] = {
        "run_id": run_id, "dry_run": dry_run, "limit": limit, "batch": batch,
        "candidates": 0, "imported": 0, "checked": 0, "wrong": 0, "suspect": 0,
        "ok": 0, "llm_calls": 0, "llm_skipped": None, "errors": [],
    }

    def _bump(verdict: str) -> None:
        stats[verdict] = stats.get(verdict, 0) + 1

    try:
        cands = dl.hard_points_without_fact_check(limit=0)
        if limit and limit > 0:
            cands = cands[:limit]
        stats["candidates"] = len(cands)
        if not cands:
            return stats

        seed = _load_seed(Path(seed_path)) if seed_path else {}
        seeded: set[str] = set()
        for c in cands:
            hit = seed.get(c["id"])
            if not hit:
                continue
            verdict = str(hit.get("verdict") or "").strip().lower()
            if verdict not in point_errata.VERDICTS:
                continue
            v = {"verdict": verdict, "reason": str(hit.get("reason") or ""),
                 "evidence": str(hit.get("evidence") or ""), "reason_code": ""}
            if not dry_run:
                _write_verdict(dl, c["id"], v, f"seed:{Path(seed_path).name}",
                               "seed", now)
            stats["imported"] += 1
            seeded.add(c["id"])
            _bump(verdict)

        rest = [c for c in cands if c["id"] not in seeded]
        if rest:
            if llm is None and cfg is not None:
                llm = LlmClient.from_config(cfg)
            if llm is None:
                stats["llm_skipped"] = ("llm 未启用（[llm] enabled=false 或 key 未设）——"
                                        "剩余 hard 点未核，可稍后重跑")
            else:
                model = getattr(llm, "model_name", "") or "llm"
                for i in range(0, len(rest), max(1, batch)):
                    b = rest[i:i + max(1, batch)]
                    items = [{"point_id": c["id"], "text": c["text"][:TEXT_CAP]}
                             for c in b]
                    res = point_errata.run(items, TaskContext(run_id=run_id, llm=llm))
                    stats["llm_calls"] += 1
                    if res.get("error"):
                        stats["errors"].append(res["error"])
                        continue
                    ids = {x["id"] for x in b}
                    for pid, v in res.get("verdicts", {}).items():
                        if pid not in ids:
                            continue
                        if not dry_run:
                            _write_verdict(dl, pid, v, model, "llm", now)
                        stats["checked"] += 1
                        _bump(v["verdict"])
    finally:
        dl.finish_run(run_id, {k: v for k, v in stats.items() if k != "errors"}
                      | {"errors": len(stats["errors"])})
    return stats