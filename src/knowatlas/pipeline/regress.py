"""回归集 runner（0.2.0 第五十一批，Phase 0.5 回归测试集 v0）。

用途：对人工确认的「条目 → 期望分类」对照集重跑自动分类链路，对比期望，
守住分类质量基线；通过率同时作为 Phase 4 LLM 兜底的基线记录
（TODO：LLM 兜底探针"回归集通过率记录在案"）。

口径：
- v0 只验证 L1 先验 + L2 规则层——ctx.llm 恒为 None 强制跳过 L3：
  用户 config 可能启用 LLM（llm.enabled=true），回归重跑绝不能烧 token；
  Phase 4 接入后在此处显式开 LLM 开关（接口不变，报告里加 origin 分布）；
- 判级三级：exact（与期望路径全等）/ prefix（一方是另一方的前缀，方向对
  但层级差半级）/ miss（无输出或 L0 价值守卫短路）；
- 正文取数：content_store 全量正文优先（与 kadd 分类时同源），缺则
  inline_content；
- 报告落 task_log（task_name=ktest, action=regress）。

种子来源：
- manual：Web UI 条目行「✓」按钮（把当前主分类确认为期望）；
- log_seed：历史 recategorize 动作回填——task_log 里 action='recategorize'
  的 detail.new_path 就是用户认可的正确分类（同条目多次改类取最后一次）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..datalayer.db import DataLayer
from ..semantic.base import SemanticInput, TaskContext
from ..semantic.tasks.classify_coarse import run as classify_run


def run_regress(dl: DataLayer, cfg: Any) -> dict[str, Any]:
    """对全量回归案例重跑 L1/L2 分类，输出三级判级报告（只读不写库）。"""
    cases = dl.list_regress_cases()
    known = frozenset(dl.all_category_paths())
    inputs: list[SemanticInput] = []
    for c in cases:
        meta = json.loads(c["meta"]) if isinstance(c["meta"], str) else dict(c["meta"] or {})
        body = None
        if c["content_hash"]:
            body = dl.get_content(c["content_hash"])
        inputs.append(SemanticInput(
            entry_id=c["entry_id"], title=c["title"],
            body=body or c["inline_content"],
            native_path=c["native_path"],
            meta={**meta, "source_type": c["source_type"],
                  "locator": c["locator"], "value_flag": meta.get("value_flag", "")},
        ))
    ctx = TaskContext(run_id="regress", known_paths=known, llm=None, config=cfg)
    outputs = classify_run(inputs, ctx) if inputs else []

    results: list[dict[str, Any]] = []
    n_exact = n_prefix = n_miss = 0
    for case, out in zip(cases, outputs):
        expected = case["expected_path"]
        if out.classifications:
            actual = out.classifications[0].category_path
            origin = out.classifications[0].origin
        elif out.tags and "not_knowledge" in out.tags:
            actual, origin = None, "value_guard"
        else:
            actual, origin = None, "none"
        if actual is not None and actual == expected:
            verdict = "exact"
            n_exact += 1
        elif actual is not None and (actual.startswith(expected + "/")
                                     or expected.startswith(actual + "/")):
            verdict = "prefix"
            n_prefix += 1
        else:
            verdict = "miss"
            n_miss += 1
        results.append({"entry_id": case["entry_id"], "title": case["title"],
                        "expected": expected, "actual": actual,
                        "origin": origin, "verdict": verdict})

    total = len(results)
    report = {
        "total": total,
        "exact": n_exact, "prefix": n_prefix, "miss": n_miss,
        "exact_rate": round(n_exact / total, 4) if total else None,
        "prefix_rate": round((n_exact + n_prefix) / total, 4) if total else None,
        "misses": [r for r in results if r["verdict"] == "miss"],
        "prefixes": [r for r in results if r["verdict"] == "prefix"],
    }
    dl.log_task(datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "ktest", "regress", "regress_cases",
                {"total": total, "exact": n_exact, "prefix": n_prefix,
                 "miss": n_miss})
    return report


def seed_from_log(dl: DataLayer, dry_run: bool = False) -> dict[str, Any]:
    """把历史 recategorize 动作回填进回归集（同条目取最后一次改类的 new_path）。"""
    rows = dl.list_task_log_actions("web", "recategorize")
    latest: dict[str, str] = {}
    for r in rows:
        detail = json.loads(r["detail"])
        new_path = str(detail.get("new_path", "")).strip().strip("/")
        if new_path:
            latest[r["target"]] = new_path
    seeded = 0
    if not dry_run:
        for entry_id, path in latest.items():
            dl.add_regress_case(entry_id, path, source="log_seed")
            seeded += 1
    return {"actions_seen": len(rows), "entries_seeded": seeded if not dry_run else len(latest),
            "dry_run": dry_run}
