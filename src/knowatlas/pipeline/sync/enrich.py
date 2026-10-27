"""pipeline/sync/enrich.py（拆分产物）。"""

# 拆分自 pipeline/sync.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


from typing import Any
from ...models import Entry, FetchResult
from ...semantic.base import SemanticInput, TaskContext
from ..kadd import ensure_category_path
from .flags import _flag_value, _now_iso


def _categorize(dl: Any, semantics: Any, cfg: Any, entries: list[Entry], new_ids: set[str],
                updated_ids: set[str], run_id: str,
                pending_ids: frozenset[str] | set[str] = frozenset()) -> dict[str, int]:
    """对本次新建/更新条目批量跑 classify_coarse；未命中进暂存区（不挂分类）。

    更新条目（书签移动文件夹、标题变化等）先 detach 机器来源（origin != manual）
    的旧挂接再重挂——人工校正（origin=manual）永不覆盖（H3）。
    L3 LLM：cfg 的 [llm] 启用且 key 已设时自动生效，否则静默跳过。
    """
    targets = [e for e in entries
               if (e.id in new_ids or e.id in updated_ids)
               and e.id not in pending_ids]  # pending 缓冲（批次 68）：不烧分类费
    if not targets:
        return {"classified": 0, "staged": 0, "reclassified": 0}
    _, classify = semantics.resolve_task("classify_coarse")
    from ...semantic.llm import LlmClient

    known = frozenset(dl.all_category_paths())
    inputs = [
        SemanticInput(entry_id=e.id, title=e.title, body=e.inline_content,
                      native_path=e.native_path,
                      meta={**e.meta, "locator": e.locator})
        for e in targets
    ]
    outputs = classify(inputs, TaskContext(run_id=run_id, known_paths=known,
                                           llm=LlmClient.from_config(cfg), config=cfg,
                                           datalayer=dl))
    classified = staged = flagged = 0
    for entry, out in zip(targets, outputs):
        if _flag_value(dl, entry, out):
            flagged += 1
        if entry.id in updated_ids:
            # 旧机器分类清理：书签换文件夹等场景下避免新旧分类并存
            for link in dl.get_entry_categories(entry.id):
                if link["origin"] != "manual":
                    dl.detach_category(entry.id, link["category_id"])
        if not out.classifications:
            staged += 1
            continue
        for classification in out.classifications:
            cid = ensure_category_path(dl, classification.category_path, classification.origin)
            dl.attach_category(entry.id, cid, classification.confidence,
                               classification.origin, run_id)
        classified += 1
    return {"classified": classified, "staged": staged,
            "reclassified": sum(1 for e in targets if e.id in updated_ids),
            "flagged_not_knowledge": flagged}


