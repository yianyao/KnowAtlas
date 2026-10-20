"""跨源去重（完整方案 §12 步骤 14；0.2.0 第三十八批落地确定性判据）。

**判据与边界**：canonical URL 五步规范化一致 / content_hash（规范化文本）一致
两条确定性判据；simhash 近似与 embedding 余弦（M4）误合成本高于漏合，本批不做，
待真实需求驱动再立项。

**合并模型（只标不删，与 value_flag 同款纪律）**：
- 组内 created_at 最早的可消费条目为主条目；
- 副条目 locator 附挂到主条目（entry_locators，双 locator 可跳转）；
- 副条目 meta 打 `dedupe_master=主id` + `dedupe_reason`，从全部消费页消失
  （datalayer.db._consumable 统一过滤），保留在库、照常参与同步 upsert
  （meta 合并语义保标不抹）；删两键即恢复（可逆）。
- 主条目失效（被舍弃/待清理/归档）时副条目的标成「死标」，scan_and_merge
  负责摘除让其回归消费面（或换主）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..ids import canonical_url, content_hash  # noqa: F401  re-export


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_same_url(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    ca, cb = canonical_url(a), canonical_url(b)
    return ca is not None and ca == cb


def _is_consumable(entry: Any) -> bool:
    """Python 侧可消费口径，与 datalayer.db._consumable 保持一致。

    改动任一处必须同步另一处并跑全量测试（消费面守卫单点语义）。
    """
    m = entry.meta or {}
    return (entry.status == "active"
            and m.get("value_flag") != "not_knowledge"
            and m.get("link_status") != "dead"
            and not m.get("dedupe_master")
            and m.get("freshness_flag") != "stale")


def find_master(dl: Any, entry: Any) -> tuple[Any | None, str]:
    """为 entry 找合并主条目。返回 (主条目|None, 命中原因)。

    canonical 优先（同 URL 是最强的同知识信号），content_hash 兜底（同正文）。
    主条目 = 候选 ∪ 自身中 (created_at, id) 字典序最小者；若最小者是自身则返回
    None（自己就是主，等组内其余并入）——保证同批新建条目方向确定、不互指。
    """
    canon_found = dl.find_canonical_group(entry.locator_canonical) \
        if entry.locator_canonical else []
    for cands, reason in (
        (canon_found, "canonical_hit"),
        (dl.find_by_content_hash(entry.content_hash)
         if entry.content_hash else [], "content_hit"),
    ):
        usable = [c for c in (cands or [])
                  if c.id != entry.id and _is_consumable(c)]
        if not usable:
            continue
        earliest = min(usable + [entry],
                       key=lambda c: (c.created_at or "9999", c.id))
        if earliest.id != entry.id:
            return earliest, reason
    return None, ""


def merge_into(dl: Any, master: Any, dup: Any, reason: str) -> bool:
    """把 dup 合并进 master：附挂 locator + 打标。返回是否本次有实际动作。

    幂等：attach INSERT OR IGNORE；标已同值时不重复写。
    """
    if dup.meta.get("dedupe_master") == master.id:
        return False
    if dup.locator != master.locator:
        dl.attach_locator(master.id, dup.locator)
    dl.merge_meta(dup.id, {"dedupe_master": master.id, "dedupe_reason": reason})
    dl.log_task(_now(), "dedupe", "merge", dup.id,
                {"master": master.id, "reason": reason,
                 "dup_locator": dup.locator, "dup_title": (dup.title or "")[:80]})
    return True


def dedupe_entries(dl: Any, entries: list[Any]) -> int:
    """入库后判重（sync 用）：对条目逐条找主，命中即合并。返回合并条数。

    已带 dedupe_master 标的跳过（幂等：重复 sync 不重复计数）。
    """
    merged = 0
    for e in entries:
        stored = dl.get_entry(e.id)
        if stored is None or stored.meta.get("dedupe_master"):
            continue
        master, reason = find_master(dl, stored)
        if master is not None and merge_into(dl, master, stored, reason):
            merged += 1
    return merged


def _clear_dead_marks(dl: Any) -> list[str]:
    """摘死标：dedupe_master 指向不存在/不可消费条目的副条目回归消费面。

    主条目被舍弃/待清理/归档后，副条目不该陪着消失——摘标后下次分组重新选主。
    """
    rows = dl.list_entries(status="active", limit=10000)
    cleared: list[str] = []
    for e in rows:
        master_id = e.meta.get("dedupe_master")
        if not master_id:
            continue
        master = dl.get_entry(master_id)
        if master is None or not _is_consumable(master):
            dl.merge_meta(e.id, {"dedupe_master": None, "dedupe_reason": None})
            cleared.append(e.id)
    return cleared


def scan_and_merge(dl: Any, dry_run: bool = False) -> dict[str, Any]:
    """存量全库扫描：按 canonical / content_hash 分组，组内 >1 可消费条目即合并。

    dry_run=True 只出报告不写库。返回统计（分组数 / 合并数 / 死标摘除数）。
    """
    cleared = [] if dry_run else _clear_dead_marks(dl)
    merged = 0
    groups: dict[str, int] = {}
    for key_col, reason in (("locator_canonical", "canonical_hit"),
                            ("content_hash", "content_hit")):
        rows = dl.list_entries(status="active", limit=10000)
        buckets: dict[str, list[Any]] = {}
        for e in rows:
            if not _is_consumable(e):
                continue
            key = getattr(e, key_col)
            if key:
                buckets.setdefault(key, []).append(e)
        for key, members in buckets.items():
            if len(members) < 2:
                continue
            groups[reason] = groups.get(reason, 0) + 1
            if dry_run:
                continue
            members.sort(key=lambda c: (c.created_at or "9999", c.id))
            master, dups = members[0], members[1:]
            for dup in dups:
                if dup.meta.get("dedupe_master"):
                    continue  # 本轮别的组已合并（canonical/hash 双命中场景）
                if merge_into(dl, master, dup, reason):
                    merged += 1
    stats = {"groups": groups, "merged": merged, "dead_marks_cleared": len(cleared),
             "dry_run": dry_run}
    if not dry_run:
        dl.log_task(_now(), "dedupe", "scan", "all", stats)
    return stats
