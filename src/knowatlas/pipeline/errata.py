"""勘误三级流水线（方案 §7.6，0.2.0 第六十四批，Phase 7 批次 65a）。

两级编排 + 附注层出口：
- L1 确定性扫描（run_errata_scan，零费用）：semantic/errata.check_text——
  完整 Python 代码块语法验证 + 已移除 API 对照表；命中直接 errata_flag=error
  进裁决队列（确定性错误无需 LLM 复核）；节选特征不下结论；
- L2 带依据核查（run_errata_check）：全库条目逐条问「该说法在当前版本是否
  仍然成立」（batch 20 单次调用，降级纪律同 aging_judge）；error 必须附
  可核查依据，给不出依据降级 suspect——**疑似不到确认级不出裁决队列**；
- L3 人裁（Web /api/entries/{id}/errata）：改正=勘误附注层（meta.errata
  追加，原文永不改写）or 废弃（同 64 出口：reject → 30 天冷却 → 物理删除）。

纪律：
- errata_flag=ok（用户否决）的条目 L1/L2 都不再标记（freshness 同口径）；
- 本批（65a）只落代码：L2 全量核查（技术类 ~600 条）须用户裁决模型档位后
  才跑（无人值守硬闸门：LLM 预算 ≤¥1 / 试跑 ≤10 条）；测试全用人造 fixture
  + LLM 替身，零真实 LLM 费用；L1 扫描零费用，真实库由用户下次 ksync
  --errata-scan 自然执行，本批不主动对真实库批量落标记。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ..semantic import errata
from ..semantic.base import TaskContext
from ..semantic.llm import LlmClient
from ..semantic.tasks import errata_check

CHECK_BATCH = 20   # 单次 LLM 调用的条目数（同 aging batch 20）
BODY_CAP = 4000    # 送 LLM 的单条正文字符上限（代码块对核查重要，同检索口径）


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _entry_body(dl: Any, entry: Any) -> str:
    """条目正文：inline_content 优先，缺了从 content_store 取（aging/points 同口径）。"""
    body = (entry.inline_content or "").strip()
    if not body and entry.content_hash:
        body = (dl.get_content(entry.content_hash) or "").strip()
    return body


# ---- L1：确定性扫描（零费用） ----

def run_errata_scan(dl: Any, dry_run: bool = False) -> dict[str, Any]:
    """L1 全库确定性错误扫描（freshness_scan 同构：无游标全量重扫，零费用）。

    候选=active+有正文，跳过 errata_flag=ok（用户否决）/待清理（value_flag=
    not_knowledge，已有更优先通道）/死链（link_status=dead，kcheck 通道）。
    命中打 meta.errata_flag=error + errata_kind + errata_reason。
    """
    entries = dl.list_entries(status="active", limit=10000)
    pool = [e for e in entries
            if e.meta.get("errata_flag") != "ok"
            and e.meta.get("value_flag") != "not_knowledge"
            and e.meta.get("link_status") != "dead"]
    by_kind: dict[str, int] = {}
    flagged: list[str] = []
    for e in pool:
        body = _entry_body(dl, e)
        if not body:
            continue
        findings = errata.check_text(body)
        if not findings:
            continue
        kinds = sorted({f["kind"] for f in findings})
        detail = "；".join(f["detail"] for f in findings)
        by_kind[kinds[0]] = by_kind.get(kinds[0], 0) + 1
        flagged.append(e.id)
        if not dry_run:
            dl.merge_meta(e.id, {"errata_flag": "error", "errata_kind": kinds[0],
                                 "errata_reason": detail,
                                 "errata_scanned_at": _now_iso()})
    stats = {"scan_total": len(entries), "scanned": len(pool), "error": len(flagged),
             "by_kind": by_kind, "dry_run": dry_run}
    dl.log_task(_now_iso(), "sync", "errata_scan", "all", stats)
    return stats


# ---- L2：带依据核查（LLM） ----

def run_errata_check(cfg: Any, dl: Any, limit: int = 10, dry_run: bool = False,
                     llm: Any = None) -> dict[str, Any]:
    """对候选条目跑一批 L2 事实核查；返回统计（CLI 打印 / 测试断言）。

    候选=active 且有正文且未经 L2 核查（errata_checked_at 游标幂等，重跑零
    重复）；limit 默认 10（试跑口径，全量核查须用户裁决模型档位——65b）。
    llm 参数为测试注入口；缺省从 cfg 构建（未启用 → skipped）。
    """
    if llm is None:
        llm = LlmClient.from_config(cfg)
    if llm is None:
        return {"skipped": "llm 未启用（[llm] enabled=false 或 key 未设）——"
                           "L2 核查是增强层，L1 确定性扫描不受影响"}
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "kerrata")
    stats: dict[str, Any] = {"run_id": run_id, "limit": limit, "dry_run": dry_run,
                             "candidates": 0, "processed": 0, "error": 0, "ok": 0,
                             "suspect": 0, "llm_calls": 0, "errors": []}
    try:
        pool = []
        for e in dl.list_entries(status="active", limit=10000):
            if e.meta.get("errata_checked_at") or e.meta.get("value_flag") == "not_knowledge":
                continue
            if not _entry_body(dl, e):
                continue
            pool.append(e)
        cand = pool[:max(1, limit)]
        stats["candidates"] = len(cand)
        stats["pool_remaining"] = max(0, len(pool) - len(cand))
        # batch 20：逐批单次 LLM 调用（同 aging §7.5 口径）
        for i in range(0, len(cand), CHECK_BATCH):
            chunk = cand[i:i + CHECK_BATCH]
            items = [{"entry_id": e.id, "title": e.title,
                      "body": _entry_body(dl, e)[:BODY_CAP]} for e in chunk]
            res = errata_check.run(items, TaskContext(run_id=run_id, llm=llm))
            if not res.get("llm_used"):
                stats["errors"].append({"chunk": i // CHECK_BATCH + 1,
                                        "error": res.get("error", "llm 未产出")})
                continue
            stats["llm_calls"] += 1
            for e in chunk:
                v = res["verdicts"].get(e.id)
                if v is None:
                    continue  # LLM 未覆盖该条 → 下次重跑自然补判
                _apply_verdict(dl, e, v, dry_run)
                stats["processed"] += 1
                stats[v["verdict"]] = stats.get(v["verdict"], 0) + 1
    finally:
        dl.finish_run(run_id, {k: v for k, v in stats.items() if k != "errors"} |
                      {"errors": len(stats["errors"])})
    return stats


def _apply_verdict(dl: Any, entry: Any, v: dict[str, Any], dry_run: bool) -> None:
    """结论落 meta：error 进裁决队列 / suspect 留观不出队 / ok 否决不再标。"""
    verdict = v["verdict"]
    patch: dict[str, Any] = {"errata_flag": verdict, "errata_kind": "llm_fact",
                             "errata_reason": v["reason"],
                             "errata_checked_at": _now_iso()}
    if v.get("evidence"):
        patch["errata_evidence"] = v["evidence"]
    if verdict == "ok":
        patch["errata_kind"] = None  # 否决不留错误类型脏键
    if not dry_run:
        dl.merge_meta(entry.id, patch)
        dl.log_task(_now_iso(), "kerrata", "llm_verdict", entry.id,
                    {"verdict": verdict, "reason": v["reason"][:200]})
