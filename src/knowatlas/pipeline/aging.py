"""老化三级流水线（方案 §7.5，0.2.0 第六十三批，Phase 7 批次 64a）。

两级编排：
- L2 判定（run_aging_judgment）：L1 规则（ksync --freshness-scan）标出的 suspect
  逐条 LLM 复核（batch 20，结论 stale 升级 / ok 否决 / keep 维持下沉人裁）；
- L3 删除出口（sweep_rejections）：人裁废弃（Web 舍弃按钮 → 即刻 rejected 全面
  不可见）→ 30 天冷却（误裁反悔窗口，restore 清 rejected_at）→ 冷却期满自动
  物理删除（ksync 顺手执行；content_store 按引用计数回收——共享内容块只减
  计数，删到零才清正文；task_log 审计留痕）。

纪律：
- 删除出口只吃「人裁」的 rejected 条目（status=rejected 且 meta.rejected_at 超
  冷却期）；无 rejected_at 的历史 rejected 条目不删（非本机制裁决，不自动清）；
- 本批（64a）只落代码：全量 suspect 判定（现库 ~87 条）与任何真实库删除均须
  用户在场裁决（无人值守硬闸门）；测试全用人造 fixture（临时库），LLM 用替身。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ..semantic.base import TaskContext
from ..semantic.llm import LlmClient
from ..semantic.tasks import aging_judge, point_aging

AGING_BATCH = 20   # 单次 LLM 调用的条目数（方案 §7.5：batch 20）
BODY_CAP = 3000    # 送 LLM 的单条正文字符上限（控成本；截断不计数——规则信号已含日期）


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_aging_judgment(cfg: Any, dl: Any, limit: int = 10, dry_run: bool = False,
                       llm: Any = None) -> dict[str, Any]:
    """对 suspect 条目跑一批 L2 时效复核；返回统计（CLI 打印 / 测试断言）。

    候选=status=active 且 freshness_flag=suspect 且未经 L2 复核（aging_checked_at
    游标幂等，重跑零重复）；limit 默认 10（试跑口径，全量判定须用户裁决）。
    llm 参数为测试注入口；缺省从 cfg 构建（未启用 → skipped）。
    """
    if llm is None:
        llm = LlmClient.from_config(cfg)
    if llm is None:
        return {"skipped": "llm 未启用（[llm] enabled=false 或 key 未设）——"
                           "L2 复核是增强层，主链路不受影响"}
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "kaging")
    stats: dict[str, Any] = {"run_id": run_id, "limit": limit, "dry_run": dry_run,
                             "candidates": 0, "processed": 0, "stale": 0, "ok": 0,
                             "keep": 0, "llm_calls": 0, "errors": []}
    try:
        pool = [e for e in dl.list_by_freshness_flag("suspect", limit=500)
                if not e.meta.get("aging_checked_at")]
        cand = pool[:max(1, limit)]
        stats["candidates"] = len(cand)
        stats["pool_remaining"] = max(0, len(pool) - len(cand))
        # batch 20：逐批单次 LLM 调用（方案 §7.5）
        for i in range(0, len(cand), AGING_BATCH):
            chunk = cand[i:i + AGING_BATCH]
            items = [{"entry_id": e.id, "title": e.title,
                      "freshness_reason": e.meta.get("freshness_reason", ""),
                      "body": _entry_body(dl, e)[:BODY_CAP]} for e in chunk]
            res = aging_judge.run(items, TaskContext(run_id=run_id, llm=llm))
            if not res.get("llm_used"):
                stats["errors"].append({"chunk": i // AGING_BATCH + 1,
                                        "error": res.get("error", "llm 未产出")})
                continue
            stats["llm_calls"] += 1
            for e in chunk:
                v = res["verdicts"].get(e.id)
                if v is None:
                    continue  # LLM 未覆盖该条 → 维持 suspect，下次重跑自然补判
                _apply_verdict(dl, e, v, dry_run)
                stats["processed"] += 1
                stats[v["verdict"]] = stats.get(v["verdict"], 0) + 1
    finally:
        # finish_run 兜底：中途异常也留痕（errors 计数，不丢明细）
        dl.finish_run(run_id, {k: v for k, v in stats.items() if k != "errors"} |
                      {"errors": len(stats["errors"])})
    return stats


def _entry_body(dl: Any, entry: Any) -> str:
    """条目正文：inline_content 优先，缺了从 content_store 取（与 points 同口径）。"""
    body = (entry.inline_content or "").strip()
    if not body and entry.content_hash:
        body = (dl.get_content(entry.content_hash) or "").strip()
    return body


def _apply_verdict(dl: Any, entry: Any, v: dict[str, Any], dry_run: bool) -> None:
    """结论落 meta：stale 升级（退出消费面）/ ok 否决（规则不再标记）/ keep 维持。"""
    verdict = v["verdict"]
    patch: dict[str, Any] = {"aging_verdict": verdict, "aging_reason": v["reason"],
                             "aging_suggest": v.get("suggest", ""),
                             "aging_checked_at": _now_iso()}
    if verdict == "stale":
        patch["freshness_flag"] = "stale"
    elif verdict == "ok":
        patch["freshness_flag"] = "ok"
    if not dry_run:
        dl.merge_meta(entry.id, patch)
        dl.log_task(_now_iso(), "kaging", "llm_verdict", entry.id,
                    {"verdict": verdict, "reason": v["reason"][:200]})


def sweep_rejections(dl: Any, dry_run: bool = False) -> dict[str, Any]:
    """L3 删除出口清扫：冷却期满（30 天）的 rejected 条目物理删除。

    db 层实现见 DataLayer.sweep_expired_rejections（引用计数回收 + 审计留痕）；
    本包装补一条任务日志汇总。ksync 主流程每轮顺手调用（无人值守口径下
    只有人裁过的条目会进冷却，物理删除=用户裁决的执行而非自动决策）。
    """
    stats = dl.sweep_expired_rejections(dry_run=dry_run)
    if not dry_run and stats["swept"]:
        dl.log_task(_now_iso(), "kaging", "sweep", "all",
                    {"swept": len(stats["swept"]),
                     "content_recycled": stats["content_recycled"]})
    return stats


# ---- 点级老化（批次 93，裁决 #14「只老化确实过时的部分点」） ----

def run_point_aging(cfg: Any, dl: Any, limit: int = 10, dry_run: bool = False,
                    llm: Any = None) -> dict[str, Any]:
    """对「溯源条目被标 suspect/stale」且未复核过的点跑 LLM 点级复核。

    候选 = 点的任一溯源条目 freshness_flag in (suspect, stale) 且点
    aging_checked_at=''（ok 免疫复扫；keep 留观不重扫）。条目过时不连坐点：
    LLM 只看点文本本身判定（point_aging task）；结论落点级三列（stale 退出
    消费面 / ok 免疫 / keep 留观），永不物理删除点。
    """
    if llm is None:
        llm = LlmClient.from_config(cfg)
    if llm is None:
        return {"skipped": "llm 未启用（[llm] enabled=false 或 key 未设）——"
                           "点级复核是增强层，主链路不受影响"}
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "kaging")
    stats: dict[str, Any] = {"run_id": run_id, "limit": limit, "dry_run": dry_run,
                             "candidates": 0, "stale": 0, "ok": 0, "keep": 0,
                             "llm_calls": 0, "errors": []}
    try:
        rows = dl._conn.execute(
            "SELECT DISTINCT p.id AS point_id, p.text, "
            " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS title, "
            " COALESCE(json_extract(e.meta,'$.freshness_flag'), '') AS entry_flag"
            " FROM points p"
            " JOIN point_sources ps ON ps.point_id = p.id"
            " JOIN entries e ON e.id = ps.entry_id"
            " WHERE p.aging_checked_at = ''"
            "   AND e.status = 'active'"
            "   AND COALESCE(json_extract(e.meta,'$.freshness_flag'), '')"
            "       IN ('suspect', 'stale')"
            " ORDER BY p.created_at LIMIT ?",
            (limit,),
        ).fetchall()
        stats["candidates"] = len(rows)
        if not rows:
            return stats
        items = [{"point_id": r["point_id"], "text": r["text"],
                  "entry_signal": f"来源《{r['title']}》被标 {r['entry_flag']}"}
                 for r in rows]
        res = point_aging.run(items, TaskContext(run_id=run_id, llm=llm))
        if res.get("error"):
            stats["errors"].append(res["error"])
            return stats
        stats["llm_calls"] = 1
        verdicts = res.get("verdicts", {})
        for it in items:
            pid = it["point_id"]
            v = verdicts.get(pid)
            if v is None:
                stats["keep"] += 1          # LLM 漏判 → 留观（只记游标）
                if not dry_run:
                    dl.set_point_aging(pid, "", "未获结论留观（漏判）")
                continue
            verdict = v["verdict"]
            stats[verdict] = stats.get(verdict, 0) + 1
            if not dry_run:
                # keep 只记游标不写 flag（维持未判，信号更新后可复扫）
                dl.set_point_aging(pid, verdict if verdict != "keep" else "",
                                   v["reason"])
    finally:
        dl.finish_run(run_id, {k: v for k, v in stats.items() if k != "errors"} |
                      {"errors": len(stats["errors"])})
    return stats
