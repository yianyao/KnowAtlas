"""入库即处理（工单 2026-10-27《入库即抽点与自动老化》§2.2）。

一次巡检 = 四段，全部幂等、可 dry-run、每步留 `task_log` 审计：

1. **激活**：`pending` 条目过 L0 守门（结构规则 + 正文形态）——垃圾直接 `rejected`，
   其余自动转正 `active`（用户 2026-10-27 裁决 C：待审闸门自动化，规则守门 + 可人工否决）。
2. **抓正文**：`active` 且无正文的条目补抓（复用 `sync._fetch_missing` 的双后端链；
   抓到即分类，口径与 `ksync` 的 `post_fetch` 一致）。
3. **抽点**：按 `ingest_router.plan` 分流——`pipeline`（≤ 上限，含分块）或 `kpe`
   （PDF / 超长文档）；`skip` 的条目把理由写进 `meta.ingest`，管理页可见。
4. **老化**（可选）：到点的周期跑 `run_lifecycle`（版本型零 LLM 先行），
   域闸门在 `pipeline/lifecycle.py`（非社科类才判）。

护栏（裁决 F）：每轮总条数上限、单条目失败计数（超 `ingest.max_retries` 进
`meta.ingest.dead` 不再自动烧钱）、`dry-run` 只出计划、`meta.ingest` 记录
「走了哪条通道 / 为什么没做」，`task_log` 记每条例子的结论。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..semantic.value_guard import is_garbled, is_index_page, judge_value
from .ingest_router import Route, plan

#: `task_log.task_name`：入库即处理的审计名（与 ksync/kpoints 区分）。
TASK = "kauto"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _body_of(dl: Any, entry: Any) -> str:
    """条目正文（与 points._entry_body 同口径：inline 预览与全文取较长者）。"""
    body = (entry.inline_content or "").strip()
    if entry.content_hash:
        full = (dl.get_content(entry.content_hash) or "").strip()
        if len(full) > len(body):
            return full
    return body


def l0_guard(locator: str, body: str = "") -> str | None:
    """L0 守门：返回拒绝原因码；None = 可以入库。

    三条零成本规则（宁漏勿误，误杀可在管理页一键转正）：
    - `judge_value`：资源直链 / 站点首页 / 列表子页；
    - `is_index_page`：正文是表格式书目/索引页（有正文时才判）；
    - `is_garbled`：乱码（用户铁律：不是可用的知识 = 没有）。
    """
    reason = judge_value(locator)
    if reason:
        return reason
    if body:
        if is_garbled(body):
            return "garbled"
        if is_index_page(body):
            return "index_page"
    return None


def activate_pending(cfg: Any, dl: Any, *, dry_run: bool = False,
                     limit: int = 0) -> dict[str, Any]:
    """把 `pending` 条目按 L0 守门分流：垃圾 → rejected，其余 → active。"""
    entries = dl.list_entries(status="pending", limit=limit or 100000)
    stats: dict[str, Any] = {"candidates": len(entries), "activated": 0,
                             "rejected": 0, "reasons": {}, "dry_run": dry_run,
                             "rejects": [], "activates": []}
    now = _now_iso()
    to_activate: list[str] = []
    to_reject: list[tuple[str, str]] = []
    for e in entries:
        reason = l0_guard(str(e.locator or ""), _body_of(dl, e))
        if reason:
            to_reject.append((e.id, reason))
            stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
            if len(stats["rejects"]) < 20:
                stats["rejects"].append({"entry_id": e.id,
                                         "title": str(e.title)[:40], "reason": reason})
        else:
            to_activate.append(e.id)
            if len(stats["activates"]) < 20:
                stats["activates"].append({"entry_id": e.id,
                                           "title": str(e.title)[:40]})
    stats["activated"] = len(to_activate)
    stats["rejected"] = len(to_reject)
    if dry_run:
        return stats
    if to_reject:
        ids = [eid for eid, _ in to_reject]
        dl.set_status(ids, "rejected")
        for eid, reason in to_reject:
            dl.merge_meta(eid, {"value_flag": "not_knowledge",
                                "value_flag_reason": reason,
                                "auto_rejected_at": now})
        dl.log_task(now, TASK, "auto_reject", ",".join(ids[:50]),
                    {"count": len(ids), "reasons": stats["reasons"]})
    if to_activate:
        dl.set_status(to_activate, "active")
        for eid in to_activate:
            dl.merge_meta(eid, {"auto_activated_at": now})
        dl.log_task(now, TASK, "auto_activate", ",".join(to_activate[:50]),
                    {"count": len(to_activate)})
    return stats


@dataclass
class _Plan:
    """本轮待办（按通道分组，保持库内顺序）。"""

    fetch: list[Any] = field(default_factory=list)
    pipeline: list[tuple[Any, str]] = field(default_factory=list)   # (entry, body)
    kpe: list[tuple[Any, str]] = field(default_factory=list)
    skipped: list[tuple[Any, Route]] = field(default_factory=list)


def _is_dead(entry: Any) -> bool:
    return bool((((entry.meta or {}).get("ingest") or {}).get("dead")))


def _plan(cfg: Any, dl: Any, entries: list[Any], *, has_points: set[str]
          ) -> _Plan:
    """给每个 active 条目定通道；已有正文但已抽过点的条目直接略过。"""
    out = _Plan()
    chunk_chars = cfg.points_chunk_chars
    chunk_total = cfg.points_chunk_total_max
    allow_kpe = cfg.ingest_allow_kpe
    for e in entries:
        if _is_dead(e):
            continue
        body = _body_of(dl, e)
        route = plan(str(e.locator or ""), body_chars=len(body) if body else None,
                     chunk_chars=chunk_chars, chunk_total_max=chunk_total,
                     allow_kpe=allow_kpe)
        if route.tool == "fetch":
            out.fetch.append(e)
            continue
        if route.tool == "skip":
            out.skipped.append((e, route))
            continue
        if e.id in has_points:
            continue                    # 已抽过点：不再重复烧钱（幂等游标）
        if (e.meta or {}).get("points_gate"):
            continue                    # 自洽性闸门：LLM 判过「无可独立成点」
        if route.tool == "kpe":
            out.kpe.append((e, body))
        else:
            out.pipeline.append((e, body))
    return out


def _mark_meta(dl: Any, entry_id: str, patch: dict[str, Any]) -> None:
    dl.merge_meta(entry_id, {"ingest": patch})


def _mark_failure(dl: Any, entry: Any, error: str, *, max_retries: int,
                  now: str) -> int:
    # 计数必须读库：调用方手里的 Entry 可能是本轮早些时候的快照（同一轮多次失败）
    fresh = dl.get_entry(entry.id) or entry
    cur = dict(((fresh.meta or {}).get("ingest") or {}))
    fails = int(cur.get("failures") or 0) + 1
    cur.update({"failures": fails, "last_error": str(error)[:200], "at": now})
    if fails > max_retries:
        cur["dead"] = True
    _mark_meta(dl, entry.id, cur)
    dl.log_task(now, TASK, "error", entry.id,
                {"failures": fails, "dead": bool(cur.get("dead")),
                 "error": str(error)[:200]})
    return fails


def _aging_due(dl: Any, cfg: Any, now: datetime) -> bool:
    """老化节拍：距上一次 `kauto/aging` 满 `aging.interval_hours` 才算到点。"""
    try:
        rows = dl.list_task_log_actions(TASK, "aging")
    except Exception:  # noqa: BLE001 —— 审计读失败不该阻断整轮
        return False
    if not rows:
        return True
    last = str(rows[-1].get("at") or "")
    try:
        prev = datetime.fromisoformat(last)
    except ValueError:
        return True
    return (now - prev) >= timedelta(hours=cfg.aging_interval_hours)


def run_ingest_pass(cfg: Any, dl: Any, semantics: Any = None,
                    locators: Any = None, *, dry_run: bool = False,
                    limit: int | None = None, do_aging: bool = True,
                    activate: bool = True, llm: Any = None) -> dict[str, Any]:
    """一轮巡检：激活 → 抓正文 → 抽点（管道/KPE）→（到点）老化；返回统计。"""
    import uuid

    from .points import run_points_extract
    from ..semantic.llm import LlmClient

    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, TASK)
    now = datetime.now().astimezone()
    now_iso = now.isoformat(timespec="seconds")
    budget = cfg.ingest_max_entries_per_run if limit is None else max(0, limit)
    stats: dict[str, Any] = {
        "run_id": run_id, "dry_run": dry_run, "budget": budget,
        "activated": 0, "rejected": 0, "fetched": 0, "pipeline": 0, "kpe": 0,
        "skipped": 0, "dead": 0, "errors": [], "points_created": 0,
        "aging": None,
    }
    try:
        if activate:
            act = activate_pending(cfg, dl, dry_run=dry_run)
            stats["activate"] = act
            stats["activated"] = act["activated"]
            stats["rejected"] = act["rejected"]

        entries = dl.list_entries(status="active", limit=100000)
        has_points = dl.point_source_entry_ids()
        plan_ = _plan(cfg, dl, entries, has_points=has_points)

        # ---- 跳过项：把理由落到 meta.ingest（管理页/审计可见），不烧钱 ----
        for e, route in plan_.skipped:
            stats["skipped"] += 1
            if not dry_run:
                _mark_meta(dl, e.id, {"route": route.tool, "reason": route.reason,
                                      "detail": route.detail, "at": now_iso})
                dl.log_task(now_iso, TASK, "skip", e.id,
                            {"reason": route.reason, "detail": route.detail})

        # 预算分配（**抓取之前**定）：KPE 单本贵且不可分割，先留 1 个名额，余量给管道
        # （便宜、条数多）；0 = 不限。
        # 2026-10-28 修：原先在抓取之后切分，而本轮新抓到的条目会追加进 `plan_.pipeline`，
        # 于是「管道数 = 既有 + 本轮抓取 ≥ budget」→ `kpe[:max(0, budget - len(pipeline))]`
        # 恒为空，KPE 在 kauto 里根本排不上队（真库实测 `--limit 1` 与 `--limit 6` 都是
        # `kpe: 0`，只有 `--limit 0` 不限时才轮到书）。
        if budget:
            plan_.kpe = plan_.kpe[:1 if plan_.kpe else 0]
            plan_.pipeline = plan_.pipeline[:max(0, budget - len(plan_.kpe))]

        # ---- 抓正文（只在该轮预算内）----
        fetch_budget = budget if budget else len(plan_.fetch)
        if dry_run:
            # 试跑只报计划：抓正文会写 content_store、失败还会打 value_flag，不能"试"。
            stats["fetch_planned"] = len(plan_.fetch[:fetch_budget])
        elif plan_.fetch and fetch_budget > 0:
            from .sync import _categorize, _fetch_missing

            if locators is None:
                from ..registry.builtins import build_registries
                locators, semantics = build_registries(cfg)
            picked = plan_.fetch[:fetch_budget]
            fstats = _fetch_missing(cfg, dl, locators, picked, fetch_budget, run_id)
            fetched_ids = fstats.pop("fetched_ids", [])
            stats["fetched"] = int(fstats.get("fetched") or 0)
            stats["fetch"] = fstats
            if fetched_ids:
                fresh = [dl.get_entry(eid) for eid in fetched_ids]
                fresh = [e for e in fresh if e is not None]
                if semantics is not None:
                    stats["post_fetch"] = _categorize(
                        dl, semantics, cfg, fresh, set(), set(fetched_ids), run_id)
                # 抓到正文的条目本轮就地重新定通道（省下一轮巡检）
                for e in fresh:
                    body = _body_of(dl, e)
                    route = plan(str(e.locator or ""), body_chars=len(body) or None,
                                 chunk_chars=cfg.points_chunk_chars,
                                 chunk_total_max=cfg.points_chunk_total_max,
                                 allow_kpe=cfg.ingest_allow_kpe)
                    if route.tool == "pipeline":
                        plan_.pipeline.append((e, body))
                    elif route.tool == "kpe":
                        plan_.kpe.append((e, body))
                    else:
                        stats["skipped"] += 1
                        _mark_meta(dl, e.id, {"route": route.tool,
                                              "reason": route.reason,
                                              "detail": route.detail,
                                              "at": now_iso})

        llm = llm if llm is not None else (
            LlmClient.from_config(cfg)
            if (not dry_run and (plan_.pipeline or plan_.kpe)) else None)
        if llm is None and plan_.pipeline and not dry_run:
            stats["errors"].append("LLM 未启用：integral 条目可产（整篇照抄降级），"
                                   "split 条目记错留待重试")

        # ---- 管道通道 ----
        if plan_.pipeline and dry_run:
            # 试跑只报计划：抽点要花 LLM 钱，dry-run 承诺零费用。
            stats["pipeline_planned"] = len(plan_.pipeline)
        elif plan_.pipeline:
            ids = [e.id for e, _ in plan_.pipeline]
            pstats = run_points_extract(cfg, dl, limit=max(1, len(ids)),
                                        dry_run=dry_run, llm=llm,
                                        entry_ids=ids)
            stats["pipeline"] = len(ids)
            stats["points_created"] += int(pstats.get("points_created") or 0)
            stats["pipeline_stats"] = {
                k: pstats.get(k) for k in
                ("processed", "chunked", "chunks_total", "points_rejected",
                 "gate_blocked", "pending_kpe", "errors")}
            for item in plan_.pipeline:
                if not dry_run:
                    _mark_meta(dl, item[0].id, {"route": "pipeline",
                                                "reason": "short_or_chunked",
                                                "at": now_iso})
            for err in pstats.get("errors", [])[:20]:
                stats["errors"].append(err)
                bad = dl.get_entry(str(err.get("entry_id") or "")) if not dry_run else None
                if bad is not None:
                    _mark_failure(dl, bad, str(err.get("error")),
                                  max_retries=cfg.ingest_max_retries, now=now_iso)

        # ---- KPE 通道（书 / 超长文档）----
        if plan_.kpe and dry_run:
            stats["kpe_planned"] = len(plan_.kpe)
        elif plan_.kpe:
            from .kpe_runner import run_kpe_for_entry

            for e, body in plan_.kpe:
                res = run_kpe_for_entry(cfg, dl, e, body, dry_run=dry_run)
                if res.get("status") == "ok":
                    stats["kpe"] += 1
                    stats["points_created"] += int(res.get("points") or 0)
                    if not dry_run:
                        _mark_meta(dl, e.id, {"route": "kpe",
                                              "reason": "pdf_book_or_large",
                                              "mode": res.get("mode"),
                                              "volumes": res.get("volumes"),
                                              "chunks": res.get("chunks"),
                                              "points": res.get("points"),
                                              "at": now_iso})
                else:
                    stats["errors"].append({"entry_id": e.id, "error": res.get("error")})
                    if not dry_run:
                        fails = _mark_failure(dl, e, str(res.get("error")),
                                              max_retries=cfg.ingest_max_retries,
                                              now=now_iso)
                        if fails > cfg.ingest_max_retries:
                            stats["dead"] += 1

        # ---- 老化（到点才跑；域闸门在 lifecycle 内部）----
        if do_aging and cfg.aging_auto and _aging_due(dl, cfg, now):
            from .lifecycle import run_lifecycle

            stats["aging"] = run_lifecycle(cfg, dl, limit=cfg.aging_limit_per_run,
                                           dry_run=dry_run,
                                           # 试跑不烧 LLM：A 段（版本型）零成本照样出计划
                                           llm=None if dry_run else LlmClient.from_config(cfg))
            if not dry_run:
                dl.log_task(now_iso, TASK, "aging", "all",
                            {k: v for k, v in stats["aging"].items()
                             if isinstance(v, (int, str, type(None)))})
    finally:
        dl.finish_run(run_id, {k: v for k, v in stats.items()
                               if k not in ("errors", "activate", "fetch",
                                            "pipeline_stats", "aging")}
                      | {"errors": len(stats["errors"])})
    return stats


__all__ = ["TASK", "activate_pending", "l0_guard", "run_ingest_pass"]