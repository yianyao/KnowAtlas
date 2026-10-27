"""点级老化两型（P2，2026-10-26 工单 `P2点级老化两型`）：主动扫描技术栈过时。

与批次 93 的被动路（`run_point_aging`：等条目被标 suspect 才复核点）互补：
本管道不看条目信号，直接按 `kind=hard` 扫全库，分两段——

- **A 版本型**（零 LLM，确定性）：点文本里的「技术 + 版本」对照 `semantic/eol.py`
  的官方支持矩阵。命中 EOL → `stale`；全部在支持期 → `ok`；版本不在表内 → `suspect`；
- **B 退场型**（LLM，按技术栈分组）：无版本号但提到技术名的点，按技术去重后整批判
  「这项技术还在不在维护」，retired 必须附官方依据，给不出降 `keep`。

纪律：只吃 `kind=hard`（P0 领域闸门，opinion/unjudgeable/dupe 一律不判）；只标不删
（`stale` 走 `set_point_aging` 退出消费面，物理删除仍只走 30 天冷却的人裁出口）；
幂等游标是 `meta.lifecycle.at`（有 at 即已判，重跑零写入）；LLM 不可用时 A 段照跑、
B 段整段 skip 不写半成品。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..semantic import eol
from ..semantic.base import TaskContext
from ..semantic.llm import LlmClient
from ..semantic.tasks import point_lifecycle
from .domain_gate import eligible_points

LIFECYCLE_BATCH = 20   # 单次 LLM 调用的技术数（按技术栈分组，与 aging 20/批同口径）
SAMPLE_CAP = 240       # 送给 LLM 的上下文片段上限（点文本）


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write(dl: Any, point_id: str, *, kind: str, verdict: str, tech: str,
           version: str, evidence: str, model: str, stage: str, now: str,
           dry_run: bool) -> None:
    """结论落点 meta（读-改-写整块，浅合并坑）+ stale 追加退出消费面 + 审计留痕。"""
    block = {"kind": kind, "verdict": verdict, "tech": tech, "version": version,
             "evidence": evidence[:300], "at": now, "model": model, "stage": stage}
    if dry_run:
        return
    cur = dl.get_point_meta(point_id)
    old = dict(((cur or {}).get("meta") or {}).get("lifecycle") or {})
    old.update(block)
    dl.merge_meta_of_point(point_id, {"lifecycle": old})
    if verdict == "stale":
        # 复用现成机制：aging_flag=stale 退出消费面；aging_checked_at 记游标，
        # 避免 L2 点级老化（run_point_aging）再把它翻回来。
        dl.set_point_aging(point_id, "stale",
                           f"lifecycle/{kind}：{tech} {version} {evidence}"[:200])
    dl.log_task(now, "kaging", "point_lifecycle", point_id,
                {"kind": kind, "verdict": verdict, "tech": tech, "version": version})


def _version_verdict(hits: list[eol.VersionHit], table: dict[str, dict[str, str]],
                     today: date | None) -> tuple[str, eol.VersionHit, str]:
    """版本型三值：任一命中 EOL → stale；全部支持期内 → ok；否则 suspect。"""
    checked = [(h, *eol.eol_status(h.tech, h.version, table=table, today=today))
               for h in hits]
    for h, status, evidence in checked:
        if status == "eol":
            return "stale", h, evidence
    if all(status == "supported" for _, status, _ in checked):
        h, _, evidence = checked[0]
        return "ok", h, evidence
    h, _, evidence = checked[0]
    return "suspect", h, evidence


def run_lifecycle(cfg: Any, dl: Any, *, limit: int = 0, dry_run: bool = False,
                  batch: int = LIFECYCLE_BATCH, llm: Any = None,
                  today: date | None = None) -> dict[str, Any]:
    """主动扫描 hard 点的技术栈过时（版本型 + 退场型）；返回统计。"""
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "kaging")
    now = _now_iso()
    data_dir = Path(cfg.db_path).parent if cfg is not None else None
    table = eol.load_table(data_dir)
    stats: dict[str, Any] = {
        "run_id": run_id, "dry_run": dry_run, "candidates": 0,
        "version_stale": 0, "version_ok": 0, "version_suspect": 0,
        "tech_groups": 0, "retired_stale": 0, "retired_ok": 0, "retired_keep": 0,
        "unjudged": 0, "llm_calls": 0, "llm_skipped": None, "errors": [],
    }
    try:
        points = dl.points_of_kind("hard")
        # 域闸门（工单 2026-10-27 §2.3）：社科/人文类一级分类不判——「技术过时」
        # 对文学/历史/哲学没有意义；无分类的点也不判（宁漏勿误）。
        exclude = getattr(cfg, "aging_exclude_categories", ()) if cfg is not None else ()
        allowed = eligible_points(dl, [p["id"] for p in points], exclude)
        points = [p for p in points if allowed.get(p["id"])]
        if limit and limit > 0:
            points = points[:limit]
        cands = [p for p in points
                 if not ((p["meta"].get("lifecycle") or {}).get("at"))
                 and p.get("aging_flag") != "stale"]
        stats["candidates"] = len(cands)
        if not cands:
            return stats

        # ---- A 版本型（零 LLM） ----
        rest: list[dict[str, Any]] = []
        for p in cands:
            hits = eol.detect_versions(p["text"], table=table)
            if not hits:
                rest.append(p)
                continue
            verdict, hit, evidence = _version_verdict(hits, table, today)
            _write(dl, p["id"], kind="version", verdict=verdict, tech=hit.tech,
                   version=hit.version, evidence=evidence, model="eol-table",
                   stage="rule", now=now, dry_run=dry_run)
            stats[f"version_{verdict}"] += 1

        # ---- B 退场型（LLM，按技术栈分组） ----
        groups: dict[str, list[dict[str, Any]]] = {}
        for p in rest:
            for tech in eol.detect_techs(p["text"], table=table):
                groups.setdefault(tech, []).append(p)
        stats["tech_groups"] = len(groups)
        if not groups:
            return stats
        # 试跑不自动连 LLM（dry_run 必须零费用）；要演练 B 段就显式传替身 llm。
        if llm is None and cfg is not None and not dry_run:
            llm = LlmClient.from_config(cfg)
        if llm is None:
            stats["llm_skipped"] = ("llm 未启用（[llm] enabled=false 或 key 未设）——"
                                    "版本型（A 段）已落库，退场型（B 段）未跑，可稍后重跑")
            return stats
        model = getattr(llm, "model_name", "") or "llm"
        tech_verdicts: dict[str, dict[str, str]] = {}
        techs = sorted(groups)
        for i in range(0, len(techs), max(1, batch)):
            chunk = techs[i:i + max(1, batch)]
            items = [{"tech": t, "sample": groups[t][0]["text"][:SAMPLE_CAP]}
                     for t in chunk]
            res = point_lifecycle.run(items, TaskContext(run_id=run_id, llm=llm))
            stats["llm_calls"] += 1
            if res.get("error"):
                stats["errors"].append(res["error"])
                continue
            tech_verdicts.update(res.get("verdicts", {}))

        # 一点可能提到多个技术：任一 retired → stale；全 active → ok；否则 keep
        for p in rest:
            judged = [(t, tech_verdicts[t]) for t in eol.detect_techs(p["text"], table=table)
                      if t in tech_verdicts]
            if not judged:
                stats["unjudged"] += 1
                continue
            retired = [(t, v) for t, v in judged if v["verdict"] == "retired"]
            if retired:
                tech, v = retired[0]
                verdict = "stale"
                stats["retired_stale"] += 1
            elif all(v["verdict"] == "active" for _, v in judged):
                tech, v = judged[0]
                verdict = "ok"
                stats["retired_ok"] += 1
            else:
                tech, v = judged[0]
                verdict = "keep"
                stats["retired_keep"] += 1
            _write(dl, p["id"], kind="retired", verdict=verdict, tech=tech,
                   version="", evidence=v.get("evidence", ""), model=model,
                   stage="llm", now=now, dry_run=dry_run)
    finally:
        dl.finish_run(run_id, {k: v for k, v in stats.items() if k != "errors"}
                      | {"errors": len(stats["errors"])})
    return stats