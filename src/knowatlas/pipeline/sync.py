"""同步编排（完整方案 §3.6）。

两类同步策略：
- 全量遍历型（bookmark/folder/emmx/bili/session/db/wx 文件产物）：全量拉取 + 幂等 upsert
  + 删除检测（full=True 时 missing_in_source → archived）——按 M1 起逐个接入；
- 游标型（mail/ima/txdoc）：各自游标增量，M3 起接入。

已接入批量源：bookmarks（adapters/bookmark.py）。

纪律：
- K1：同步默认不抓正文（fetch.on_sync=false）——--fetch-limit N 显式开启，本次最多 N 条
  缺正文的 http 条目走 fetch_with_fallback 补抓；
- 分类只跑 classify_coarse（L0 价值守卫 + L1 先验 + L2 规则 + L3 LLM，未命中进暂存区，
  绝不硬猜），且只对本次新建条目执行——unchanged 条目幂等跳过，不重复挂分类；
- --value-scan：只跑 L0 价值守卫给存量条目打标（零费用，不动分类树）；
- 适配器抛 AdapterError → 跳过该源、其余源继续（完整方案 §10.1）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ..adapters.bookmark import collect_bookmarks
from ..adapters.emmx import collect_emmx
from ..adapters.folder import collect_folders
from ..adapters.maildir import collect_maildirs
from ..errors import AdapterError, DegradedParseError, FetchError
from ..ids import content_hash
from ..models import Entry, FetchResult
from ..registry.capability import FetchContext
from ..semantic.base import SemanticInput, TaskContext
from .kadd import ensure_category_path
from .dedupe import dedupe_entries, scan_and_merge
from .mail_threads import rebuild_mail_threads

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

# 全量遍历型批量源注册：源配置名 → 收集函数（新批量源 = 一行 + 适配器文件）
_BATCH_COLLECTORS: dict[str, Any] = {
    "bookmarks": collect_bookmarks,
    "folders": collect_folders,
    "emmx": collect_emmx,
    "mail": collect_maildirs,
}
# 配置名 → source_type（archive_missing 按条目来源类型做删除检测）
_SOURCE_TYPE_BY_NAME: dict[str, str] = {
    "bookmarks": "bookmark", "folders": "folder", "emmx": "emmx", "mail": "mail"}

_INLINE_LIMIT = 4096
_TRUNCATED_AT = 4000

# 与 datalayer.db._SOURCE_FIELDS 保持一致（upsert 的 updated 判定字段）——
# 改动任一处必须同步另一处并跑全量测试
_SOURCE_FIELDS = ("title", "locator", "locator_canonical", "native_path",
                  "inline_content", "content_hash", "created_at")


def _flag_value(dl: Any, entry: Entry, out: Any) -> bool:
    """把「非知识」结论落进 meta（value_flag=not_knowledge + value_flag_reason）。

    tag 来源两条路：L0 价值守卫（value_guard，结构性规则，带 reason）与 LLM
    kind=non（classify_deep，语义判断，无 reason）——统一经本函数落库，语义同构。
    返回是否本次新标记（已标记 / 用户已否决 value_flag=ok 的不重复写）。
    用户否决以**库中** meta 为准（采集器产出的 entry.meta 不含后处理键，
    同步路径必须读库才能看到 Web UI 里点过的「是知识，保留」）。
    保留决定权在用户：仅标记，不自动舍弃（not_knowledge 只进待清理候选）。
    """
    if "not_knowledge" not in out.tags:
        return False
    current = dl.get_entry(entry.id)
    if current is not None and current.meta.get("value_flag") == "ok":
        return False  # 用户已否决——机器结论不再覆盖人的决定
    reason = next((t.split(":", 1)[1] for t in out.tags
                   if t.startswith("value_reason:")), None)
    if current is not None and current.meta.get("value_flag") == "not_knowledge":
        if reason and current.meta.get("value_flag_reason") != reason:
            dl.merge_meta(entry.id, {"value_flag_reason": reason})  # 旧 LLM 标记补原因
        return False
    patch: dict[str, Any] = {"value_flag": "not_knowledge"}
    if reason:
        patch["value_flag_reason"] = reason
    dl.merge_meta(entry.id, patch)
    return True


def _categorize(dl: Any, semantics: Any, cfg: Any, entries: list[Entry], new_ids: set[str],
                updated_ids: set[str], run_id: str) -> dict[str, int]:
    """对本次新建/更新条目批量跑 classify_coarse；未命中进暂存区（不挂分类）。

    更新条目（书签移动文件夹、标题变化等）先 detach 机器来源（origin != manual）
    的旧挂接再重挂——人工校正（origin=manual）永不覆盖（H3）。
    L3 LLM：cfg 的 [llm] 启用且 key 已设时自动生效，否则静默跳过。
    """
    targets = [e for e in entries if e.id in new_ids or e.id in updated_ids]
    if not targets:
        return {"classified": 0, "staged": 0, "reclassified": 0}
    _, classify = semantics.resolve_task("classify_coarse")
    from ..semantic.llm import LlmClient

    known = frozenset(dl.all_category_paths())
    inputs = [
        SemanticInput(entry_id=e.id, title=e.title, body=e.inline_content,
                      native_path=e.native_path,
                      meta={**e.meta, "locator": e.locator})
        for e in targets
    ]
    outputs = classify(inputs, TaskContext(run_id=run_id, known_paths=known,
                                           llm=LlmClient.from_config(cfg), config=cfg))
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


def _apply_content(entry: Entry, text: str, content_hash_hex: str,
                   fetcher: str, fetched_at: str) -> Entry:
    """补抓成功后重建条目（同 id upsert 更新正文；截断规则与 manual 源一致）。"""
    inline: str | None
    if len(text) <= _INLINE_LIMIT:
        inline = text
    else:
        inline = text[:_TRUNCATED_AT] + "…[截断，全文在 content_store]"
    meta = dict(entry.meta)
    meta["fetch_backend"] = fetcher
    meta["fetched_at"] = fetched_at
    meta["fetch_status"] = "ok"
    return Entry(
        id=entry.id, source_type=entry.source_type, title=entry.title,
        locator=entry.locator, locator_canonical=entry.locator_canonical,
        native_path=entry.native_path, inline_content=inline,
        content_hash=content_hash_hex, meta=meta, created_at=entry.created_at,
        exported_at=entry.exported_at, status=entry.status,
    )


def _is_timeout(exc: Exception) -> bool:
    """超时类错误判定（httpx 措辞 "timed out" / "timeout"）——只有超时才值得重试。"""
    s = str(exc).lower()
    return "timed out" in s or "timeout" in s


def _clear_stale_fetch_flags(dl: Any, fetched_ids: list[str]) -> None:
    """清除过时的 fetch 失败打标（0.2.0 第二十八批）。

    补抓成功 = 旧「解析失败/不可达/乱码」结论作废，条目不该继续留在待清理候选。
    upsert 的 meta 合并语义（{**旧,**新}）会保留库中旧键，必须显式删（merge_meta
    None=删键）。用户否决 value_flag=ok 与 L0 结构规则（URL 形态，与抓取无关）
    不动——L0 reason 不属 fetch 失败三因，不会命中。
    """
    for eid in fetched_ids:
        patch: dict[str, Any] = {"fetch_error": None}
        stored = dl.get_entry(eid)
        # 必须是机器打标（value_flag=not_knowledge）才清——用户否决 value_flag=ok
        # 时 reason 可能仍是旧 fetch 失败三因（ok 覆盖了 flag 但 reason 残留），
        # 人的决定优先，不得清。
        if (stored and stored.meta.get("value_flag") == "not_knowledge"
                and stored.meta.get("value_flag_reason") in (
                    "unparseable", "unreachable", "garbled")):
            patch["value_flag"] = None
            patch["value_flag_reason"] = None
        dl.merge_meta(eid, patch)


def _fetch_missing(cfg: Any, dl: Any, locators: Any, entries: list[Entry],
                   limit: int, run_id: str) -> dict[str, int]:
    """K1 显式补抓：对缺正文的 http(s)/file 条目抓取，最多尝试 limit 次；失败计数不中断。

    用户铁律（2026-10-20）：不可达、解析不出、乱码——总之「不是具体的、用不了的知识
    等于没有」→ 抓取失败/乱码的条目直接打 not_knowledge（value_flag_reason 注明原因）
    进待清理候选；用户 value_flag=ok 否决的照旧不覆盖（_flag_value 读库判定）。
    limit 是**尝试次数**上限（不是成功数）——失败大多不计费，但要防一轮跑太久。
    """
    import httpx
    from datetime import datetime
    from types import SimpleNamespace

    from ..fetchers.base import fetch_with_fallback
    from ..semantic.value_guard import is_garbled

    done = failed = attempts = 0
    fetched_ids: list[str] = []
    ctx = FetchContext(config=cfg, datalayer=dl, http=httpx.Client(), run_id=run_id)
    updates: list[Entry] = []

    def _flag(entry: Entry, reason: str, err: str | None = None) -> None:
        """失败/乱码 → 待清理候选（reason 进 value_flag_reason）；附 fetch_status 供诊断。"""
        nonlocal failed
        failed += 1
        _flag_value(dl, entry, SimpleNamespace(tags=["not_knowledge", f"value_reason:{reason}"]))
        patch: dict[str, Any] = {"fetch_status": reason}
        if err:
            patch["fetch_error"] = err[:120]
        dl.merge_meta(entry.id, patch)

    for e in entries:
        if done >= limit or attempts >= limit:
            break
        is_file = e.locator.startswith("file://")
        if e.locator_canonical is None and not is_file:
            continue  # 非 http 且非 file，无正文可抓
        # 「已抓过」判定必须读库：传入的 entries 是采集器视图（content_hash 恒为
        # None），用它会每轮重复抓同一批文件、烧光尝试预算（0.2.0 第二十五批修）
        stored = dl.get_entry(e.id)
        if stored and stored.content_hash and dl.get_content(stored.content_hash) is not None:
            continue  # 正文已在 content_store（抓过一次不重复抓）
        attempts += 1
        # 用户定调（2026-10-20）：「连续三次超时且排除网络问题，扔掉」——超时重试
        # 最多 3 次（每次走完整双后端链），仍超时按 unreachable 打标进待清理候选；
        # 非超时错误（403/404/解析失败）是确定性的，重试无益，一次判死。
        text = title = None
        last_exc: Exception | None = None
        ok = False
        for _try in range(3):
            try:
                text, title = fetch_with_fallback(e.locator, locators, ctx)
                ok = True
                break
            except DegradedParseError as exc:
                last_exc = exc
                break  # 解析失败确定性失败
            except (AdapterError, FetchError) as exc:
                last_exc = exc
                if not _is_timeout(exc):
                    break
        if not ok:
            if last_exc is not None:
                _flag(e, "unparseable" if isinstance(last_exc, DegradedParseError)
                      else "unreachable", str(last_exc))
            continue
        if is_garbled(text):
            _flag(e, "garbled")  # 乱码正文不入库不进 FTS，直接进待清理候选
            continue
        fhash = content_hash(text)
        dl.put_content(FetchResult(text=text, content_hash=fhash,
                                   fetcher=str(cfg.get("fetch.default_backend", "simple")),
                                   fetched_at=datetime.now().astimezone().isoformat(timespec="seconds")))
        updates.append(_apply_content(e, text, fhash,
                                      str(cfg.get("fetch.default_backend", "simple")),
                                      datetime.now().astimezone().isoformat(timespec="seconds")))
        fetched_ids.append(e.id)
        done += 1
    if updates:
        dl.upsert_entries(updates)
    _clear_stale_fetch_flags(dl, fetched_ids)
    return {"fetched": done, "fetch_failed": failed, "fetch_attempts": attempts,
            "fetched_ids": fetched_ids}


def _reclassify_all(cfg: Any, dl: Any, semantics: Any, run_id: str) -> dict[str, Any]:
    """全量重分类：active 条目重跑 classify_coarse 三级流水线。

    语义（0.2.0 修正，用户反馈"LLM 不该顺手归并残留类目"）：
    - 先统一 detach 全部机器分类；候选路径（known_paths）只保留**人工挂接**的分类——
      LLM 的类目候选由用户认可的类目决定，不再被旧机器类目 anchor；
    - 含人工挂接的条目整条跳过（人工结论优先，H3）；
    - 重跑后自动清理空壳机器类目（无条目、无子类、origin != manual）；
    - [llm] 未启用 / key 未设时 L3 静默跳过，结果 = 先验+规则（stats.llm_used=false）。
    """
    from ..semantic.base import SemanticInput, TaskContext
    from ..semantic.llm import LlmClient

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
            TaskContext(run_id=run_id, known_paths=known, llm=llm, config=cfg),
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
    """
    from ..semantic.value_guard import judge_value

    entries = dl.list_entries(status="active", limit=10000)
    by_reason: dict[str, int] = {}
    flagged = reasons_filled = 0
    for e in entries:
        if e.meta.get("value_flag") == "ok":
            continue
        reason = judge_value(e.locator)
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
    from ..semantic.freshness import extract_latest_year, judge_text, title_key

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


