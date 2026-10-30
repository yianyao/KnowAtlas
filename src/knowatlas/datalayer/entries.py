"""条目域：入库（upsert）、状态机、查找/列表、跨源合并、废弃清理。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from ..errors import ContractError, LocatorFormatError
from ..models import Entry, SCHEMES, SOURCE_TYPES, STATUSES, UpsertResult
from ._common import (
    REJECT_COOLING_DAYS,
    _ACTIVATION_ACTIONS,
    _ID_RE,
    _IN_CHUNK,
    _SOURCE_FIELDS,
    _consumable,
    _meta_json,
    _now,
)


class _EntriesMixin:
    # ---- 条目 ----

    def _validate_entry(self, e: Entry) -> None:
        if not _ID_RE.match(e.id):
            raise ContractError(f"entry_id 非法：{e.id!r}", entry_id=e.id,
                                hint="id 必须由 ids.entry_id 生成（16 位十六进制）")
        if e.source_type not in SOURCE_TYPES:
            raise ContractError(f"source_type 不在白名单：{e.source_type}", entry_id=e.id)
        if e.status not in STATUSES:
            raise ContractError(f"status 非法：{e.status}", entry_id=e.id)
        scheme = e.locator.split("://", 1)[0].lower()
        if scheme not in SCHEMES:
            raise LocatorFormatError(f"locator scheme 非法：{e.locator}", entry_id=e.id)
        if e.inline_content is not None and len(e.inline_content) > 4096:
            raise ContractError(
                f"inline_content 超长（{len(e.inline_content)} > 4096）", entry_id=e.id,
                hint="超出部分入 content_store，本字段留截断摘要",
            )
        if not isinstance(e.meta, dict):
            raise ContractError("meta 必须是 dict", entry_id=e.id)

    def upsert_entries(self, entries: Iterable[Entry]) -> UpsertResult:
        """按 id INSERT .. ON CONFLICT（H3 覆盖纪律见模块 docstring 与完整方案 §3.5）。

        updated 判定 = 源字段与库中值有真实差异（exported_at 刷新不计入 updated）。
        meta 合并语义（0.2.0 第十八批修正，修机器后处理键被同步抹掉的 bug）：
        入库 meta = {**旧 meta, **新 meta}——源自带的键（source_type/browser/
        native_path/mind_path 等）以源为准覆盖；**源不设置而库中已有的键原样保留**，
        含 manual_ 人工键与同步后机器写入的 value_flag / value_flag_reason /
        link_status / fetch_backend 等（否则每次同步都会把「待清理候选」标记、
        体检结论抹掉并造成 updated 翻转抖动）。updated 判定同样按合并后的 meta 比。
        """
        created = updated = unchanged = 0
        ids: list[str] = []
        with self.transaction() as conn:
            for e in entries:
                self._validate_entry(e)
                meta_json = _meta_json(e.meta)
                row = conn.execute("SELECT * FROM entries WHERE id=?", (e.id,)).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO entries (id, source_type, title, locator, locator_canonical,"
                        " native_path, inline_content, content_hash, meta, created_at, exported_at, status)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (e.id, e.source_type, e.title, e.locator, e.locator_canonical,
                         e.native_path, e.inline_content, e.content_hash, meta_json,
                         e.created_at, e.exported_at, e.status),
                    )
                    created += 1
                else:
                    # 浅合并：源键覆盖旧值；源不设置的键（机器/人工后处理）保留
                    old_meta = json.loads(row["meta"])
                    merged = {**old_meta, **e.meta}
                    merged_json = _meta_json(merged)
                    # 抓取内容保护（0.2.0 第二十五批）：采集器不产出正文的源
                    # （folder/bookmark 的 inline_content 为空）不得抹掉已抓取的
                    # 正文——K1 纪律「内容只进不出」，否则每轮全量同步都会把
                    # --fetch-limit 补来的正文与 content_hash 清零并误判 updated。
                    # emmx 等源自带正文（源非空）→ 照常覆盖。
                    src_has_content = bool((e.inline_content or "").strip()) or bool(e.content_hash)
                    if src_has_content:
                        eff_inline, eff_hash = e.inline_content, e.content_hash
                    else:
                        eff_inline = row["inline_content"]
                        eff_hash = row["content_hash"]
                    changed = (
                        any(row[f] != getattr(e, f) for f in _SOURCE_FIELDS
                            if f not in ("inline_content", "content_hash"))
                        or row["inline_content"] != eff_inline
                        or row["content_hash"] != eff_hash
                        or row["meta"] != merged_json
                    )
                    if changed:
                        conn.execute(
                            "UPDATE entries SET title=?, locator=?, locator_canonical=?,"
                            " native_path=?, inline_content=?, content_hash=?, meta=?,"
                            " created_at=?, exported_at=? WHERE id=?",
                            (e.title, e.locator, e.locator_canonical, e.native_path,
                             eff_inline, eff_hash, merged_json,
                             e.created_at, _now(), e.id),
                        )
                        updated += 1
                    else:
                        conn.execute("UPDATE entries SET exported_at=? WHERE id=?", (_now(), e.id))
                        unchanged += 1
                ids.append(e.id)
        return UpsertResult(created, updated, unchanged, ids)

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> Entry:
        meta = json.loads(row["meta"])
        # display_name 覆盖层（批次 71）：用户改名/AI 起名优先于源标题——
        # full 重同步会冲回 entries.title（upsert 覆盖），覆盖层在 meta 不受影响；
        # 统一在数据层应用，所有消费面（列表/检索/图/导出）自动生效。
        title = str(meta.get("display_name") or row["title"] or "")
        return Entry(
            id=row["id"], source_type=row["source_type"], title=title,
            locator=row["locator"], locator_canonical=row["locator_canonical"],
            native_path=row["native_path"], inline_content=row["inline_content"],
            content_hash=row["content_hash"], meta=meta,
            created_at=row["created_at"], exported_at=row["exported_at"], status=row["status"],
        )

    def get_entry(self, entry_id: str) -> Entry | None:
        row = self._conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        return self._row_to_entry(row) if row else None

    def find_by_locator(self, locator: str) -> list[Entry]:
        """同时匹配主 locator（entries.locator）与附加 locator（entry_locators）。"""
        rows = self._conn.execute(
            "SELECT e.* FROM entries e WHERE e.locator = ?"
            " UNION"
            " SELECT e.* FROM entries e JOIN entry_locators l ON l.entry_id = e.id"
            " WHERE l.locator = ?",
            (locator, locator),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def find_by_canonical(self, canonical_url: str) -> Entry | None:
        """kadd 判重：走 idx_entries_loccanon 索引，不全表扫。"""
        row = self._conn.execute(
            "SELECT * FROM entries WHERE locator_canonical=?", (canonical_url,)
        ).fetchone()
        return self._row_to_entry(row) if row else None

    def find_canonical_group(self, canonical_url: str) -> list[Entry]:
        """canonical 相同的全部条目（跨源去重分组用，第三十八批）。"""
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE locator_canonical=?", (canonical_url,)
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def find_by_content_hash(self, content_hash: str) -> list[Entry]:
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE content_hash=?", (content_hash,)
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def attach_locator(self, entry_id: str, locator: str, is_primary: bool = False) -> None:
        """跨源合并落点：同一知识的第二个来源 locator 追加到已有条目。"""
        scheme = locator.split("://", 1)[0].lower()
        if scheme not in SCHEMES:
            raise LocatorFormatError(f"locator scheme 非法：{locator}", entry_id=entry_id)
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO entry_locators (entry_id, locator, scheme, is_primary)"
                " VALUES (?,?,?,?)",
                (entry_id, locator, scheme, int(is_primary)),
            )

    def merge_entries(self, primary_id: str, merge_ids: list[str], *,
                      reason: str = "web_merge") -> dict[str, Any]:
        """条目合并（批次 71）：同主题多条并成一条——用户截图「PECOS×3 该合并」。

        - merge_ids 各条的 locator 逐个挂到主条目（entry_locators，跨源合并落点）；
        - 点溯源转移：point_sources.entry_id 改指主条目（点与溯源不丢，主条目
          溯源变多）；共享点自动归并；
        - 分类挂接合并：entry_categories INSERT OR IGNORE（主条目获得缺失分类）；
        - 其余条目置 rejected（带 rejected_at 冷却起点——用户舍弃语义，30 天后
          kaging 可物理删除；不物理删：正文引用计数归零回收自动发生）；
        - meta 记 merged_into / merged_from 双向锚（审计与理解来路）；
        - 返回 {merged, primary_locators, points_moved}。task_log 留痕。
        """
        if primary_id in merge_ids:
            raise ContractError("主条目不能出现在合并列表里", entry_id=primary_id)
        moved_points = 0
        with self.transaction() as conn:
            primary = conn.execute("SELECT id, locator FROM entries WHERE id=?",
                                   (primary_id,)).fetchone()
            if primary is None:
                raise ContractError(f"主条目不存在：{primary_id}", entry_id=primary_id)
            n_moved = 0
            for mid in merge_ids:
                row = conn.execute(
                    "SELECT id, locator, source_type, title FROM entries WHERE id=?",
                    (mid,)).fetchone()
                if row is None:
                    continue
                loc = row["locator"]
                if loc and loc != primary["locator"]:
                    scheme = loc.split("://", 1)[0].lower()
                    if scheme in SCHEMES:
                        conn.execute(
                            "INSERT OR IGNORE INTO entry_locators (entry_id, locator,"
                            " scheme, is_primary) VALUES (?,?,?,0)", (primary_id, loc, scheme))
                conn.execute("UPDATE OR IGNORE point_sources SET entry_id=? WHERE entry_id=?",
                             (primary_id, mid))
                moved_points += conn.execute(
                    "SELECT changes()").fetchone()[0]
                # 分类挂接搬给主条目（重复自动忽略）
                conn.execute(
                    "INSERT OR IGNORE INTO entry_categories (entry_id, category_id,"
                    " confidence, origin, task_run_id)"
                    " SELECT ?, category_id, confidence, origin, task_run_id"
                    " FROM entry_categories WHERE entry_id=?",
                    (primary_id, mid))
                # 被并条目：舍弃（带冷却起点）+ 双向锚
                conn.execute(
                    "UPDATE entries SET status='rejected',"
                    " meta=json_set(meta,'$.merged_into',?,'$.rejected_at',?) WHERE id=?",
                    (primary_id, _now(), mid))
                n_moved += 1
            # merged_from 双向锚：Python 侧读-改-写（SQL JSON 拼接数组易 malformed）
            prow = conn.execute("SELECT meta FROM entries WHERE id=?",
                                (primary_id,)).fetchone()
            pmeta = json.loads(prow["meta"]) if prow and prow["meta"] else {}
            prev = pmeta.get("merged_from") or []
            pmeta["merged_from"] = list(prev) + merge_ids[:20]
            conn.execute("UPDATE entries SET meta=? WHERE id=?",
                         (json.dumps(pmeta, ensure_ascii=False), primary_id))
            conn.execute(
                "INSERT INTO task_log (at, task_name, action, target, detail)"
                " VALUES (?,?,?,?,?)",
                (_now(), "web", "merge_entries", primary_id,
                 json.dumps({"merged": n_moved, "merge_ids": merge_ids[:20],
                             "points_moved": moved_points, "reason": reason},
                            ensure_ascii=False)))
        return {"merged": n_moved, "primary": primary_id,
                "points_moved": moved_points}

    def all_entry_categories(self) -> dict[str, list[str]]:
        """全部条目→直挂分类 id 列表（按 rowid 序）——导出投影用（第四十五批）。"""
        out: dict[str, list[str]] = {}
        for r in self._conn.execute(
                "SELECT entry_id, category_id FROM entry_categories ORDER BY rowid"):
            out.setdefault(r["entry_id"], []).append(r["category_id"])
        return out

    def entry_category_ids(self, entry_id: str) -> list[str]:
        """单条目直挂分类 id 列表（按 rowid 序）——MCP 只读详情端点用
        （第四十六批；all_entry_categories 的全量映射对单条目查询太重）。"""
        return [r["category_id"] for r in self._conn.execute(
            "SELECT category_id FROM entry_categories WHERE entry_id=? ORDER BY rowid",
            (entry_id,))]

    def all_entry_locators(self) -> dict[str, list[str]]:
        """全部附加 locator（entry_id → locator 列表，按 is_primary 倒序+插入序）。
        导出投影用（第四十五批）；空 dict = 无任何附加 locator。"""
        out: dict[str, list[str]] = {}
        for r in self._conn.execute(
                "SELECT entry_id, locator FROM entry_locators"
                " ORDER BY is_primary DESC, rowid"):
            out.setdefault(r["entry_id"], []).append(r["locator"])
        return out

    def set_status(self, entry_ids: Sequence[str], status: str) -> None:
        if status not in STATUSES:
            raise ContractError(f"status 非法：{status}")
        with self.transaction() as conn:
            conn.executemany(
                "UPDATE entries SET status=? WHERE id=?",
                [(status, eid) for eid in entry_ids],
            )

    def status_map(self, entry_ids: Sequence[str]) -> dict[str, str]:
        """批量读条目状态：id → status（只含库中存在的 id）。

        用途：`--fetch-limit` 候选口径（变更工单-2026-10-27-fetch候选口径与定向补抓）
        ——采集器视图没有真实 status，预算必须按库内状态分配，否则 rejected/pending
        会白吃尝试次数。
        """
        ids = list(dict.fromkeys(entry_ids))
        out: dict[str, str] = {}
        for i in range(0, len(ids), _IN_CHUNK):
            part = ids[i:i + _IN_CHUNK]
            marks = ",".join("?" * len(part))
            for r in self._conn.execute(
                    f"SELECT id, status FROM entries WHERE id IN ({marks})", part):
                out[r["id"]] = r["status"]
        return out

    def activation_times(self, entry_ids: Sequence[str]) -> dict[str, str]:
        """条目最近一次「转正」时间：id → task_log.at（只含有过转正记录的 id）。

        为什么读 task_log 而不是 meta：转正此前没有落 meta（只有舍弃会写
        rejected_at），task_log 是唯一既有的审计链；MAX(at) 即最近一次转正。
        时间戳同源（CLI/web 都写 _now_iso，+08:00），故字符串比较等价时间比较。
        """
        ids = list(dict.fromkeys(entry_ids))
        out: dict[str, str] = {}
        for i in range(0, len(ids), _IN_CHUNK):
            part = ids[i:i + _IN_CHUNK]
            marks = ",".join("?" * len(part))
            actions = ",".join(f"'{a}'" for a in _ACTIVATION_ACTIONS)  # 常量，非用户输入
            for r in self._conn.execute(
                    "SELECT target, MAX(at) AS at FROM task_log"
                    f" WHERE action IN ({actions}) AND target IN ({marks})"
                    " GROUP BY target", part):
                out[r["target"]] = r["at"]
        return out

    def archive_missing(self, source_type: str, seen_ids: set[str], run_id: str) -> list[str]:
        """删除检测（§3.6）：全量遍历型源本次未见且 active 的条目 → archived，不物理删除。"""
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT id FROM entries WHERE source_type=? AND status='active'",
                (source_type,),
            ).fetchall()
            missing = [r["id"] for r in rows if r["id"] not in seen_ids]
            conn.executemany(
                "UPDATE entries SET status='archived' WHERE id=?",
                [(eid,) for eid in missing],
            )
            for eid in missing:
                conn.execute(
                    "INSERT INTO task_log (at, task_name, action, target, detail) VALUES (?,?,?,?,?)",
                    (_now(), "ksync", "archive", eid,
                     json.dumps({"reason": "missing_in_source", "run_id": run_id},
                                ensure_ascii=False)),
                )
        return missing

    def mark_source_state(self, source_type: str, seen_ids: set[str],
                          run_id: str) -> dict[str, int]:
        """源存在性标记（2026-10-30 工单《收录与源脱节》）：只写 meta，**不碰 status**。

        为什么不再用 `archive_missing`：源侧删除（书签失效、邮件/聊天记录清理、文件删除）
        是外部世界的常态，不该让库里已收录的条目退出消费面。`archived` 从此只由用户
        或显式 `ksync --prune-missing` 产生。

        口径：
        - 本次全量遍历未见且 `status='active'` → `meta.source_state="missing"` +
          `meta.source_missing_at`（消费面不加过滤，仅 UI 可读）；
        - 重新出现 → `json_remove` 两键（回到「源在」的默认态）；
        - 只动 active：pending/rejected/archived 不参与，避免冲掉人工结论；
        - 写一条 `task_log(action="source_missing")` 审计（有变化才写）。
        """
        now = _now()
        scanned = missing_total = newly_marked = cleared = 0
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT id, meta FROM entries WHERE source_type=? AND status='active'",
                (source_type,),
            ).fetchall()
            scanned = len(rows)
            for r in rows:
                meta = json.loads(r["meta"] or "{}")
                if r["id"] not in seen_ids:
                    missing_total += 1
                    if meta.get("source_state") != "missing":
                        conn.execute(
                            "UPDATE entries SET meta=json_set(COALESCE(meta,'{}'),"
                            "'$.source_state','missing','$.source_missing_at',?)"
                            " WHERE id=?",
                            (now, r["id"]),
                        )
                        newly_marked += 1
                elif "source_state" in meta:
                    conn.execute(
                        "UPDATE entries SET meta=json_remove(COALESCE(meta,'{}'),"
                        "'$.source_state','$.source_missing_at') WHERE id=?",
                        (r["id"],),
                    )
                    cleared += 1
            if newly_marked or cleared:
                conn.execute(
                    "INSERT INTO task_log (at, task_name, action, target, detail)"
                    " VALUES (?,?,?,?,?)",
                    (now, "ksync", "source_missing", source_type,
                     json.dumps({"missing": missing_total, "newly_marked": newly_marked,
                                 "cleared": cleared, "run_id": run_id},
                                ensure_ascii=False)),
                )
        return {"scanned": scanned, "missing": missing_total,
                "newly_marked": newly_marked, "cleared": cleared}

    def sweep_expired_rejections(self, cooling_days: int = REJECT_COOLING_DAYS, *,
                                 dry_run: bool = False,
                                 now: datetime | None = None) -> dict[str, Any]:
        """老化删除出口（0.2.0 第六十三批，方案 §7.5 用户裁决第 4 条）：
        rejected 且 meta.rejected_at 超冷却期的条目物理删除。

        - 冷却期=误裁反悔窗口（restore 清 rejected_at）；无 rejected_at 的历史
          rejected 条目不删（非本机制裁决，不自动清）；
        - 删除走 FK 级联（entry_locators/entry_categories/point_sources 指针消失，
          points 本体保留），entries_fts 由触发器同步；
        - task_log 审计链留痕：被删条目的历史日志不动，另追加 sweep_delete 记录；
        - content_store 引用计数回收：多条目共享同一内容块只减计数，删到零才
          连 content_fts 一并清正文；
        - dry_run 只出报告不写库。
        """
        ref_now = now or datetime.now(timezone.utc)
        rows = self._conn.execute(
            "SELECT id, title, source_type, content_hash, meta FROM entries"
            " WHERE status='rejected'").fetchall()
        stats: dict[str, Any] = {"scanned_rejected": len(rows),
                                 "cooling_days": cooling_days, "dry_run": dry_run,
                                 "swept": [], "content_recycled": 0,
                                 "kept_cooling": 0, "kept_legacy": 0}
        expired: list[sqlite3.Row] = []
        for r in rows:
            rejected_at = json.loads(r["meta"] or "{}").get("rejected_at")
            if not rejected_at:
                stats["kept_legacy"] += 1
                continue
            try:
                t = datetime.fromisoformat(str(rejected_at))
            except ValueError:
                stats["kept_legacy"] += 1
                continue
            if t.tzinfo is None:
                t = t.astimezone()  # 无时区的历史值按本地时区解读
            if (ref_now - t).total_seconds() >= cooling_days * 86400:
                expired.append(r)
            else:
                stats["kept_cooling"] += 1
        for r in expired:
            detail = {"title": r["title"], "source_type": r["source_type"],
                      "content_hash": r["content_hash"], "cooling_days": cooling_days}
            if dry_run:
                stats["swept"].append({"id": r["id"], **detail})
                continue
            with self.transaction() as conn:
                conn.execute("DELETE FROM entries WHERE id=?", (r["id"],))
                conn.execute(
                    "INSERT INTO task_log (at, task_name, action, target, detail)"
                    " VALUES (?,?,?,?,?)",
                    (_now(), "aging", "sweep_delete", r["id"],
                     json.dumps(detail, ensure_ascii=False)),
                )
                if r["content_hash"]:
                    n = conn.execute(
                        "SELECT COUNT(*) FROM entries WHERE content_hash=?",
                        (r["content_hash"],),
                    ).fetchone()[0]
                    if n == 0:  # 引用计数归零才清正文（共享块只减计数）
                        conn.execute("DELETE FROM content_fts WHERE content_hash=?",
                                     (r["content_hash"],))
                        conn.execute("DELETE FROM content_store WHERE content_hash=?",
                                     (r["content_hash"],))
                        stats["content_recycled"] += 1
                stats["swept"].append({"id": r["id"], **detail})
        return stats

    def purge_source(self, source_type: str, *, reason: str,
                     task_name: str = "ksync") -> dict[str, Any]:
        """按 source_type 物理删除**全部**条目（含 archived/rejected）——推倒重来
        场景（emmx 全删重灌，方案 §7.8；调用方须先有快照，本方法不做快照）。

        - 删除走 FK 级联（entry_locators/entry_categories/entry_vectors/
          point_sources/thread_items/conv_messages/regress_cases 指针全清，
          points 本体保留），entries_fts 由触发器同步；
        - content_store 引用计数回收：共享内容块只减计数，删到零才清正文
          （与 sweep_expired_rejections 同口径）；
        - task_log 批次留痕（单条 action=purge_source，detail 含数量与原因）；
        - 调用方持返回 dict 记入 stats。
        """
        hashes = [r["content_hash"] for r in self._conn.execute(
            "SELECT DISTINCT content_hash FROM entries"
            " WHERE source_type=? AND content_hash IS NOT NULL", (source_type,),
        ).fetchall()]
        with self.transaction() as conn:
            n = conn.execute("SELECT COUNT(*) FROM entries WHERE source_type=?",
                             (source_type,)).fetchone()[0]
            conn.execute("DELETE FROM entries WHERE source_type=?", (source_type,))
            conn.execute(
                "INSERT INTO task_log (at, task_name, action, target, detail)"
                " VALUES (?,?,?,?,?)",
                (_now(), task_name, "purge_source", source_type,
                 json.dumps({"deleted": n, "reason": reason}, ensure_ascii=False)),
            )
        recycled = 0
        for h in hashes:
            with self.transaction() as conn:
                remain = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE content_hash=?", (h,),
                ).fetchone()[0]
                if remain == 0:
                    conn.execute("DELETE FROM content_fts WHERE content_hash=?", (h,))
                    conn.execute("DELETE FROM content_store WHERE content_hash=?", (h,))
                    recycled += 1
        return {"purged": n, "source_type": source_type, "reason": reason,
                "content_recycled": recycled}

    def list_entries(self, status: str = "active", limit: int = 2000) -> list[Entry]:
        """按状态列出条目（reclassify 等全量遍历场景用；默认上限 2000 防失控）。"""
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE status=? ORDER BY rowid LIMIT ?",
            (status, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def count_entries(self, status: str = "active") -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM entries WHERE status=?", (status,)).fetchone()[0]

    def list_by_link_status(self, link_status: str, limit: int = 500) -> list[Entry]:
        """按链接体检结果列出条目（meta.link_status；dead=永久失效，error=疑似临时）。"""
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE status='active'"
            "   AND json_extract(meta, '$.link_status')=? ORDER BY rowid LIMIT ?",
            (link_status, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def merge_meta(self, entry_id: str, patch: dict[str, Any]) -> None:
        """合并写入条目 meta（浅合并 patch；条目不存在时静默跳过）。

        patch 值为 None = **删除该键**（0.2.0 第二十八批：补抓成功后清除过时的
        fetch 失败打标需要真删键——存 null 会在 meta 留脏键）。
        """
        with self.transaction() as conn:
            row = conn.execute("SELECT meta FROM entries WHERE id=?", (entry_id,)).fetchone()
            if row is None:
                return
            meta = json.loads(row["meta"])
            for key, val in patch.items():
                if val is None:
                    meta.pop(key, None)
                else:
                    meta[key] = val
            conn.execute("UPDATE entries SET meta=? WHERE id=?", (_meta_json(meta), entry_id))

    def list_by_value_flag(self, value_flag: str, limit: int = 500) -> list[Entry]:
        """按价值标记列出条目（meta.value_flag；not_knowledge = 规则或 LLM 判非知识，待用户清理）。"""
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE status='active'"
            "   AND json_extract(meta, '$.value_flag')=? ORDER BY rowid LIMIT ?",
            (value_flag, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def list_by_freshness_flag(self, freshness_flag: str, limit: int = 500) -> list[Entry]:
        """按时效标记列出条目（meta.freshness_flag；stale=明确过期，suspect=疑似过旧，
        待用户清理/否决。第四十一批时效守卫）。"""
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE status='active'"
            "   AND json_extract(meta, '$.freshness_flag')=? ORDER BY rowid LIMIT ?",
            (freshness_flag, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def list_by_errata_flag(self, errata_flag: str, limit: int = 500) -> list[Entry]:
        """按勘误标记列出条目（meta.errata_flag；error=确认错误进裁决队列，
        suspect=疑似留观不出队，ok=用户否决不再标。第六十四批勘误三级）。"""
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE status='active'"
            "   AND json_extract(meta, '$.errata_flag')=? ORDER BY rowid LIMIT ?",
            (errata_flag, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_uncategorized(self, limit: int = 200) -> list[Entry]:
        """未分类暂存区。"""
        rows = self._conn.execute(
            "SELECT e.* FROM entries e"
            " LEFT JOIN entry_categories ec ON ec.entry_id = e.id"
            " WHERE ec.entry_id IS NULL AND e.status='active'"
            " ORDER BY e.exported_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def count_uncategorized(self) -> int:
        """未分类条目精确计数（COUNT 不设上限——get_uncategorized 有 LIMIT，
        len(list) 封顶会给出假数字，MCP tree 等聚合场景用本方法）。"""
        row = self._conn.execute(
            "SELECT count(*) FROM entries e"
            " LEFT JOIN entry_categories ec ON ec.entry_id = e.id"
            " WHERE ec.entry_id IS NULL AND e.status='active'",
        ).fetchone()
        return int(row[0])

    def get_entries_by_ids(self, entry_ids: Sequence[str]) -> list[Entry]:
        """按 id 批量取条目（保序去重； topic_recall 等聚合场景用，避免逐条查询）。"""
        ids = list(dict.fromkeys(entry_ids))
        if not ids:
            return []
        out: list[Entry] = []
        for i in range(0, len(ids), 400):  # SQLite 变量数上限内分批
            chunk = ids[i:i + 400]
            marks = ",".join("?" for _ in chunk)
            rows = self._conn.execute(
                f"SELECT * FROM entries WHERE id IN ({marks})", chunk).fetchall()
            out.extend(self._row_to_entry(r) for r in rows)
        by_id = {e.id: e for e in out}
        return [by_id[i] for i in ids if i in by_id]

    def entries_by_host(self, host: str, limit: int = 50) -> list[Entry]:
        """同 host 的 active 条目（topic_recall 同源聚类通道；host 需已小写规范化）。"""
        host = (host or "").strip().lower()
        if not host:
            return []
        esc = self._escape_like(host)
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE status='active'" + _consumable("entries") +
            "   AND (locator LIKE ? ESCAPE '\\' OR locator = ? OR locator = ?)"
            " ORDER BY exported_at DESC LIMIT ?",
            (f"%://{esc}/%", f"https://{host}", f"http://{host}", limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_entry_detail(self, entry_id: str) -> dict[str, Any] | None:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None
        content = self.get_content(entry.content_hash) if entry.content_hash else None
        return {
            "entry": {
                "id": entry.id, "source_type": entry.source_type, "title": entry.title,
                "locator": entry.locator, "locator_canonical": entry.locator_canonical,
                "native_path": entry.native_path, "inline_content": entry.inline_content,
                "meta": entry.meta, "created_at": entry.created_at,
                "exported_at": entry.exported_at, "status": entry.status,
            },
            "categories": self.get_entry_categories(entry_id),
            "content": content,
        }

