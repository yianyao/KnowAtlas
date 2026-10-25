"""点分诊管道（P0，2026-10-25 裁决）：三分诊落库 + 领域闸门。

为什么要有这一层：勘误（P1）与老化（P2）只能判「可判定的硬事实」，否则等于花钱
去判观点/预测。分诊结论必须落库（`temp/` 随时可清空），且对 P3 重抽后的同文本点
自动继承（点以 `content_hash` 为稳定键）。

三件事，按代价从低到高：
1. `dupe` 判定是确定性的（`meta.dupe_of` 非空即可），零 LLM；
2. 已有分诊产物（`temp/errata_full_triage.json`，4,509 点）用 `seed_path` 直接导入，
   零 LLM——这是默认路径，别为了「新鲜」重花半小时与费用；
3. 只有既无 kind 又不在种子里（新入库点）才走 LLM（`point_triage` task），串行分批。

幂等：候选只取 `kind` 为空的点，写过的永不重判，重跑 = 零写入。
不写半成品：LLM 未启用 / 单批故障 → 该批一个 meta 都不写，只在 stats 里记账。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..semantic.llm import LlmClient
from ..semantic.tasks import point_triage
from ..semantic.base import TaskContext

#: 领域闸门（唯一出口）：勘误/老化只准吃 kind=hard 的点。P1/P2 请 import 这里，
#: 不要各自再写一份 SQL/判断，否则口径漂移会悄悄放观点进核查。
HARD_SQL = "COALESCE(json_extract(p.meta,'$.kind'),'') = 'hard'"

DUPE_WHY = "meta.dupe_of 重复点：消费面已去重，不参与勘误/老化"

TRIAGE_KINDS = point_triage.KINDS


def is_hard(meta: dict[str, Any] | None) -> bool:
    """点 meta 是否属于「可判定硬事实」（领域闸门）。"""
    return str((meta or {}).get("kind") or "").strip() == "hard"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_seed(seed_path: Path) -> dict[str, dict[str, Any]]:
    """读既有分诊产物 `{point_id: {kind, why}}`；坏文件当空种子（不阻断确定性部分）。"""
    try:
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def _write_kind(dl: Any, point_id: str, kind: str, why: str, model: str,
                now: str) -> None:
    """落分诊结论（浅合并）+ 审计留痕。kind 是机器后处理键，见 db.py 保护说明。"""
    dl.merge_meta_of_point(point_id, {"kind": kind, "kind_why": why[:200],
                                      "kind_at": now, "kind_model": model})
    dl.log_task(now, "points", "triage", point_id,
                {"kind": kind, "why": why[:120], "model": model})


def run_point_triage(cfg: Any, dl: Any, *, limit: int = 0, dry_run: bool = False,
                     seed_path: str | Path | None = None, batch: int = 30,
                     llm: Any = None) -> dict[str, Any]:
    """三分诊落库。返回统计（含 `llm_skipped` 时调用方据此决定退出码）。

    - `limit`：本次最多处理多少条点（0=不限；种子导入与 dupe 标记都算在内）；
    - `seed_path`：既有分诊 JSON（`{point_id: {kind, why}}`），命中即确定性写库；
    - `batch`：LLM 每批点数（沿用实测 30/批的口径）。
    """
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "kpoints")
    now = _now_iso()
    stats: dict[str, Any] = {
        "run_id": run_id, "dry_run": dry_run, "limit": limit, "batch": batch,
        "candidates": 0, "dupes_marked": 0, "imported": 0, "triaged": 0,
        "seed_missing": 0, "llm_calls": 0, "llm_skipped": None,
        "kinds": {}, "errors": [],
    }

    def _bump(kind: str) -> None:
        kinds = stats["kinds"]
        kinds[kind] = kinds.get(kind, 0) + 1

    try:
        cands = dl.points_without_kind(limit=0, include_dupes=True)
        # 先过 limit（按 created_at 顺序，与抽取顺序一致），干跑也照此口径计数
        if limit and limit > 0:
            cands = cands[:limit]
        stats["candidates"] = len(cands)
        if not cands:
            return stats

        dupes = [c for c in cands if c["meta"].get("dupe_of")]
        normals = [c for c in cands if not c["meta"].get("dupe_of")]

        for c in dupes:
            if not dry_run:
                _write_kind(dl, c["id"], "dupe", DUPE_WHY, "rule:dupe_of", now)
            stats["dupes_marked"] += 1
            _bump("dupe")

        seed = _load_seed(Path(seed_path)) if seed_path else {}
        seeded: set[str] = set()
        for c in normals:
            hit = seed.get(c["id"])
            if not hit:
                if seed:
                    stats["seed_missing"] += 1
                continue
            kind = str(hit.get("kind") or "").strip().lower()
            if kind not in TRIAGE_KINDS:
                if seed:
                    stats["seed_missing"] += 1
                continue
            why = str(hit.get("why") or "").strip()
            model = f"seed:{Path(seed_path).name}"
            if not dry_run:
                _write_kind(dl, c["id"], kind, why, model, now)
            stats["imported"] += 1
            seeded.add(c["id"])
            _bump(kind)

        rest = [c for c in normals if c["id"] not in seeded]
        if rest:
            if llm is None and cfg is not None:
                llm = LlmClient.from_config(cfg)
            if llm is None:
                stats["llm_skipped"] = ("llm 未启用（[llm] enabled=false 或 key 未设）——"
                                        "剩余点未分诊，可稍后重跑；确定性部分已落库")
            else:
                model = getattr(llm, "model_name", "") or "llm"
                for i in range(0, len(rest), max(1, batch)):
                    b = rest[i:i + max(1, batch)]
                    items = [{"point_id": c["id"], "text": c["text"]} for c in b]
                    res = point_triage.run(items, TaskContext(run_id=run_id, llm=llm))
                    stats["llm_calls"] += 1
                    if res.get("error"):
                        stats["errors"].append(res["error"])
                        continue
                    for pid, got in res.get("kinds", {}).items():
                        if pid not in {x["id"] for x in b}:
                            continue
                        if not dry_run:
                            _write_kind(dl, pid, got["kind"], got.get("why", ""),
                                        model, now)
                        stats["triaged"] += 1
                        _bump(got["kind"])
    finally:
        dl.finish_run(run_id, {k: v for k, v in stats.items()
                               if k not in ("errors", "kinds")} |
                      {"errors": len(stats["errors"]), "kinds": stats["kinds"]})
    return stats