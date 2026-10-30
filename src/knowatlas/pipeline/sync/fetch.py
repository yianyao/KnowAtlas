"""pipeline/sync/fetch.py（拆分产物）。"""

# 拆分自 pipeline/sync.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


from typing import Any
from ...errors import AdapterError, DegradedParseError, FetchError
from ...models import Entry, FetchResult
from ...registry.capability import FetchContext
from .flags import _flag_value, _now_iso
from .store import _ingest_content


def _fetch_candidates(dl: Any, entries: list[Entry], *,
                      entry_ids: list[str] | None = None,
                      ) -> tuple[list[Entry], dict[str, Any]]:
    """补抓候选（变更工单-2026-10-27-fetch候选口径与定向补抓 §2.1）。

    默认（非定向）：只留库里 status='active' 的条目，且**刚转正的排最前**。
    为什么：`--fetch-limit N` 的 N 是**尝试次数**预算，而采集器视图按采集顺序给出
    全部条目（含 pending/rejected/archived）；老的 rejected 排在前面就会白吃预算
    （R16 排查：22 条 rejected 仍有正文，用户 19:33 转正的 3 条一条没抓到）。
    定向（entry_ids）：不看 status（用户点名即抓，可补 rejected/待审），按点名顺序。

    返回 (候选列表, 统计键)；统计键只增，供 ksync 报告展示。
    """
    if entry_ids:
        order = {eid: i for i, eid in enumerate(entry_ids)}
        picked = sorted((e for e in entries if e.id in order),
                        key=lambda e: order[e.id])
        return picked, {"fetch_mode": "entry", "fetch_candidates": len(picked)}
    statuses = dl.status_map([e.id for e in entries])
    active = [e for e in entries if statuses.get(e.id) == "active"]
    promoted = dl.activation_times([e.id for e in active])
    first = [e for e in active if promoted.get(e.id)]
    first.sort(key=lambda e: promoted[e.id], reverse=True)  # 稳定排序：同刻保持源顺序
    rest = [e for e in active if not promoted.get(e.id)]
    return first + rest, {"fetch_mode": "active", "fetch_candidates": len(active),
                          "fetch_skipped_non_active": len(entries) - len(active),
                          "fetch_promoted_first": len(first)}


def _snapshot_backlog(dl: Any, source_type: str, new_ids: set[str],
                      pending_ids: set[str] | frozenset[str],
                      budget: int) -> list[Entry]:
    """本地源正文快照的候选（2026-10-30 工单《收录与源脱节》§2.2）。

    口径：该源 `status='active'` 且**没有 content_hash** 的条目（已抓过的不重读，
    避免每轮全库重解析）；`pending` 不抓（批次 68：待审不烧抓取/LLM 费用）。
    本轮新建的排最前——否则老 backlog 会吃光预算，新条目空正文进分类。
    `budget<=0` 视为不限。
    """
    out: list[Entry] = []
    for e in dl.list_entries(status="active", limit=10000):
        if e.source_type != source_type or e.id in pending_ids:
            continue
        if e.content_hash:
            continue
        if (e.meta or {}).get("value_flag") == "not_knowledge":
            continue  # 已判非知识/解析失败：别再每轮重试（用户否决 value_flag=ok 时自然会回来）
        out.append(e)
    out.sort(key=lambda e: e.id not in new_ids)  # 稳定排序：new 在前，其余保持 rowid 序
    return out if budget <= 0 else out[:budget]


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

    from ...fetchers.base import fetch_with_fallback
    from ...semantic.value_guard import is_garbled

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
        if not text.strip():
            # 空正文守门（TODO 8.4 验收补充，2026-10-26）：0 字节文件/纯空白页
            # 抓下来也是「没有知识」——与 expand 批次 94 的 empty_body 同口径。
            # 只标记不删（用户可否决），但不得以「可消费 active 条目」进检索/分类/抽点。
            _flag(e, "empty")
            continue
        if is_garbled(text):
            _flag(e, "garbled")  # 乱码正文不入库不进 FTS，直接进待清理候选
            continue
        updates.append(_ingest_content(
            cfg, dl, e, text, str(cfg.get("fetch.default_backend", "simple")),
            _now_iso()))
        fetched_ids.append(e.id)
        done += 1
    if updates:
        dl.upsert_entries(updates)
    _clear_stale_fetch_flags(dl, fetched_ids)
    return {"fetched": done, "fetch_failed": failed, "fetch_attempts": attempts,
            "fetched_ids": fetched_ids}


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