def run_sync(cfg: Any, dl: Any, locators: Any, semantics: Any, *,
             full: bool = False, source: str | None = None, dry_run: bool = False,
             limit: int | None = None, fetch_limit: int | None = None,
             reclassify: bool = False, value_scan: bool = False,
             dedupe_scan: bool = False,
             freshness_scan: bool = False) -> dict[str, Any]:
    """同步入口。返回统计 dict（各源 created/updated/unchanged/archived/分类分布）。

    reclassify=True 时跳过源收集，只对库中全部 active 条目重跑分类。
    value_scan=True 时跳过源收集，只跑 L0 价值守卫打标（零费用，见 _value_scan）。
    dedupe_scan=True 时跳过源收集，只跑跨源去重存量扫描（第三十八批，见
    pipeline/dedupe.scan_and_merge；dry_run 只出报告）。
    """
    run_id = uuid.uuid4().hex[:16]
    kind = "sync_full" if full else "sync_incremental"
    dl.start_run(run_id, kind)
    stats: dict[str, Any] = {"sources": {}}
    if value_scan:
        stats["value_scan"] = _value_scan(dl, dry_run)
        dl.finish_run(run_id, stats)
        return {"run_id": run_id, **stats}
    if reclassify:
        stats["reclassify"] = _reclassify_all(cfg, dl, semantics, run_id)
        dl.finish_run(run_id, stats)
        return {"run_id": run_id, **stats}
    if dedupe_scan:
        stats["dedupe_scan"] = scan_and_merge(dl, dry_run=dry_run)
        dl.finish_run(run_id, stats)
        return {"run_id": run_id, **stats}
    if freshness_scan:
        stats["freshness_scan"] = _freshness_scan(dl, dry_run)
        dl.finish_run(run_id, stats)
        return {"run_id": run_id, **stats}

    for name, collector in _BATCH_COLLECTORS.items():
        if source is not None and source != name:
            continue
        sec = cfg.get(f"sources.{name}") or {}
        if not sec.get("enabled"):
            continue
        try:
            out = collector(cfg)
        except AdapterError as exc:
            stats["sources"][name] = {"error": f"{type(exc).__name__}: {exc}"}
            continue

        entries: list[Entry] = list(out.entries)
        if limit is not None:
            entries = entries[:limit]
        if dry_run:
            stats["sources"][name] = {"reachable": True, "entry_count": len(entries), **out.stats}
            continue

        # 预检：新建 id、更新 id（源字段有真实变化）、归档复活（曾 missing → 源里重新出现）
        new_ids: set[str] = set()
        updated_ids: set[str] = set()
        revived_ids: list[str] = []
        for e in entries:
            old = dl.get_entry(e.id)
            if old is None:
                new_ids.add(e.id)
                continue
            if old.status == "archived":
                revived_ids.append(e.id)
            # 预检与 upsert 内容保护同口径（0.2.0 第二十五批）：采集器不产正文时
            # 不比较 inline_content/content_hash——否则已抓正文的条目每轮都被误判
            # updated，白白重跑一次无正文的分类（烧 LLM 费用）
            src_has_content = bool((e.inline_content or "").strip()) or bool(e.content_hash)
            fields = _SOURCE_FIELDS if src_has_content else tuple(
                f for f in _SOURCE_FIELDS if f not in ("inline_content", "content_hash"))
            if any(getattr(old, f) != getattr(e, f) for f in fields):
                updated_ids.add(e.id)
        result = dl.upsert_entries(entries)
        # mail 源附加处理（0.2.0 第三十九批）：全量正文进 content_store +
        # conv_messages 落库 + 原始会话线程还原（幂等，重复同步不重建）
        mail_stats: dict[str, Any] = {}
        if name == "mail":
            full_bodies: dict[str, str] = out.stats.pop("_full_bodies", {})
            convs = out.stats.pop("conv_messages", [])
            stored_count = 0
            for eid, text in full_bodies.items():
                e = dl.get_entry(eid)
                if e is not None and e.content_hash \
                        and dl.get_content(e.content_hash) is None:
                    dl.put_content(FetchResult(
                        text=text, content_hash=e.content_hash,
                        fetcher="maildir", fetched_at=_now_iso()))
                    stored_count += 1
            mail_stats["contents_stored"] = stored_count
            mail_stats.update(rebuild_mail_threads(dl, convs, run_id))
        if revived_ids:
            dl.set_status(revived_ids, "active")  # upsert 不写 status；源里重现即恢复
            dl.log_task(_now_iso(), "sync", "revive", ",".join(revived_ids),
                        {"count": len(revived_ids),
                         "source_type": _SOURCE_TYPE_BY_NAME.get(name, name)})
        cat = _categorize(dl, semantics, cfg, entries, new_ids, updated_ids, run_id)
        # 跨源判重（第三十八批）：新建/更新条目 canonical/hash 命中已有可消费
        # 条目 → 附挂 locator + 打 dedupe_master 标（消费页由主条目代表）
        deduped = dedupe_entries(dl, [e for e in entries
                                      if e.id in new_ids or e.id in updated_ids])

        src_stats: dict[str, Any] = {
            "entries": len(entries),
            "created": result.created, "updated": result.updated,
            "unchanged": result.unchanged, "deduped": deduped, **mail_stats,
            **cat, **out.stats,
        }
        if full:
            archived = dl.archive_missing(
                source_type=_SOURCE_TYPE_BY_NAME.get(name, name),
                seen_ids={e.id for e in entries}, run_id=run_id)
            src_stats["archived"] = len(archived)
        if fetch_limit:
            fstats = _fetch_missing(cfg, dl, locators, entries, fetch_limit, run_id)
            fetched_ids = fstats.pop("fetched_ids")
            src_stats.update(fstats)
            if fetched_ids:
                # 抓到正文的条目**当场重分类**（update 语义=先摘机器旧挂接再重挂，
                # 人工校正不动）——否则正文晚于分类一步，要再跑一次全量 reclassify
                with_content = [dl.get_entry(eid) for eid in fetched_ids]
                src_stats["post_fetch"] = _categorize(
                    dl, semantics, cfg, [e for e in with_content if e is not None],
                    set(), set(fetched_ids), run_id)
                # 补抓拿到正文后 content_hash 才可用——当场判重（hash 命中即合并）
                fetched_live = [e for e in with_content if e is not None]
                src_stats["post_fetch_deduped"] = dedupe_entries(dl, fetched_live)
        stats["sources"][name] = src_stats

    if not stats["sources"]:
        stats["note"] = ("无可同步的已启用批量源：在 config/knowatlas.toml 启用"
                         " [sources.bookmarks] 等源，或用 kadd 手动收录")
    dl.finish_run(run_id, stats)
    return {"run_id": run_id, **stats}