def _reclassify_all(cfg: Any, dl: Any, semantics: Any, run_id: str) -> dict[str, Any]:
    """全量重分类：active 条目重跑 classify_coarse 三级流水线。

    语义（0.2.0 修正，用户反馈"LLM 不该顺手归并残留类目"）：
    - 先统一 detach 全部机器分类；候选路径（known_paths）只保留**人工挂接**的分类——
      LLM 的类目候选由用户认可的类目决定，不再被旧机器类目 anchor；
    - 含人工挂接的条目整条跳过（人工结论优先，H3）；
    - 重跑后自动清理空壳机器类目（无条目、无子类、origin != manual）；
    - [llm] 未启用 / key 未设时 L3 静默跳过，结果 = 先验+规则（stats.llm_used=false）。
    """
    from ...semantic.base import SemanticInput, TaskContext
    from ...semantic.llm import LlmClient

    llm = LlmClient.from_config(cfg)
    _, classify = semantics.resolve_task("classify_coarse")
    entries = dl.list_entries(status="active", limit=10000)
    # 含人工挂接的条目跳过；其余先统一摘除机器分类
    # 1) detach 前清理真·空壳（历史遗留、无挂接无子类且非人工）
    dropped = dl.delete_empty_categories()
    # 1.5) 碎片收拢：单条目的机器二级类目并入一级（树由内容聚出来，2026-10-19 用户定调）
    moved = dl.prune_fragment_categories(min_size=2)
    if moved:
        dl.log_task(_now_iso(), "sync", "prune_fragments", "auto",
                    {"count": len(moved), "names": [m["name"] for m in moved]})
    # 2) 快照大类骨架：detach 前有真实条目支撑的一级类目（防待清理类目混入候选）
    root_names = {n["name"] for n in dl.get_tree()}
    # 3) 摘除全部机器分类
    targets: list[Entry] = []
    for e in entries:
        links = dl.get_entry_categories(e.id)
        if any(l["origin"] == "manual" for l in links):
            continue
        targets.append(e)
        for link in links:
            dl.detach_category(e.id, link["category_id"])
    # 候选 = 人工挂接路径 ∪ 大类骨架（完整旧路径不进候选，防顺手归并碎片类目）
    known = frozenset(dl.manual_category_paths() | root_names)
    classified = staged = flagged = 0
    max_batch = int(cfg.get("llm.max_batch", 20) or 20)
    for i in range(0, len(targets), max_batch):
        chunk = targets[i:i + max_batch]
        outputs = classify(
            [SemanticInput(entry_id=e.id, title=e.title, body=e.inline_content,
                           native_path=e.native_path,
                           meta={**e.meta, "locator": e.locator}) for e in chunk],
            TaskContext(run_id=run_id, known_paths=known, llm=llm, config=cfg,
                        datalayer=dl),
        )
        for e, out in zip(chunk, outputs):
            if _flag_value(dl, e, out):
                flagged += 1
            if not out.classifications:
                staged += 1
                continue
            for classification in out.classifications:
                cid = ensure_category_path(dl, classification.category_path,
                                           classification.origin)
                dl.attach_category(e.id, cid, classification.confidence,
                                   classification.origin, run_id)
            classified += 1
    dropped = dl.delete_empty_categories()
    # 分类后再收拢一次：本轮 LLM 新产生的单条目碎片也并入一级
    moved = dl.prune_fragment_categories(min_size=2)
    if moved:
        dl.log_task(_now_iso(), "sync", "prune_fragments", "auto",
                    {"count": len(moved), "names": [m["name"] for m in moved]})
    if dropped:
        dl.log_task(_now_iso(), "sync", "drop_empty_categories", ",".join(d[0] for d in dropped),
                    {"names": [d[1] for d in dropped], "count": len(dropped)})
    stats = {"reclassify_total": len(targets), "classified": classified,
             "staged": staged, "llm_used": llm is not None,
             "dropped_empty_categories": [d[1] for d in dropped],
             "pruned_fragments": len(moved), "flagged_not_knowledge": flagged}
    dl.log_task(_now_iso(), "sync", "reclassify", "all",
                {k: v for k, v in stats.items()})
    return stats


def _value_scan(dl: Any, dry_run: bool) -> dict[str, Any]:
    """价值体检（L0 价值守卫，零费用）：扫全部 active 条目的 URL 结构，
    命中「资源直链/站点首页/列表子页」即置 meta.value_flag=not_knowledge
    + value_flag_reason，进 Web UI 待清理候选（仅标记，舍弃决定权在用户）。

    与 --reclassify 的分工：不重跑分类、不动分类树、不调 LLM、零费用——
    存量条目的非知识标记用这条通道补，不必为打标重型跑一遍全量重分类。
    - value_flag=ok（用户否决）与已 rejected 的条目跳过；
    - 已被 LLM 标记过但缺 reason 的条目只补 reason，不重复计数；
    - dry_run=True 只出报告不写库。

    P5（2026-10-26）：URL 结构判不出来时补一道正文层判据 `is_index_page`
    （表格式书目/索引页，reason="index_page"）。只读条目自带的内联正文
    （`inline_content`，≤4000 字），不读 content_store——零额外 IO。
    """
    from ...semantic.value_guard import is_index_page, judge_value

    entries = dl.list_entries(status="active", limit=10000)
    by_reason: dict[str, int] = {}
    flagged = reasons_filled = 0
    for e in entries:
        if e.meta.get("value_flag") == "ok":
            continue
        reason = judge_value(e.locator)
        if reason is None and is_index_page(e.inline_content or ""):
            reason = "index_page"
        if reason is None:
            continue
        by_reason[reason] = by_reason.get(reason, 0) + 1
        if e.meta.get("value_flag") == "not_knowledge":
            if e.meta.get("value_flag_reason") != reason:
                if not dry_run:
                    dl.merge_meta(e.id, {"value_flag_reason": reason})
                reasons_filled += 1
            continue
        flagged += 1
        if not dry_run:
            dl.merge_meta(e.id, {"value_flag": "not_knowledge",
                                 "value_flag_reason": reason})
    stats = {"value_scan_total": len(entries), "new_flagged": flagged,
             "matched_total": sum(by_reason.values()),
             "reasons_filled": reasons_filled, "by_reason": by_reason,
             "dry_run": dry_run}
    dl.log_task(_now_iso(), "sync", "value_scan", "all", stats)
    return stats


