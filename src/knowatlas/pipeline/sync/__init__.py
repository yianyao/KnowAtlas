"""同步编排：源遍历 → 入库 → 抓取 → 分类（pipeline/sync 包）。"""


# 对外入口保持 knowatlas.pipeline.sync 不变（测试/ingest 按名取用，勿改）
from .fetch import _clear_stale_fetch_flags, _fetch_candidates, _fetch_missing, _is_timeout
from .store import _apply_content, _clean_options, _ingest_content, _store_bodies
from .enrich import _categorize, _freshness_scan, _reclassify_all, _value_scan
from .flags import _flag_value, _now_iso
import uuid
from typing import Any
from ...errors import AdapterError, DegradedParseError, FetchError
from ...models import Entry, FetchResult
from ..dedupe import dedupe_entries, scan_and_merge
from ..mail_threads import rebuild_mail_threads
from ..session_threads import rebuild_session_threads
from ._common import _BATCH_COLLECTORS, _SECTION_BY_NAME, _SOURCE_FIELDS, _SOURCE_TYPE_BY_NAME


def run_sync(cfg: Any, dl: Any, locators: Any, semantics: Any, *,
             full: bool = False, source: str | None = None, dry_run: bool = False,
             limit: int | None = None, fetch_limit: int | None = None,
             entry_ids: list[str] | None = None,
             reclassify: bool = False, value_scan: bool = False,
             dedupe_scan: bool = False,
             freshness_scan: bool = False, errata_scan: bool = False,
             purge_source: str | None = None,
             purge_reason: str = "reingest") -> dict[str, Any]:
    """同步入口。返回统计 dict（各源 created/updated/unchanged/archived/分类分布）。

    reclassify=True 时跳过源收集，只对库中全部 active 条目重跑分类。
    value_scan=True 时跳过源收集，只跑 L0 价值守卫打标（零费用，见 _value_scan）。
    dedupe_scan=True 时跳过源收集，只跑跨源去重存量扫描（第三十八批，见
    pipeline/dedupe.scan_and_merge；dry_run 只出报告）。
    purge_source 非空时先物理删除该源全部条目再同步（emmx 全删重灌，方案 §7.8）——
    顺序保证：前快照后清除（backup_on_sync 快照失败即中止，没快照不动手）；
    dry_run 只探测不删除。
    entry_ids（变更工单-2026-10-27-fetch候选口径与定向补抓 §2.2）：定向模式，只处理
    点名条目（顺序按命令行，不看 status，用户点名即抓）；**不归档**（定向 ≠ 全量遍历，
    即使带 full 也跳过 archive_missing），默认触发补抓（受 fetch_limit 上限约束）。
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
    if errata_scan:
        from ..errata import run_errata_scan

        stats["errata_scan"] = run_errata_scan(dl, dry_run)
        dl.finish_run(run_id, stats)
        return {"run_id": run_id, **stats}

    # 同步前快照（第四十六批）：契约=没快照不同步——VACUUM INTO 失败即中断，
    # 避免库写坏后连恢复点都没有；backup_on_sync=false 可显式关闭（用户自担风险）。
    # dry_run 只读不备份；scan 分支（上列四个）只读零写，不备份。
    if cfg.backup_on_sync and not dry_run:
        try:
            from ...pipeline.backup import snapshot as _snapshot
            stats["backup"] = _snapshot(cfg, dl, keep=cfg.backup_keep,
                                        min_interval_hours=cfg.backup_min_interval_hours)
        except Exception as exc:  # 快照失败不写库：先保证有恢复点再同步
            stats["backup"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            dl.finish_run(run_id, stats)
            return {"run_id": run_id, "aborted": "backup_failed", **stats}

    # 全删重灌（第六十五批，方案 §7.8）：先快照（上方，失败即中止）后清除——
    # purge 走 DataLayer.purge_source（FK 级联 + content_store 引用计数回收
    # + task_log 批次留痕「<purge_reason>」）；dry_run 只报告不动数据。
    if purge_source:
        stype = _SOURCE_TYPE_BY_NAME.get(purge_source, purge_source)
        if dry_run:
            stats["purge"] = {"source_type": stype, "dry_run": True}
        else:
            stats["purge"] = dl.purge_source(stype, reason=purge_reason,
                                             task_name="ksync")

    targeted_missing: set[str] = set()  # 定向模式下源扫描里找不到的点名 id（跨源合并）
    for name, collector in _BATCH_COLLECTORS.items():
        if source is not None and source != name:
            continue
        sec = cfg.get(f"sources.{_SECTION_BY_NAME.get(name, name)}") or {}
        if not sec.get("enabled"):
            continue
        try:
            out = collector(cfg)
        except AdapterError as exc:
            stats["sources"][name] = {"error": f"{type(exc).__name__}: {exc}"}
            continue

        entries: list[Entry] = list(out.entries)
        # 定向模式（变更工单-2026-10-27-fetch候选口径与定向补抓 §2.2）：只留点名 id，
        # 顺序按命令行；先过滤再套 limit（否则 limit 可能把点名条目截掉）。
        if entry_ids:
            order = {eid: i for i, eid in enumerate(entry_ids)}
            seen = {e.id for e in entries}
            targeted_missing.update(eid for eid in entry_ids if eid not in seen)
            entries = sorted((e for e in entries if e.id in order),
                             key=lambda e: order[e.id])
            if not entries:
                # 本源的扫描结果里一个都没有：不写 upsert/分类（定向只补点名的那些），
                # 缺失 id 统一在循环后按全局口径报（跨源去重，不按源重复刷存在感）。
                continue
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
            stored = _store_bodies(cfg, dl, full_bodies, "maildir")
            mail_stats["contents_stored"] = len(stored)
            mail_stats.update(rebuild_mail_threads(dl, convs, run_id))
        # session 源附加处理（第五十七批）：全量对话正文进 content_store +
        # 轮次落 conv_messages + 每会话一条 source 线程（与 mail 同约定，幂等）
        if name == "sessions":
            full_bodies: dict[str, str] = out.stats.pop("_full_bodies", {})
            convs = out.stats.pop("conv_messages", [])
            stored = _store_bodies(cfg, dl, full_bodies, "harvester_export")
            mail_stats = {"contents_stored": len(stored)}
            mail_stats.update(
                rebuild_session_threads(dl, convs, run_id))
        # emmx 源附加处理（第六十五批，方案 §7.8）：integral 整图大纲超 4096 的
        # 全文入 content_store（适配器 inline 留截断摘要 + content_hash 指向）
        if name == "emmx":
            full_bodies = out.stats.pop("_full_bodies", {})
            stored = _store_bodies(cfg, dl, full_bodies, "emmx_outline")
            mail_stats = {"contents_stored": len(stored)}
        if revived_ids:
            dl.set_status(revived_ids, "active")  # upsert 不写 status；源里重现即恢复
            dl.log_task(_now_iso(), "sync", "revive", ",".join(revived_ids),
                        {"count": len(revived_ids),
                         "source_type": _SOURCE_TYPE_BY_NAME.get(name, name)})
        # 入库缓冲（批次 68，用户裁决「正常入库、人工判断后再参与处理」）：源配置
        # new_entries="pending" 时新条目置 pending——不分类/不抓正文/不抽点（消费面
        # 全部按 status='active' 过滤，天然隔离），管理页「🆕 待审」批量转正或舍弃。
        # 默认 active（零行为变化）；给未来高噪音源（聊天记录/AI 会话/邮件）立闸门。
        pending_ids: set[str] = set()
        entry_mode = str(sec.get("new_entries", "active")).strip().lower()
        if entry_mode == "pending" and new_ids:
            pending_ids = set(new_ids)
            dl.set_status(sorted(pending_ids), "pending")
            dl.log_task(_now_iso(), "sync", "stage_pending", ",".join(sorted(pending_ids)),
                        {"count": len(pending_ids),
                         "source_type": _SOURCE_TYPE_BY_NAME.get(name, name),
                         "mode": "new_entries=pending"})
        elif entry_mode == "auto" and new_ids:
            # 工单 2026-10-27《入库即抽点与自动老化》§2.3：第三取值 auto = 守门后自动转正。
            # 判定口径与 kauto 的 activate_pending 同源（semantic.value_guard 零成本规则）；
            # 误杀可在管理页一键转正，审计走 task_log 的 auto_activate / auto_reject。
            from ..ingest import l0_guard

            now = _now_iso()
            ok_ids: list[str] = []
            bad: list[tuple[str, str]] = []
            for e in entries:
                if e.id not in new_ids:
                    continue
                reason = l0_guard(str(e.locator or ""),
                                  str(e.inline_content or "").strip())
                if reason:
                    bad.append((e.id, reason))
                else:
                    ok_ids.append(e.id)
            if bad:
                dl.set_status([eid for eid, _ in bad], "rejected")
                for eid, reason in bad:
                    dl.merge_meta(eid, {"value_flag": "not_knowledge",
                                        "value_flag_reason": reason,
                                        "auto_rejected_at": now})
                dl.log_task(now, "sync", "auto_reject",
                            ",".join(eid for eid, _ in bad),
                            {"count": len(bad),
                             "reasons": sorted({r for _, r in bad})})
            dl.log_task(now, "sync", "auto_activate", ",".join(ok_ids),
                        {"count": len(ok_ids),
                         "source_type": _SOURCE_TYPE_BY_NAME.get(name, name)})
        cat = _categorize(dl, semantics, cfg, entries, new_ids, updated_ids, run_id,
                          pending_ids=pending_ids)
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
        if full and not entry_ids:
            # 定向模式不归档（定向 ≠ 全量遍历）：只处理点名条目时「没出现」不代表
            # 源里删了东西——照 full 口径会把整源其余条目错误归档。
            archived = dl.archive_missing(
                source_type=_SOURCE_TYPE_BY_NAME.get(name, name),
                seen_ids={e.id for e in entries}, run_id=run_id)
            src_stats["archived"] = len(archived)
        if fetch_limit or entry_ids:
            # 候选口径（工单 §2.1）：默认只取 active 且刚转正的排最前；定向模式按点名
            # 顺序不看 status。pending 由此天然排除（status 过滤），不再单列 pending_ids。
            cand, finfo = _fetch_candidates(dl, entries, entry_ids=entry_ids)
            src_stats.update(finfo)
            # 定向模式默认补抓（点名即补完），预算 = 命中条数；fetch_limit 仍可收紧。
            budget = fetch_limit if fetch_limit else len(cand)
            if budget > 0:
                fstats = _fetch_missing(cfg, dl, locators, cand, budget, run_id)
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
    if entry_ids:
        # 定向模式报告（工单 §2.2）：点名几个、命中几个、哪些源里根本没有。
        stats["targeted"] = {"requested": len(entry_ids),
                             "matched": len(entry_ids) - len(targeted_missing),
                             "missing_ids": sorted(targeted_missing)}

    # 老化删除出口（第六十三批，方案 §7.5）：ksync 顺手执行——冷却期满（30 天）
    # 的 rejected 条目物理删除（人裁过的才进冷却；引用计数回收 + 审计留痕）。
    # dry_run 只出报告不删除；scan 分支（上文早退）本就不清扫。
    from ..aging import sweep_rejections

    stats["rejected_sweep"] = sweep_rejections(dl, dry_run=dry_run)
    dl.finish_run(run_id, stats)
    return {"run_id": run_id, **stats}