def _freshness_scan(dl: Any, dry_run: bool) -> dict[str, Any]:
    """时效体检（freshness guard，零费用）：纯规则标记「过期的、容易误导的知识」。

    单条信号（semantic/freshness.judge_text）+ 跨条目信号（同 host 同主题新旧
    并存）。命中打 meta.freshness_flag=stale/suspect + freshness_reason +
    freshness_checked_at，进 Web UI 时效候选（仅标记，清理决定权在用户）。
    - freshness_flag=ok（用户否决）的条目跳过，二次扫描不翻转（value_flag 同口径）；
    - 已在待清理候选（value_flag=not_knowledge）与已死链（link_status=dead）的
      条目跳过——它们已有更优先的清理通道，重复打标徒增噪音；
    - dry_run=True 只出报告不写库。
    """
    from ...semantic.freshness import extract_latest_year, judge_text, title_key

    def _body(e: Any) -> str:
        inline = e.inline_content or ""
        if e.content_hash:
            stored = dl.get_content_preview(e.content_hash, 5000) or ""
            return inline[:2000] + "\n" + stored[:5000]
        return inline[:5000]

    def _flagged(e: Any, flag: str, reason: str) -> None:
        by_reason[reason] = by_reason.get(reason, 0) + 1
        if not dry_run:
            dl.merge_meta(e.id, {"freshness_flag": flag, "freshness_reason": reason,
                                 "freshness_checked_at": _now_iso()})

    entries = dl.list_entries(status="active", limit=10000)
    scan_pool = [e for e in entries
                 if e.meta.get("freshness_flag") != "ok"
                 and e.meta.get("value_flag") != "not_knowledge"
                 and e.meta.get("link_status") != "dead"]
    by_reason: dict[str, int] = {}
    stale = suspect = 0

    # 单条信号：keyword → stale / date_old → suspect
    judged: dict[str, tuple[str, str]] = {}   # entry_id -> (flag, reason)
    for e in scan_pool:
        verdict = judge_text(e.title, _body(e))
        if verdict is not None:
            judged[e.id] = verdict

    # 跨条目信号：同 host 同主题组内 ≥2 条，更旧的补 suspect/newer_version
    # （date_old/keyword 已 stale 的不降级覆盖；同分并列不判新旧）
    from urllib.parse import urlsplit
    groups: dict[tuple[str, str], list[Any]] = {}
    for e in scan_pool:
        loc = str(e.locator or "")
        try:
            parts = urlsplit(loc)
        except ValueError:
            continue
        if parts.scheme not in ("http", "https") or not parts.netloc:
            continue
        key = title_key(e.title)
        if key:
            groups.setdefault((parts.netloc.lower(), key), []).append(e)
    for members in groups.values():
        if len(members) < 2:
            continue

        def _date_of(e: Any) -> str:
            yr = extract_latest_year(_body(e))
            return str(yr) if yr else (e.created_at or "9999")

        ordered = sorted(members, key=lambda e: (_date_of(e), e.id))
        newest_date = _date_of(ordered[-1])
        for e in ordered[:-1]:
            if _date_of(e) == newest_date:
                continue  # 与最新并列：分不出新旧，不判（id 只作排序稳定用）
            if e.id not in judged:  # 已 stale/suspect 的保持更重结论
                judged[e.id] = ("suspect", "newer_version")

    for e in scan_pool:
        verdict = judged.get(e.id)
        if verdict is None:
            continue
        if verdict[0] == "stale":
            stale += 1
        else:
            suspect += 1
        _flagged(e, verdict[0], verdict[1])

    stats = {"freshness_scan_total": len(entries), "scanned": len(scan_pool),
             "stale": stale, "suspect": suspect,
             "by_reason": by_reason, "dry_run": dry_run}
    dl.log_task(_now_iso(), "sync", "freshness_scan", "all", stats)
    return stats
