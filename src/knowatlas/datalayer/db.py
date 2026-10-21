"""DataLayer：唯一允许碰 SQLite 的模块（完整方案 §3.5）。

防腐化红线（代码评审检查项）：
  grep -rn "sqlite3.connect" src/        只允许命中本文件；
  grep -rn "INSERT INTO\\|UPDATE .* SET\\|DELETE FROM" src/  同理。
"""

from __future__ import annotations

import functools
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from ..errors import ContractError, LocatorFormatError
from ..models import (
    SCHEMES, SOURCE_TYPES, STATUSES, THREAD_TYPES,
    Category, Entry, FetchResult, SearchHit, Thread, ThreadItem, UpsertResult,
)
from .schema import latest_version, load_migration

_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_ORIGINS = ("prior", "rule", "embedding", "llm", "manual")


def _consumable(alias: str = "e") -> str:
    """消费面守卫 SQL 片段（0.2.0 第三十六批，带前导 AND）。

    知识消费页（关系图/召回/检索/线索）只出「可消费」条目：
    status='active'（调用方既有条件）+ 非待清理（value_flag!=not_knowledge）
    + 非永久失效（link_status!=dead；error=疑似临时不判死）
    + 非去重副条目（dedupe_master 为空；第三十八批：跨源合并后由主条目代表）
    + 非明确过期（freshness_flag!=stale；第四十一批：suspect 仅标记保留可见）。
    管理页（待清理候选/时效候选/失效链接/归档检索）不走本片段，照常全量列出。
    Python 侧同口径判定在 pipeline/dedupe.py::_is_consumable，改动须两处同步。
    """
    return (f" AND COALESCE(json_extract({alias}.meta,'$.value_flag'),'ok')!='not_knowledge'"
            f" AND COALESCE(json_extract({alias}.meta,'$.link_status'),'ok')!='dead'"
            f" AND COALESCE(json_extract({alias}.meta,'$.dedupe_master'),'')=''"
            f" AND COALESCE(json_extract({alias}.meta,'$.freshness_flag'),'ok')!='stale'")
# H3 覆盖纪律：upsert 的 UPDATE 只含源拥有的字段；status 与人工校正永不覆盖。
# meta 浅合并（第十八批）：源键覆盖旧值，源不设置的键（机器/人工后处理，如
# value_flag / link_status / manual_*）原样保留——否则同步会抹掉后处理结论。
_SOURCE_FIELDS = (
    "title", "locator", "locator_canonical", "native_path",
    "inline_content", "content_hash", "created_at",
)
_PATHS_CTE = """
WITH RECURSIVE paths(id, path) AS (
    SELECT c.id, c.name FROM categories c
    WHERE NOT EXISTS (SELECT 1 FROM category_parents cp WHERE cp.category_id = c.id)
    UNION ALL
    SELECT cp.category_id, p.path || '/' || c.name
    FROM paths p
    JOIN category_parents cp ON cp.parent_id = p.id
    JOIN categories c ON c.id = cp.category_id
)
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _meta_json(meta: dict[str, Any]) -> str:
    return json.dumps(meta, ensure_ascii=False, sort_keys=True)


class DataLayer:
    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        self._lock = threading.RLock()
        # check_same_thread=False：web 层线程池访问；并发安全由 self._lock 串行化保证
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 连接纪律（§3.4）
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        # 实例级串行化：公开方法统一加锁（RLock 可重入，事务方法自行持锁）
        for name, fn in vars(type(self)).items():
            if name.startswith("_") or name == "transaction" or not callable(fn):
                continue
            setattr(self, name, functools.partial(self._guard, fn))

    def _guard(self, fn, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ---- 建库与迁移（只进不前） ----

    def init_schema(self) -> int:
        """建库与迁移（只进不前，0.2.0 第三十二批升级为多迁移按序应用）。

        - user_version=0（新库）→ 从 001 起顺序应用全部迁移；
        - user_version 介于 1..latest-1（旧库）→ 只应用缺失的后续迁移
          （如 001→002 加 threads 表，既有数据无损）；
        - user_version > latest（库比代码新）→ 明确报错，绝不用旧代码静默写新库。
        """
        latest = latest_version()
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > latest:
            raise ContractError(
                f"数据库 user_version={version} 高于代码支持的 {latest}",
                hint="该库由更新版本的 knowatlas 创建：请升级 knowatlas，或用旧版备份恢复",
            )
        if version == latest:
            return version
        for v in range(version + 1, latest + 1):
            self._conn.executescript(load_migration(v))
            self._conn.commit()
            self._conn.execute(f"PRAGMA user_version = {v}")
            self._conn.commit()
        return latest

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
        return Entry(
            id=row["id"], source_type=row["source_type"], title=row["title"],
            locator=row["locator"], locator_canonical=row["locator_canonical"],
            native_path=row["native_path"], inline_content=row["inline_content"],
            content_hash=row["content_hash"], meta=json.loads(row["meta"]),
            created_at=row["created_at"], exported_at=row["exported_at"], status=row["status"],
        )

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ThreadItem:
        return ThreadItem(
            id=row["id"], thread_id=row["thread_id"], entry_id=row["entry_id"],
            position=row["position"], relation_type=row["relation_type"], note=row["note"],
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

    def set_status(self, entry_ids: Sequence[str], status: str) -> None:
        if status not in STATUSES:
            raise ContractError(f"status 非法：{status}")
        with self.transaction() as conn:
            conn.executemany(
                "UPDATE entries SET status=? WHERE id=?",
                [(status, eid) for eid in entry_ids],
            )

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

    # ---- 内容 ----

    def put_content(self, result: FetchResult) -> None:
        """fetcher 不碰库；由 pipeline 经本方法落 content_store + content_fts。"""
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO content_store (content_hash, text, fetched_at, fetcher)"
                " VALUES (?,?,?,?)",
                (result.content_hash, result.text, result.fetched_at, result.fetcher),
            )
            conn.execute("DELETE FROM content_fts WHERE content_hash=?", (result.content_hash,))
            conn.execute(
                "INSERT INTO content_fts (content_hash, text) VALUES (?,?)",
                (result.content_hash, result.text),
            )

    def get_content(self, content_hash: str) -> str | None:
        row = self._conn.execute(
            "SELECT text FROM content_store WHERE content_hash=?", (content_hash,)
        ).fetchone()
        return row["text"] if row else None

    def get_content_preview(self, content_hash: str, limit: int) -> str | None:
        """正文前缀（SQL substr 截取，不整段进内存——悬浮概要等轻场景用）。"""
        row = self._conn.execute(
            "SELECT substr(text, 1, ?) AS head FROM content_store WHERE content_hash=?",
            (max(0, int(limit)), content_hash),
        ).fetchone()
        return row["head"] if row else None

    # ---- 分类 ----

    def _category_from_row(self, row: sqlite3.Row, path: str) -> Category:
        return Category(id=row["id"], name=row["name"], note=row["note"],
                        origin=row["origin"], created_at=row["created_at"], path=path)

    def create_category(self, name: str, parent_ids: Sequence[str], origin: str) -> Category:
        """path 不落库；返回的 Category.path 为按 parent_ids 派生的首条路径。"""
        if origin not in _ORIGINS:
            raise ContractError(f"origin 非法：{origin}")
        if not name or "/" in name:
            raise ContractError(f"分类名非法（不得含 / 或为空）：{name!r}")
        cid = uuid.uuid4().hex[:16]
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO categories (id, name, note, origin, created_at) VALUES (?,?,?,?,?)",
                (cid, name, None, origin, _now()),
            )
            for pid in parent_ids:
                if pid == cid:
                    raise ContractError("分类不能以自身为父")
                parent = conn.execute("SELECT id FROM categories WHERE id=?", (pid,)).fetchone()
                if parent is None:
                    raise ContractError(f"父分类不存在：{pid}")
                conn.execute(
                    "INSERT OR IGNORE INTO category_parents (category_id, parent_id) VALUES (?,?)",
                    (cid, pid),
                )
        cat = self.get_category(cid)
        assert cat is not None
        return cat

    def rename_category(self, category_id: str, new_name: str) -> None:
        """重命名分类节点（path 为派生量，改名后子树路径自动随之派生，无需级联重写）。"""
        if not new_name or "/" in new_name:
            raise ContractError(f"分类名非法（不得含 / 或为空）：{new_name!r}")
        with self.transaction() as conn:
            row = conn.execute("SELECT id FROM categories WHERE id=?", (category_id,)).fetchone()
            if row is None:
                raise ContractError(f"分类不存在：{category_id}")
            conn.execute("UPDATE categories SET name=? WHERE id=?", (new_name, category_id))

    def _all_paths(self) -> list[tuple[str, str]]:
        rows = self._conn.execute(_PATHS_CTE + " SELECT id, path FROM paths").fetchall()
        return [(r["id"], r["path"]) for r in rows]

    def get_category(self, category_id: str) -> Category | None:
        row = self._conn.execute(
            "SELECT * FROM categories WHERE id=?", (category_id,)
        ).fetchone()
        if row is None:
            return None
        paths = self.get_category_paths(category_id)
        return self._category_from_row(row, paths[0] if paths else row["name"])

    def get_category_paths(self, category_id: str) -> list[str]:
        """多父分类的全部派生路径。"""
        rows = self._conn.execute(
            _PATHS_CTE + " SELECT path FROM paths WHERE id=?", (category_id,)
        ).fetchall()
        return [r["path"] for r in rows]

    def all_category_paths(self) -> set[str]:
        return {p for _, p in self._all_paths()}

    def manual_category_paths(self) -> set[str]:
        """仅人工挂接（origin=manual）的分类的派生路径——reclassify 的候选来源。

        语义：LLM 的类目候选由用户人工认可的类目决定，空壳机器类目不进候选
        （2026-10-19 用户反馈：LLM 不应顺手归并残留类目）。
        """
        ids = [r["category_id"] for r in self._conn.execute(
            "SELECT DISTINCT category_id FROM entry_categories WHERE origin='manual'"
        ).fetchall()]
        out: set[str] = set()
        for cid in ids:
            out.update(self.get_category_paths(cid))
        return out

    def get_category_by_path(self, path: str) -> Category | None:
        """递归 CTE 派生路径匹配；多父派生导致路径歧义时取 origin 优先级最高者并记 task_log。"""
        rows = self._conn.execute(
            _PATHS_CTE + " SELECT c.*, p.path FROM paths p JOIN categories c ON c.id = p.id"
            " WHERE p.path = ?",
            (path,),
        ).fetchall()
        if not rows:
            return None
        if len({r["id"] for r in rows}) > 1:
            best = min(rows, key=lambda r: _ORIGINS.index(r["origin"])
                       if r["origin"] in _ORIGINS else len(_ORIGINS))
            self.log_task(_now(), "classify_coarse", "classify", best["id"], {
                "warning": "category_path_ambiguity", "path": path,
                "candidates": [r["id"] for r in rows],
            })
            row = best
        else:
            row = rows[0]
        return self._category_from_row(row, path)

    def _ensure_acyclic(self, conn: sqlite3.Connection, category_id: str,
                        new_parent_ids: Sequence[str]) -> None:
        for pid in new_parent_ids:
            cur: str | None = pid
            seen: set[str] = set()
            while cur is not None:
                if cur == category_id:
                    raise ContractError(f"挂接会形成环：{category_id} 不能成为自己子孙的子分类")
                if cur in seen:
                    break
                seen.add(cur)
                row = conn.execute(
                    "SELECT parent_id FROM category_parents WHERE category_id=?", (cur,)
                ).fetchone()
                cur = row["parent_id"] if row else None

    def move_category(self, category_id: str, new_parent_ids: Sequence[str]) -> None:
        """整棵挂到新父下；子树路径随之派生变化，无级联重写。"""
        with self.transaction() as conn:
            self._ensure_acyclic(conn, category_id, new_parent_ids)
            conn.execute("DELETE FROM category_parents WHERE category_id=?", (category_id,))
            for pid in new_parent_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO category_parents (category_id, parent_id) VALUES (?,?)",
                    (category_id, pid),
                )
            self.log_task(_now(), "corrections", "move", category_id,
                          {"new_parent_ids": list(new_parent_ids)})

    def merge_categories(self, source_id: str, target_id: str) -> None:
        """source 的条目挂接迁到 target（去重），source 删除；写 task_log。"""
        with self.transaction() as conn:
            if conn.execute("SELECT 1 FROM categories WHERE id=?", (source_id,)).fetchone() is None:
                raise ContractError(f"待合并分类不存在：{source_id}")
            if source_id == target_id:
                raise ContractError("不能合并到自身")
            conn.execute(
                "INSERT OR IGNORE INTO entry_categories"
                " (entry_id, category_id, confidence, origin, task_run_id)"
                " SELECT entry_id, ?, confidence, origin, task_run_id FROM entry_categories"
                " WHERE category_id = ?",
                (target_id, source_id),
            )
            conn.execute("DELETE FROM entry_categories WHERE category_id=?", (source_id,))
            conn.execute(
                "UPDATE OR IGNORE category_parents SET parent_id=? WHERE parent_id=?",
                (target_id, source_id),
            )
            conn.execute("DELETE FROM category_parents WHERE parent_id=?", (source_id,))
            conn.execute("DELETE FROM category_parents WHERE category_id=?", (source_id,))
            conn.execute("DELETE FROM categories WHERE id=?", (source_id,))
            self.log_task(_now(), "corrections", "merge", target_id, {"merged_from": source_id})

    def attach_parent(self, category_id: str, parent_id: str) -> None:
        with self.transaction() as conn:
            self._ensure_acyclic(conn, category_id, [parent_id])
            conn.execute(
                "INSERT OR IGNORE INTO category_parents (category_id, parent_id) VALUES (?,?)",
                (category_id, parent_id),
            )

    def detach_parent(self, category_id: str, parent_id: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM category_parents WHERE category_id=? AND parent_id=?",
                (category_id, parent_id),
            )

    def attach_category(self, entry_id: str, category_id: str, confidence: float,
                        origin: str, task_run_id: str) -> None:
        """条目挂分类；已存在 manual 挂接时不被机器来源覆盖（人工校正保护）。"""
        if origin not in _ORIGINS:
            raise ContractError(f"origin 非法：{origin}")
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT origin FROM entry_categories WHERE entry_id=? AND category_id=?",
                (entry_id, category_id),
            ).fetchone()
            if existing is not None and existing["origin"] == "manual" and origin != "manual":
                return
            conn.execute(
                "INSERT OR REPLACE INTO entry_categories"
                " (entry_id, category_id, confidence, origin, task_run_id) VALUES (?,?,?,?,?)",
                (entry_id, category_id, float(confidence), origin, task_run_id),
            )

    def detach_category(self, entry_id: str, category_id: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM entry_categories WHERE entry_id=? AND category_id=?",
                (entry_id, category_id),
            )

    def get_entry_categories(self, entry_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            _PATHS_CTE + " SELECT c.id, c.name, p.path, ec.confidence, ec.origin"
            " FROM entry_categories ec JOIN categories c ON c.id = ec.category_id"
            " LEFT JOIN paths p ON p.id = c.id WHERE ec.entry_id = ?",
            (entry_id,),
        ).fetchall()
        return [
            {"category_id": r["id"], "name": r["name"], "path": r["path"],
             "confidence": r["confidence"], "origin": r["origin"]}
            for r in rows
        ]

    def list_entries(self, status: str = "active", limit: int = 2000) -> list[Entry]:
        """按状态列出条目（reclassify 等全量遍历场景用；默认上限 2000 防失控）。"""
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE status=? ORDER BY rowid LIMIT ?",
            (status, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_graph_data(self, max_entries: int = 400) -> dict[str, Any]:
        """关系图数据（结构关系 v0）：分类节点 + 条目节点 + 域名节点。

        边的三类来源：条目↔分类（挂接，含 origin）、条目↔域名（locator host 归组，
        星型防边爆炸）。语义级关系（引用/相似度）随 M2 正文与 M4 embedding 接入后扩展。
        """
        from urllib.parse import urlsplit

        entries = self._conn.execute(
            "SELECT id, title, locator FROM entries WHERE status='active'"
            + _consumable("entries") + " LIMIT ?",
            (max_entries,),
        ).fetchall()
        ecat = self._conn.execute(
            "SELECT entry_id, category_id, origin FROM entry_categories"
        ).fetchall()
        cats = {r["id"]: r["name"] for r in
                self._conn.execute("SELECT id, name FROM categories").fetchall()}

        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        seen_cids: set[str] = set()
        host_members: dict[str, list[str]] = {}
        for e in entries:
            host = urlsplit(e["locator"]).hostname or ""
            nodes.append({"id": f"e:{e['id']}", "name": (e["title"] or e["locator"])[:40],
                          "kind": "entry", "host": host})
            if host:
                host_members.setdefault(host, []).append(f"e:{e['id']}")
        for r in ecat:
            cid = r["category_id"]
            if cid not in cats:
                continue
            if cid not in seen_cids:
                seen_cids.add(cid)
                nodes.append({"id": f"c:{cid}", "name": cats[cid], "kind": "category"})
            links.append({"source": f"e:{r['entry_id']}", "target": f"c:{cid}",
                          "kind": r["origin"]})
        for host, members in host_members.items():
            if len(members) < 2:
                continue
            domain_id = f"d:{host}"
            nodes.append({"id": domain_id, "name": host, "kind": "domain"})
            for m in members:
                links.append({"source": m, "target": domain_id, "kind": "same_host"})
        return {"nodes": nodes, "links": links}

    # ---- 关系图三视图（0.2.0 第二十二批：总览 → 搜索/下钻按需子图） ----
    # 用户定调：全量力导一次渲染会拖垮——初始只显示一级大类；搜索框按关键字出
    # 相关子图；点分类节点下钻子树。全部按需加载，服务端裁剪。

    def _consumable_count(self, cat_ids: list[str]) -> int:
        """分类集合内可消费条目数（去重；消费面守卫口径，见 _consumable）。"""
        if not cat_ids:
            return 0
        ph = ",".join("?" * len(cat_ids))
        return self._conn.execute(
            "SELECT count(DISTINCT ec.entry_id) FROM entry_categories ec"
            " JOIN entries e ON e.id=ec.entry_id AND e.status='active'" + _consumable("e") +
            f" WHERE ec.category_id IN ({ph})", cat_ids).fetchone()[0]

    def _cat_descendants(self, cid: str) -> list[str]:
        """子树全 id（含自身；多父 DAG 防环）。"""
        down: dict[str, list[str]] = {}
        for r in self._conn.execute("SELECT category_id, parent_id FROM category_parents"):
            down.setdefault(r["parent_id"], []).append(r["category_id"])
        ids, stack, seen = [cid], [cid], {cid}
        while stack:
            x = stack.pop()
            for k in down.get(x, []):
                if k not in seen:
                    seen.add(k)
                    ids.append(k)
                    stack.append(k)
        return ids

    def _cat_ancestors(self, cid: str) -> list[str]:
        """祖先链 id（自父到根；多父取全部父，BFS 向上，防环）。"""
        up: dict[str, list[str]] = {}
        for r in self._conn.execute("SELECT category_id, parent_id FROM category_parents"):
            up.setdefault(r["category_id"], []).append(r["parent_id"])
        out: list[str] = []
        stack, seen = list(up.get(cid, [])), {cid}
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
            stack.extend(up.get(x, []))
        return out

    @staticmethod
    def _like_pattern(q: str) -> str:
        """LIKE 模式（转义 %/_，配 ESCAPE '\\' 使用）。"""
        return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    def _host_group_links(self, entry_nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """匹配条目间的同域名聚合（≥2 条才出域名节点）——与 v0 口径一致。"""
        from urllib.parse import urlsplit

        members: dict[str, list[str]] = {}
        for n in entry_nodes:
            host = n.get("host") or ""
            if host:
                members.setdefault(host, []).append(n["id"])
        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        for host, ids in members.items():
            if len(ids) < 2:
                continue
            nodes.append({"id": f"d:{host}", "name": host, "kind": "domain"})
            for m in ids:
                links.append({"source": m, "target": f"d:{host}", "kind": "same_host"})
        return nodes, links

    def get_graph_overview(self) -> dict[str, Any]:
        """大纲图：只含一级大类节点，value = 子树 active 条目数（前端按它定气泡大小）。"""
        has_parent = {r["category_id"] for r in
                      self._conn.execute("SELECT category_id FROM category_parents")}
        nodes: list[dict[str, Any]] = []
        for r in self._conn.execute("SELECT id, name FROM categories ORDER BY name"):
            if r["id"] in has_parent:
                continue
            ids = self._cat_descendants(r["id"])
            count = self._consumable_count(ids)
            if count == 0:
                continue    # 空类剪枝（第三十六批）：无可消费条目的大类不进总览
            nodes.append({"id": f"c:{r['id']}", "name": r["name"],
                          "kind": "category", "value": count})
        return {"nodes": nodes, "links": []}

    def get_graph_subtree(self, category_id: str, limit: int = 120) -> dict[str, Any] | None:
        """子树下钻图：该分类的子孙分类 + 挂接条目（近 limit 条）+ 祖先链上下文。

        条目节点带 locator（前端点击可打开原链接）；分类不存在返回 None。
        """
        cat = self._conn.execute(
            "SELECT id, name FROM categories WHERE id=?", (category_id,)).fetchone()
        if cat is None:
            return None
        cats = {r["id"]: r["name"] for r in
                self._conn.execute("SELECT id, name FROM categories").fetchall()}
        sub_ids = self._cat_descendants(category_id)
        anc_ids = [a for a in self._cat_ancestors(category_id) if a not in sub_ids]
        ph = ",".join("?" * len(sub_ids))
        entries = self._conn.execute(
            "SELECT DISTINCT e.id, e.title, e.locator FROM entries e"
            f" JOIN entry_categories ec ON ec.entry_id=e.id"
            f" WHERE ec.category_id IN ({ph}) AND e.status='active'" + _consumable("e") +
            " ORDER BY e.created_at DESC LIMIT ?", (*sub_ids, limit)).fetchall()
        entry_ids = [e["id"] for e in entries]
        nodes: list[dict[str, Any]] = [
            {"id": f"c:{a}", "name": cats.get(a, "?"), "kind": "category", "ctx": True}
            for a in anc_ids]
        for cid in sub_ids:
            # 空类剪枝（第三十六批）：子树内无可消费条目的子类不进下钻图；焦点根保留
            if cid != category_id and self._consumable_count(self._cat_descendants(cid)) == 0:
                continue
            nodes.append({"id": f"c:{cid}", "name": cats.get(cid, "?"), "kind": "category"})
        from urllib.parse import urlsplit
        entry_nodes: list[dict[str, Any]] = []
        for e in entries:
            host = urlsplit(e["locator"]).hostname or ""
            entry_nodes.append({"id": f"e:{e['id']}", "name": (e["title"] or e["locator"])[:40],
                                "kind": "entry", "locator": e["locator"], "host": host})
        nodes.extend(entry_nodes)
        links: list[dict[str, Any]] = []
        if entry_ids:
            eph = ",".join("?" * len(entry_ids))
            for r in self._conn.execute(
                    f"SELECT entry_id, category_id, origin FROM entry_categories"
                    f" WHERE entry_id IN ({eph}) AND category_id IN ({ph})",
                    (*entry_ids, *sub_ids)):
                links.append({"source": f"e:{r['entry_id']}", "target": f"c:{r['category_id']}",
                              "kind": r["origin"]})
        d_nodes, d_links = self._host_group_links(entry_nodes)
        nodes.extend(d_nodes)
        links.extend(d_links)
        return {"root": category_id, "nodes": nodes, "links": links}

    def search_graph(self, q: str, limit: int = 80) -> dict[str, Any]:
        """搜索驱动子图：条目标题 / 分类名命中 + 各自分类链与挂接边（按需加载）。

        只带命中条目、其直挂分类与祖先链——不扩散拉全子树，保证子图小而相关。
        """
        from urllib.parse import urlsplit

        pat = self._like_pattern(q)
        matched_entries = self._conn.execute(
            "SELECT id, title, locator FROM entries WHERE status='active'"
            + _consumable("entries") +
            " AND title LIKE ? ESCAPE '\\' ORDER BY created_at DESC LIMIT ?",
            (pat, limit)).fetchall()
        matched_cats = [r["id"] for r in self._conn.execute(
            "SELECT id FROM categories WHERE name LIKE ? ESCAPE '\\' ORDER BY name LIMIT 20",
            (pat,))]
        cats = {r["id"]: r["name"] for r in
                self._conn.execute("SELECT id, name FROM categories").fetchall()}
        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        entry_ids = [e["id"] for e in matched_entries]
        entry_nodes: list[dict[str, Any]] = []
        for e in matched_entries:
            host = urlsplit(e["locator"]).hostname or ""
            entry_nodes.append({"id": f"e:{e['id']}", "name": (e["title"] or e["locator"])[:40],
                                "kind": "entry", "locator": e["locator"], "host": host})
        nodes.extend(entry_nodes)
        # 命中分类节点（含其祖先链，保证能看见大类归属）
        involved: set[str] = set(matched_cats)
        for cid in matched_cats:
            involved.update(self._cat_ancestors(cid))
        if entry_ids:
            eph = ",".join("?" * len(entry_ids))
            for r in self._conn.execute(
                    f"SELECT entry_id, category_id, origin FROM entry_categories"
                    f" WHERE entry_id IN ({eph})", entry_ids):
                cid = r["category_id"]
                links.append({"source": f"e:{r['entry_id']}", "target": f"c:{cid}",
                              "kind": r["origin"]})
                involved.add(cid)
                involved.update(self._cat_ancestors(cid))
        for cid in involved:
            if cid in cats:
                nodes.append({"id": f"c:{cid}", "name": cats[cid], "kind": "category"})
        d_nodes, d_links = self._host_group_links(entry_nodes)
        nodes.extend(d_nodes)
        links.extend(d_links)
        return {"query": q, "nodes": nodes, "links": links}

    # ---- 放射导航（0.2.0 第三十三批：§9.4 探索导向迭代，不推翻三视图） ----
    # 纪律：没有解释的关联不展示——每个节点带 reasons[]、每条边带 reason；
    # relation_reason 全部由规则生成（共现/同源/显式关联），语义相似边留 M4 embedding。

    _RADIATE_KINDS = {"c": "category", "e": "entry", "d": "domain"}

    def _entry_node(self, row: sqlite3.Row) -> dict[str, Any]:
        from urllib.parse import urlsplit
        host = urlsplit(row["locator"]).hostname or ""
        return {"id": f"e:{row['id']}", "name": (row["title"] or row["locator"])[:40],
                "kind": "entry", "locator": row["locator"], "host": host}

    def _entry_row(self, entry_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT id, title, locator FROM entries WHERE id=? AND status='active'"
            + _consumable("entries"),
            (entry_id,)).fetchone()
    def radiate(self, node_id: str, per_channel: int = 8) -> dict[str, Any] | None:
        """焦点一跳邻域（放射模式数据源）。

        节点 id 约定 `c:<分类id>` / `e:<条目id>` / `d:<host>`。通道与 relation_reason：
        分类焦点 → child / attach:<origin> / parent；条目焦点 → attach:<origin> /
        same_host:<host> / thread:<线索名>；域名焦点 → host_member:<host>。
        每通道上限 per_channel，超出记 truncated[通道]=剩余数。焦点不存在返回 None。
        """
        from urllib.parse import urlsplit

        prefix, _, raw_id = node_id.partition(":")
        kind = self._RADIATE_KINDS.get(prefix)
        if kind is None or not raw_id:
            return None

        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        truncated: dict[str, int] = {}

        def add_node(nid: str, name: str, nkind: str, reason: str, **extra: Any) -> None:
            if nid == node_id:
                return
            n = nodes.setdefault(nid, {"id": nid, "name": name, "kind": nkind,
                                       "reasons": [], **extra})
            if reason and reason not in n["reasons"]:
                n["reasons"].append(reason)

        def add_edge(target: str, reason: str) -> None:
            e = edges.setdefault(target, {"source": node_id, "target": target,
                                          "reason": reason})
            if reason and reason not in e["reason"]:
                e["reason"] = f"{e['reason']}；{reason}" if e["reason"] else reason

        def cut(channel: str, total: int) -> None:
            if total > per_channel:
                truncated[channel] = total - per_channel

        if kind == "category":
            cat = self._conn.execute(
                "SELECT id, name FROM categories WHERE id=?", (raw_id,)).fetchone()
            if cat is None:
                return None
            focus = {"id": node_id, "name": cat["name"], "kind": "category"}
            # child：子分类（空类剪枝：子树内无可消费条目的子类不出）
            children = self._conn.execute(
                "SELECT c.id, c.name FROM category_parents cp"
                " JOIN categories c ON c.id=cp.category_id WHERE cp.parent_id=?"
                " ORDER BY c.name", (raw_id,)).fetchall()
            children = [r for r in children
                        if self._consumable_count(self._cat_descendants(r["id"])) > 0]
            for r in children[:per_channel]:
                add_node(f"c:{r['id']}", r["name"], "category", "child")
            cut("child", len(children))
            # attach:<origin>：挂接条目（带 locator，前端可打开）
            atts = self._conn.execute(
                "SELECT e.id, e.title, e.locator, ec.origin FROM entry_categories ec"
                " JOIN entries e ON e.id=ec.entry_id AND e.status='active'"
                + _consumable("e") +
                " WHERE ec.category_id=? ORDER BY e.created_at DESC", (raw_id,)).fetchall()
            for r in atts[:per_channel]:
                add_node(f"e:{r['id']}", (r["title"] or r["locator"])[:40], "entry",
                         f"attach:{r['origin']}", locator=r["locator"])
                add_edge(f"e:{r['id']}", f"attach:{r['origin']}")
            cut("attach", len(atts))
            # parent：父分类
            parents = self._conn.execute(
                "SELECT c.id, c.name FROM category_parents cp"
                " JOIN categories c ON c.id=cp.parent_id WHERE cp.category_id=?"
                " ORDER BY c.name", (raw_id,)).fetchall()
            for r in parents[:per_channel]:
                add_node(f"c:{r['id']}", r["name"], "category", "parent")
                add_edge(f"c:{r['id']}", "parent")
            cut("parent", len(parents))
        elif kind == "entry":
            row = self._entry_row(raw_id)
            if row is None:
                return None
            focus = {"id": node_id, "name": (row["title"] or row["locator"])[:40],
                     "kind": "entry", "locator": row["locator"]}
            # attach:<origin>：直挂分类（带派生 path）
            atts = self._conn.execute(
                "SELECT ec.category_id, ec.origin FROM entry_categories ec"
                " WHERE ec.entry_id=?", (raw_id,)).fetchall()
            for r in atts[:per_channel]:
                paths = self.get_category_paths(r["category_id"])
                cname_row = self._conn.execute(
                    "SELECT name FROM categories WHERE id=?",
                    (r["category_id"],)).fetchone()
                add_node(f"c:{r['category_id']}", cname_row["name"] if cname_row else "?",
                         "category", f"attach:{r['origin']}", path=paths[0] if paths else "")
                add_edge(f"c:{r['category_id']}", f"attach:{r['origin']}")
            cut("attach", len(atts))
            # same_host:<host>
            host = urlsplit(row["locator"]).hostname or ""
            if host:
                peers = self.entries_by_host(host, limit=per_channel + 1)
                total = len([p for p in peers if p.id != raw_id])
                for p in [x for x in peers if x.id != raw_id][:per_channel]:
                    add_node(f"e:{p.id}", (p.title or p.locator)[:40], "entry",
                             f"same_host:{host}", locator=p.locator)
                    add_edge(f"e:{p.id}", f"same_host:{host}")
                cut("same_host", total)
            # thread:<线索名>：与串联工作区双向打通
            seen_thread_entries: set[str] = set()
            thread_total = 0
            for t in self.threads_for_entry(raw_id):
                full = self.get_thread(t["id"])
                if full is None:
                    continue
                members = [it for it in full.items if it.entry_id != raw_id]
                thread_total += len(members)
                for it in members[:per_channel]:
                    er = self._entry_row(it.entry_id)
                    if er is None or it.entry_id in seen_thread_entries:
                        continue
                    seen_thread_entries.add(it.entry_id)
                    add_node(f"e:{it.entry_id}", (er["title"] or er["locator"])[:40],
                             "entry", f"thread:{t['name']}", locator=er["locator"])
                    add_edge(f"e:{it.entry_id}", f"thread:{t['name']}")
            cut("thread", thread_total)
        else:  # domain
            host = raw_id.strip().lower()
            members = self.entries_by_host(host, limit=per_channel + 1)
            focus = {"id": node_id, "name": host, "kind": "domain"}
            for p in members[:per_channel]:
                add_node(f"e:{p.id}", (p.title or p.locator)[:40], "entry",
                         f"host_member:{host}", locator=p.locator)
                add_edge(f"e:{p.id}", f"host_member:{host}")
            cut("host_member", len(members))

        return {"focus": focus, "nodes": list(nodes.values()),
                "edges": list(edges.values()), "truncated": truncated}

    def reverse_reach(self, node_id: str, limit: int = 20) -> dict[str, Any] | None:
        """双向反查：哪些焦点能到达该节点。

        条目焦点 → 直挂分类（带 path）+ 同域名 + 同线索（kind=thread，带 thread.html url）；
        分类焦点 → 父分类 + 挂接条目 Top-N；域名节点不支持反查（返回 None）。
        """
        prefix, _, raw_id = node_id.partition(":")
        kind = self._RADIATE_KINDS.get(prefix)
        if kind is None or not raw_id or kind == "domain":
            return None

        items: list[dict[str, Any]] = []
        if kind == "entry":
            row = self._entry_row(raw_id)
            if row is None:
                return None
            for r in self._conn.execute(
                    "SELECT category_id, origin FROM entry_categories WHERE entry_id=?",
                    (raw_id,)).fetchall():
                paths = self.get_category_paths(r["category_id"])
                cname_row = self._conn.execute(
                    "SELECT name FROM categories WHERE id=?", (r["category_id"],)).fetchone()
                items.append({"kind": "category", "id": f"c:{r['category_id']}",
                              "name": cname_row["name"] if cname_row else "?",
                              "path": paths[0] if paths else "",
                              "reason": f"attach:{r['origin']}"})
            from urllib.parse import urlsplit
            host = urlsplit(row["locator"]).hostname or ""
            if host:
                items.append({"kind": "domain", "id": f"d:{host}", "name": host,
                              "reason": f"same_host:{host}"})
            for t in self.threads_for_entry(raw_id):
                items.append({"kind": "thread", "id": t["id"], "name": t["name"],
                              "url": f"/thread.html?id={t['id']}",
                              "reason": f"thread:{t['name']}"})
        else:  # category
            cat = self._conn.execute(
                "SELECT id, name FROM categories WHERE id=?", (raw_id,)).fetchone()
            if cat is None:
                return None
            parents = self._conn.execute(
                "SELECT c.id, c.name FROM category_parents cp"
                " JOIN categories c ON c.id=cp.parent_id WHERE cp.category_id=?"
                " ORDER BY c.name", (raw_id,)).fetchall()
            for r in parents:
                paths = self.get_category_paths(r["id"])
                items.append({"kind": "category", "id": f"c:{r['id']}", "name": r["name"],
                              "path": paths[0] if paths else "", "reason": "parent"})
            atts = self._conn.execute(
                "SELECT e.id, e.title, e.locator, ec.origin FROM entry_categories ec"
                " JOIN entries e ON e.id=ec.entry_id AND e.status='active'"
                + _consumable("e") +
                " WHERE ec.category_id=? ORDER BY e.created_at DESC LIMIT ?",
                (raw_id, limit)).fetchall()
            for r in atts:
                items.append({"kind": "entry", "id": f"e:{r['id']}",
                              "name": (r["title"] or r["locator"])[:40],
                              "reason": f"attach:{r['origin']}"})
        return {"focus": {"id": node_id, "kind": kind}, "items": items[:limit]}

    def delete_empty_categories(self, *, protect_manual: bool = True) -> list[str]:
        """删除「空壳」分类：无条目挂接且无子类。返回被删的 (id, name) 名单。

        protect_manual=True 时跳过 origin=manual（人工建的类目即使空也保留）。
        用途：reclassify 后清理不再被内容支撑的旧机器类目。
        """
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT c.id, c.name, c.origin FROM categories c"
                " WHERE NOT EXISTS (SELECT 1 FROM entry_categories ec WHERE ec.category_id=c.id)"
                "   AND NOT EXISTS (SELECT 1 FROM category_parents cp WHERE cp.parent_id=c.id)"
            ).fetchall()
            doomed = [(r["id"], r["name"]) for r in rows
                      if not (protect_manual and r["origin"] == "manual")]
            conn.executemany(
                "DELETE FROM category_parents WHERE category_id=?",
                [(d[0],) for d in doomed],
            )
            conn.executemany("DELETE FROM categories WHERE id=?", [(d[0],) for d in doomed])
        return doomed

    def prune_fragment_categories(self, min_size: int = 2) -> list[dict[str, Any]]:
        """收拢碎片类目：挂接条目数 < min_size 的非人工二级类目并入其一级父。

        条目挂接迁移到父类目（origin 保留），类目删除。返回操作记录供 task_log。
        多父类目迁移到首个父；无父类目不动（一级类目不收拢）。
        """
        moved: list[dict[str, Any]] = []
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT c.id, c.name, c.origin FROM categories c"
                " WHERE c.origin != 'manual'"
                "   AND EXISTS (SELECT 1 FROM category_parents cp WHERE cp.category_id=c.id)"
                "   AND (SELECT COUNT(DISTINCT entry_id) FROM entry_categories"
                "        WHERE category_id=c.id) < ?",
                (min_size,),
            ).fetchall()
            for r in rows:
                parents = [p["parent_id"] for p in conn.execute(
                    "SELECT parent_id FROM category_parents WHERE category_id=?",
                    (r["id"],)).fetchall()]
                if not parents:
                    continue
                target = parents[0]
                members = conn.execute(
                    "SELECT DISTINCT entry_id, origin FROM entry_categories WHERE category_id=?",
                    (r["id"],)).fetchall()
                for m in members:
                    conn.execute(
                        "INSERT OR REPLACE INTO entry_categories"
                        " (entry_id, category_id, confidence, origin, task_run_id)"
                        " VALUES (?,?,?,?,?)",
                        (m["entry_id"], target, 0.5, m["origin"], "prune-fragments"),
                    )
                conn.execute("DELETE FROM entry_categories WHERE category_id=?", (r["id"],))
                conn.execute("DELETE FROM category_parents WHERE category_id=?", (r["id"],))
                conn.execute("DELETE FROM categories WHERE id=?", (r["id"],))
                moved.append({"name": r["name"], "into": target, "entries": len(members)})
        return moved

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

    # ---- 词云视图（第四十三批：scoped cloud 聚合数据源） ----

    def category_names(self) -> dict[str, str]:
        """全部分类 id→name 映射（词云着色/前端展示用，只读轻查询）。"""
        return {r["id"]: r["name"] for r in
                self._conn.execute("SELECT id, name FROM categories").fetchall()}

    def cloud_data(self, category_id: str | None, *,
                   sample: int = 800) -> dict[str, Any]:
        """词云聚合数据源：focus 子树（None=全库）的分类词元 + 内容词元样本。

        返回：
        - focus: {id, name} | None（None=全库）；
        - categories: focus 的直接子分类及可消费条目数（focus=None 时顶层大类；
          空类剪枝——无可消费条目的不出）——「分类词元」，点击进入子分类；
        - entries: [(entry_id, title, body, top_cat_id)] 样本（子树内可消费
          条目 DISTINCT 近 sample 条；top_cat_id=直挂分类的顶层根，多父多根
          取最小 id 保确定性——显示口径非事实口径）。

        词元提取（jieba tf-idf）在 api 层做：SQL 与 NLP 分治，jieba 惰性导入。
        消费面口径与 _consumable 一致（不判 dead/value_flag/dedupe/freshness）。
        """
        if category_id:
            sub_ids = self._cat_descendants(category_id)
            if category_id not in sub_ids:
                return {"focus": None, "children": [], "entries": []}
        else:
            sub_ids = [r["id"] for r in self._conn.execute("SELECT id FROM categories")]
        if not sub_ids:
            return {"focus": None, "children": [], "entries": []}
        # 分类词元：focus 直接子分类（focus=None 时顶层）
        if category_id:
            kids = self._conn.execute(
                "SELECT c.id, c.name FROM category_parents cp"
                " JOIN categories c ON c.id=cp.category_id WHERE cp.parent_id=?"
                " ORDER BY c.name", (category_id,)).fetchall()
        else:
            kids = self._conn.execute(
                "SELECT id, name FROM categories"
                " WHERE id NOT IN (SELECT category_id FROM category_parents)"
                " ORDER BY name").fetchall()
        children = [{"id": r["id"], "name": r["name"],
                     "count": self._consumable_count(self._cat_descendants(r["id"]))}
                    for r in kids]
        children = [c for c in children if c["count"] > 0]
        # 内容词元样本：子树内可消费条目（去重，近 sample 条）
        marks = ",".join("?" * len(sub_ids))
        rows = self._conn.execute(
            "SELECT DISTINCT e.id, e.title, COALESCE(e.inline_content,'') AS body"
            " FROM entries e JOIN entry_categories ec ON ec.entry_id=e.id"
            f" WHERE ec.category_id IN ({marks}) AND e.status='active'"
            + _consumable("e") + " ORDER BY e.exported_at DESC LIMIT ?",
            (*sub_ids, sample)).fetchall()
        has_parent = {r["category_id"]
                      for r in self._conn.execute("SELECT category_id FROM category_parents")}
        entries: list[tuple[str, str, str, str | None]] = []
        for r in rows:
            cats = [x["category_id"] for x in self._conn.execute(
                "SELECT category_id FROM entry_categories WHERE entry_id=?", (r["id"],))]
            roots = []
            for cid in cats:
                anc = self._cat_ancestors(cid)
                roots.extend([a for a in anc if a not in has_parent] or ([cid] if cid not in has_parent else []))
            entries.append((r["id"], r["title"], r["body"],
                            min(roots) if roots else None))
        focus = None
        if category_id:
            frow = self._conn.execute("SELECT id, name FROM categories WHERE id=?",
                                      (category_id,)).fetchone()
            if frow is not None:
                focus = {"id": frow["id"], "name": frow["name"]}
        return {"focus": focus, "categories": children, "entries": entries}

    def cloud_facet(self, category_id: str | None, word: str,
                    limit: int = 50) -> list[Entry]:
        """词云 facet：focus 子树内可消费且标题/内联正文含该词的条目
        （内容词元点击 = facet 过滤当前范围；第四十三批）。"""
        if category_id:
            sub_ids = self._cat_descendants(category_id)
            if category_id not in sub_ids:
                return []
        else:
            sub_ids = [r["id"] for r in self._conn.execute("SELECT id FROM categories")]
        if not sub_ids:
            return []
        marks = ",".join("?" * len(sub_ids))
        rows = self._conn.execute(
            "SELECT DISTINCT e.* FROM entries e"
            " JOIN entry_categories ec ON ec.entry_id=e.id"
            f" WHERE ec.category_id IN ({marks}) AND e.status='active'"
            + _consumable("e")
            + " AND (e.title LIKE ? ESCAPE '\\' OR e.inline_content LIKE ? ESCAPE '\\')"
            " ORDER BY e.exported_at DESC LIMIT ?",
            (*sub_ids, self._like_pattern(word), self._like_pattern(word), limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    # ---- 时间线视图（第四十四批：scoped timeline + 陈旧分支提醒） ----

    def timeline_data(self, category_id: str | None, *, granularity: str | None = None,
                      bucket: str | None = None, stale_years: int = 2,
                      bucket_limit: int = 100) -> dict[str, Any]:
        """时间线聚合数据源：focus 子树（None=全库）按 created_at 分桶 +
        陈旧叶子分支提醒（长期无新内容）+ bucket 下钻条目。

        时间口径：created_at = 内容时间（书签收藏/文件创建时间）；exported_at
        是入库时间（全批同时刻，无分布意义）不用作轴。created_at 缺失的条目
        只进 unknown_count，不编造时间。

        granularity: "year"|"month"|None（None=自适应：跨度 >24 个月→year）。
        bucket: 传 key（如 "2020" / "2020-07"）时返回该桶条目列表 entries。
        stale_years: 叶子分支最新条目早于该年数 → 进 stale_branches（只提醒，
        不改任何数据；用户否决/清理走既有管理入口）。

        返回：{focus, granularity, buckets, unknown_count, span,
        stale_branches, unknown_branches, threshold_years, entries?}
        """
        if category_id:
            sub_ids = self._cat_descendants(category_id)
            if category_id not in sub_ids:
                return {"focus": None, "granularity": granularity or "year",
                        "buckets": [], "unknown_count": 0, "span": None,
                        "stale_branches": [], "unknown_branches": [],
                        "threshold_years": stale_years}
        else:
            sub_ids = [r["id"] for r in self._conn.execute("SELECT id FROM categories")]
        if not sub_ids:
            return {"focus": None, "granularity": granularity or "year",
                    "buckets": [], "unknown_count": 0, "span": None,
                    "stale_branches": [], "unknown_branches": [],
                    "threshold_years": stale_years}
        marks = ",".join("?" * len(sub_ids))
        base = (" FROM entries e JOIN entry_categories ec ON ec.entry_id=e.id"
                f" WHERE ec.category_id IN ({marks}) AND e.status='active'"
                + _consumable("e"))
        focus = None
        if category_id:
            frow = self._conn.execute("SELECT id, name FROM categories WHERE id=?",
                                      (category_id,)).fetchone()
            if frow is not None:
                focus = {"id": frow["id"], "name": frow["name"]}
        # 时间未知计数（created_at 缺失——不编造时间、不判陈旧）
        unknown_count = self._conn.execute(
            "SELECT count(DISTINCT e.id) AS n" + base
            + " AND (e.created_at IS NULL OR e.created_at='')",
            tuple(sub_ids)).fetchone()["n"]
        # 跨度与分桶粒度
        span_row = self._conn.execute(
            "SELECT min(substr(e.created_at,1,10)) AS lo, max(substr(e.created_at,1,10)) AS hi"
            + base + " AND e.created_at IS NOT NULL AND e.created_at != ''",
            tuple(sub_ids)).fetchone()
        span = {"min": span_row["lo"], "max": span_row["hi"]} if span_row["lo"] else None
        if granularity not in ("year", "month"):
            granularity = "year"
            if span and span["min"] and span["max"]:
                lo_y, lo_m = int(span["min"][:4]), int(span["min"][5:7])
                hi_y, hi_m = int(span["max"][:4]), int(span["max"][5:7])
                if (hi_y - lo_y) * 12 + (hi_m - lo_m) <= 24:
                    granularity = "month"
        width = 4 if granularity == "year" else 7
        counts: dict[str, int] = {}
        if span:
            for r in self._conn.execute(
                    "SELECT substr(e.created_at,1,?) AS k, count(DISTINCT e.id) AS n"
                    + base + " AND e.created_at IS NOT NULL AND e.created_at != ''"
                    " GROUP BY k", (width, *sub_ids)):
                counts[r["k"]] = r["n"]
            buckets = self._fill_buckets(span, granularity, counts)
        else:
            buckets = []
        out: dict[str, Any] = {
            "focus": focus, "granularity": granularity, "buckets": buckets,
            "unknown_count": unknown_count, "span": span,
            "threshold_years": stale_years,
        }
        if bucket:
            # bucket 前缀匹配（长度自适应）：month 粒度下传 "2020" 得全年，
            # 传 "2020-07" 得单月——前端传当前图桶 key，直调也不会因粒度落空
            rows = self._conn.execute(
                "SELECT DISTINCT e.*" + base
                + " AND e.created_at IS NOT NULL AND e.created_at != ''"
                + " AND substr(e.created_at,1,?) = ?"
                " ORDER BY e.exported_at DESC LIMIT ?",
                (*sub_ids, len(bucket), bucket, bucket_limit)).fetchall()
            out["entries"] = [self._row_to_entry(r) for r in rows]
        # 陈旧分支提醒：子树内叶子分类（无子节点），各自 max(created_at)
        out["stale_branches"], out["unknown_branches"] = self._stale_branches(
            sub_ids, stale_years=stale_years)
        return out

    @staticmethod
    def _fill_buckets(span: dict[str, str], granularity: str,
                      counts: dict[str, int]) -> list[dict[str, Any]]:
        """连续区间补齐空桶（柱状图轴均匀；稀疏年份不出空洞误导）。"""
        lo_y, lo_m = int(span["min"][:4]), int(span["min"][5:7])
        hi_y, hi_m = int(span["max"][:4]), int(span["max"][5:7])
        keys: list[str] = []
        if granularity == "year":
            keys = [str(y) for y in range(lo_y, hi_y + 1)]
        else:
            y, m = lo_y, lo_m
            while (y, m) <= (hi_y, hi_m):
                keys.append(f"{y:04d}-{m:02d}")
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return [{"key": k, "label": k, "count": counts.get(k, 0)} for k in keys]

    def _stale_branches(self, sub_ids: list[str], *,
                        stale_years: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """子树内叶子分类的陈旧判定（第四十四批）。叶子 = 无子节点的分类
        （category_parents.parent_id 列里从不出现的分类；该表一行
        (category_id, parent_id) 表示 category_id 的父是 parent_id）。

        只提醒不改数据（只标不删可逆模型）：latest 超 stale_years 年 →
        stale_branches；created_at 全缺 → unknown_branches（时间未知 ≠ 陈旧）。
        """
        leaves = [r["id"] for r in self._conn.execute(
            "SELECT id FROM categories"
            " WHERE id NOT IN (SELECT parent_id FROM category_parents)"
            "   AND id IN (%s)" % ",".join("?" * len(sub_ids)),
            tuple(sub_ids))]
        stale: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []
        for cid in leaves:
            ids = self._cat_descendants(cid)
            if cid not in ids:
                ids.append(cid)
            marks = ",".join("?" * len(ids))
            row = self._conn.execute(
                "SELECT count(DISTINCT e.id) AS n, max(e.created_at) AS latest"
                " FROM entries e JOIN entry_categories ec ON ec.entry_id=e.id"
                f" WHERE ec.category_id IN ({marks}) AND e.status='active'"
                + _consumable("e"), tuple(ids)).fetchone()
            if not row["n"]:
                continue  # 空叶子不提醒（可能条目被舍弃/归档后清空）
            name = self._conn.execute("SELECT name FROM categories WHERE id=?",
                                      (cid,)).fetchone()["name"]
            item = {"id": cid, "name": name, "latest": row["latest"], "count": row["n"]}
            if not row["latest"]:
                unknown.append(item)
                continue
            latest = datetime.fromisoformat(row["latest"])
            if latest.tzinfo is None:  # 统一到 aware 再比（created_at 带时区偏移）
                latest = latest.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - latest).days / 365.25
            item["age_years"] = round(age, 1)
            if age >= stale_years:
                stale.append(item)
        stale.sort(key=lambda x: -x["age_years"])
        return stale, unknown

    def get_tree(self) -> list[dict[str, Any]]:
        """返回多父 DAG 展平的树（按根展开；多父节点会在每个父下出现）。

        每个节点带 count = 该子树（含自身、含多父重复出现）的 active 条目数——
        供 UI 默认隐藏空枝：分类节点本身不删（可能只是条目被舍弃/归档后清空），
        但不再占视线；用户勾选「显示空分类」后可见。
        """
        cats = {r["id"]: dict(r) for r in
                self._conn.execute("SELECT * FROM categories").fetchall()}
        children: dict[str | None, list[str]] = {}
        has_parent: set[str] = set()
        for r in self._conn.execute("SELECT category_id, parent_id FROM category_parents"):
            children.setdefault(r["parent_id"], []).append(r["category_id"])
            has_parent.add(r["category_id"])
        paths = dict(self._all_paths())
        first_path: dict[str, str] = {}
        for cid, p in paths.items():
            first_path.setdefault(cid, p)

        # active 直挂映射（一次查询拿全，Python 侧自底向上聚合子树数）
        own: dict[str, set[str]] = {}
        for r in self._conn.execute(
                "SELECT ec.category_id, ec.entry_id FROM entry_categories ec"
                " JOIN entries e ON e.id=ec.entry_id WHERE e.status='active'"):
            own.setdefault(r["category_id"], set()).add(r["entry_id"])
        memo: dict[str, set[str]] = {}

        def subtree_entries(cid: str) -> set[str]:
            if cid in memo:
                return memo[cid]
            memo[cid] = set()  # 防环占位（多父 DAG 无环时可被后续覆盖）
            acc = set(own.get(cid, ()))
            for k in children.get(cid, []):
                acc |= subtree_entries(k)
            memo[cid] = acc
            return acc

        def build(cid: str) -> dict[str, Any]:
            c = cats[cid]
            return {
                "id": cid, "name": c["name"], "origin": c["origin"],
                "path": first_path.get(cid, c["name"]),
                "count": len(subtree_entries(cid)),
                "children": [build(k) for k in sorted(children.get(cid, []))],
            }

        roots = sorted(cid for cid in cats if cid not in has_parent)
        return [build(cid) for cid in roots]

    def subtree_category_ids(self, category_id: str) -> set[str]:
        """分类子树（含自身）的全部 id——自父链向下收集，多父去重。"""
        result = {category_id}
        down: dict[str, list[str]] = {}
        for r in self._conn.execute("SELECT category_id, parent_id FROM category_parents"):
            down.setdefault(r["parent_id"], []).append(r["category_id"])
        stack = [category_id]
        while stack:
            cur = stack.pop()
            for child in down.get(cur, []):
                if child not in result:
                    result.add(child)
                    stack.append(child)
        return result

    def get_entries_for_categories(self, category_ids: set[str], *,
                                   source_type: str | None = None,
                                   status: str = "active",
                                   limit: int = 200) -> list[Entry]:
        if not category_ids:
            return []
        marks = ",".join("?" for _ in category_ids)
        sql = (
            "SELECT DISTINCT e.* FROM entries e"
            f" JOIN entry_categories ec ON ec.entry_id = e.id"
            f" WHERE ec.category_id IN ({marks}) AND e.status=?" + _consumable("e")
        )
        params: list[Any] = [*category_ids, status]
        if source_type:
            sql += " AND e.source_type=?"
            params.append(source_type)
        sql += " ORDER BY e.exported_at DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_entry(r) for r in self._conn.execute(sql, params).fetchall()]

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

    # ---- Thread 串联工作区（完整方案 §9.4，0.2.0 第三十二批） ----
    # 写操作全部落 task_log（task_name=threads）；position 从 0 起紧凑编号。

    _THREAD_NAME_MAX = 200
    _RELATION_MAX = 32

    def _validate_thread_type(self, thread_type: str) -> None:
        if thread_type not in THREAD_TYPES:
            raise ContractError(
                f"thread_type 非法：{thread_type!r}（允许 {list(THREAD_TYPES)}）")

    def create_thread(self, name: str, note: str | None = None,
                      thread_type: str = "curated") -> Thread:
        name = (name or "").strip()
        if not name or len(name) > self._THREAD_NAME_MAX:
            raise ContractError(
                f"线索名非法（需 1..{self._THREAD_NAME_MAX} 字符）：{name!r}")
        self._validate_thread_type(thread_type)
        tid = uuid.uuid4().hex[:16]
        now = _now()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO threads (id, name, note, thread_type, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?)",
                (tid, name, note, thread_type, now, now),
            )
            self.log_task(now, "threads", "create", tid,
                          {"name": name, "thread_type": thread_type})
        return Thread(id=tid, name=name, note=note, thread_type=thread_type,
                      created_at=now, updated_at=now)

    def get_thread(self, thread_id: str) -> Thread | None:
        row = self._conn.execute(
            "SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
        if row is None:
            return None
        items = self._conn.execute(
            "SELECT i.* FROM thread_items i WHERE i.thread_id=?"
            " AND EXISTS (SELECT 1 FROM entries e WHERE e.id=i.entry_id"
            "   AND e.status='active'" + _consumable("e") + ")"
            " ORDER BY i.position, i.rowid",
            (thread_id,),
        ).fetchall()
        return Thread(id=row["id"], name=row["name"], note=row["note"],
                      thread_type=row["thread_type"], created_at=row["created_at"],
                      updated_at=row["updated_at"],
                      items=tuple(self._row_to_item(r) for r in items))

    def list_threads(self, thread_type: str | None = None,
                     limit: int = 200) -> list[dict[str, Any]]:
        """线索列表（不含 items；带 item_count 供 UI 展示）。"""
        sql = ("SELECT t.*, (SELECT COUNT(*) FROM thread_items i"
               " WHERE i.thread_id = t.id) AS item_count FROM threads t")
        params: list[Any] = []
        if thread_type is not None:
            self._validate_thread_type(thread_type)
            sql += " WHERE t.thread_type=?"
            params.append(thread_type)
        sql += " ORDER BY t.updated_at DESC, t.rowid DESC LIMIT ?"
        params.append(limit)
        return [
            {"id": r["id"], "name": r["name"], "note": r["note"],
             "thread_type": r["thread_type"], "item_count": r["item_count"],
             "created_at": r["created_at"], "updated_at": r["updated_at"]}
            for r in self._conn.execute(sql, params).fetchall()
        ]

    def update_thread(self, thread_id: str, name: str | None = None,
                      note: str | None = None) -> None:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
            if row is None:
                raise ContractError(f"线索不存在：{thread_id}")
            fields: dict[str, Any] = {}
            if name is not None:
                new_name = name.strip()
                if not new_name or len(new_name) > self._THREAD_NAME_MAX:
                    raise ContractError(
                        f"线索名非法（需 1..{self._THREAD_NAME_MAX} 字符）：{new_name!r}")
                fields["name"] = new_name
            if note is not None:
                fields["note"] = note
            if not fields:
                return
            assignments = ", ".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE threads SET {assignments}, updated_at=? WHERE id=?",
                (*fields.values(), _now(), thread_id),
            )
            self.log_task(_now(), "threads", "update", thread_id,
                          {"changed": sorted(fields)})

    def delete_thread(self, thread_id: str) -> None:
        """删除线索；thread_items 经 FK ON DELETE CASCADE 级联清除。"""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT name FROM threads WHERE id=?", (thread_id,)).fetchone()
            if row is None:
                raise ContractError(f"线索不存在：{thread_id}")
            conn.execute("DELETE FROM threads WHERE id=?", (thread_id,))
            self.log_task(_now(), "threads", "delete", thread_id, {"name": row["name"]})

    def add_thread_item(self, thread_id: str, entry_id: str,
                        relation_type: str = "seq",
                        note: str | None = None) -> ThreadItem:
        relation_type = (relation_type or "seq").strip() or "seq"
        if len(relation_type) > self._RELATION_MAX:
            raise ContractError(
                f"relation_type 超长（>{self._RELATION_MAX}）：{relation_type!r}")
        with self.transaction() as conn:
            thread = conn.execute(
                "SELECT id FROM threads WHERE id=?", (thread_id,)).fetchone()
            if thread is None:
                raise ContractError(f"线索不存在：{thread_id}")
            entry = conn.execute(
                "SELECT id FROM entries WHERE id=?", (entry_id,)).fetchone()
            if entry is None:
                raise ContractError(f"条目不存在：{entry_id}")
            dup = conn.execute(
                "SELECT id FROM thread_items WHERE thread_id=? AND entry_id=?",
                (thread_id, entry_id),
            ).fetchone()
            if dup is not None:
                raise ContractError(
                    f"条目已在该线索中（item_id={dup['id']}）",
                    hint="同一线索内条目唯一；换关系类型用 update_thread_item")
            position = conn.execute(
                "SELECT COALESCE(MAX(position)+1, 0) FROM thread_items WHERE thread_id=?",
                (thread_id,),
            ).fetchone()[0]
            iid = uuid.uuid4().hex[:16]
            conn.execute(
                "INSERT INTO thread_items (id, thread_id, entry_id, position, relation_type, note)"
                " VALUES (?,?,?,?,?,?)",
                (iid, thread_id, entry_id, position, relation_type, note),
            )
            conn.execute("UPDATE threads SET updated_at=? WHERE id=?", (_now(), thread_id))
            self.log_task(_now(), "threads", "item_add", thread_id,
                          {"item_id": iid, "entry_id": entry_id, "position": position,
                           "relation_type": relation_type})
        return ThreadItem(id=iid, thread_id=thread_id, entry_id=entry_id,
                          position=position, relation_type=relation_type, note=note)

    def remove_thread_item(self, thread_id: str, item_id: str) -> None:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM thread_items WHERE thread_id=? AND id=?",
                (thread_id, item_id),
            ).fetchone()
            if row is None:
                raise ContractError(f"线索条目不存在：thread={thread_id} item={item_id}")
            conn.execute("DELETE FROM thread_items WHERE id=?", (item_id,))
            self._compact_positions(conn, thread_id)
            conn.execute("UPDATE threads SET updated_at=? WHERE id=?", (_now(), thread_id))
            self.log_task(_now(), "threads", "item_remove", thread_id, {"item_id": item_id})

    def move_thread_item(self, thread_id: str, item_id: str, new_position: int) -> None:
        """把线索内条目移到新位置（0 起；越界夹紧），其余条目顺移、序号紧凑重写。"""
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT id FROM thread_items WHERE thread_id=? ORDER BY position, rowid",
                (thread_id,),
            ).fetchall()
            order = [r["id"] for r in rows]
            if item_id not in order:
                raise ContractError(f"线索条目不存在：thread={thread_id} item={item_id}")
            target = max(0, min(int(new_position), len(order) - 1))
            order.remove(item_id)
            order.insert(target, item_id)
            for pos, iid in enumerate(order):
                conn.execute("UPDATE thread_items SET position=? WHERE id=?", (pos, iid))
            conn.execute("UPDATE threads SET updated_at=? WHERE id=?", (_now(), thread_id))
            self.log_task(_now(), "threads", "item_move", thread_id,
                          {"item_id": item_id, "new_position": target})

    def reorder_thread_items(self, thread_id: str, entry_ids: Sequence[str]) -> None:
        """按给定 entry_id 顺序整线重写 position（thread_suggest 应用建议排序用）。

        传入集合必须与线索现有条目一致（不多不少）——不一致说明调用方拿了过期
        数据，直接报错而不是静默丢条目。
        """
        wanted = list(entry_ids)
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT entry_id FROM thread_items WHERE thread_id=? ORDER BY position, rowid",
                (thread_id,),
            ).fetchall()
            current = [r["entry_id"] for r in rows]
            if sorted(wanted) != sorted(current):
                raise ContractError(
                    "重排条目集与线索现有条目不一致",
                    hint="传入的 entry_ids 必须恰好覆盖线索内全部条目（先刷新线索再应用排序）")
            for pos, eid in enumerate(wanted):
                conn.execute(
                    "UPDATE thread_items SET position=? WHERE thread_id=? AND entry_id=?",
                    (pos, thread_id, eid),
                )
            conn.execute("UPDATE threads SET updated_at=? WHERE id=?", (_now(), thread_id))

    def update_thread_item(self, thread_id: str, item_id: str,
                           relation_type: str | None = None,
                           note: str | None = None) -> None:
        """改线索条目属性（relation_type / note）；校验条目归属该线索。"""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM thread_items WHERE thread_id=? AND id=?",
                (thread_id, item_id),
            ).fetchone()
            if row is None:
                raise ContractError(f"线索条目不存在：thread={thread_id} item={item_id}")
            fields: dict[str, Any] = {}
            if relation_type is not None:
                rt = relation_type.strip() or "seq"
                if len(rt) > self._RELATION_MAX:
                    raise ContractError(f"relation_type 超长（>{self._RELATION_MAX}）：{rt!r}")
                fields["relation_type"] = rt
            if note is not None:
                fields["note"] = note
            if not fields:
                return
            assignments = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE thread_items SET {assignments} WHERE id=?",
                         (*fields.values(), item_id))
            conn.execute("UPDATE threads SET updated_at=? WHERE id=?",
                         (_now(), row["thread_id"]))
            self.log_task(_now(), "threads", "item_update", row["thread_id"],
                          {"item_id": item_id, "changed": sorted(fields)})

    @staticmethod
    def _compact_positions(conn: sqlite3.Connection, thread_id: str) -> None:
        """序号紧凑重写（0..n-1）——删除/移动后消除空洞。"""
        rows = conn.execute(
            "SELECT id FROM thread_items WHERE thread_id=? ORDER BY position, rowid",
            (thread_id,),
        ).fetchall()
        for pos, r in enumerate(rows):
            conn.execute("UPDATE thread_items SET position=? WHERE id=?", (pos, r["id"]))

    def threads_for_entry(self, entry_id: str) -> list[dict[str, Any]]:
        """条目挂在哪些线索里（UI 徽标与 topic_recall 显式关联通道用）。"""
        rows = self._conn.execute(
            "SELECT t.id, t.name, t.thread_type FROM thread_items i"
            " JOIN threads t ON t.id = i.thread_id WHERE i.entry_id=?"
            " ORDER BY t.updated_at DESC",
            (entry_id,),
        ).fetchall()
        return [{"id": r["id"], "name": r["name"], "thread_type": r["thread_type"]}
                for r in rows]

    # ---- 会话消息（0.2.0 第三十九批：邮件源原始会话线程还原） ----

    def upsert_conv_messages(self, messages: Sequence[dict[str, Any]]) -> None:
        """批量落 conv_messages（邮件适配器；键=message_id 归一，幂等覆盖）。"""
        with self.transaction() as conn:
            for m in messages:
                conn.execute(
                    "INSERT INTO conv_messages (id, entry_id, in_reply_to,"
                    " subject_norm, sent_at, thread_id) VALUES (?,?,?,?,?,?)"
                    " ON CONFLICT(id) DO UPDATE SET entry_id=excluded.entry_id,"
                    " in_reply_to=excluded.in_reply_to,"
                    " subject_norm=excluded.subject_norm, sent_at=excluded.sent_at,"
                    " thread_id=COALESCE(conv_messages.thread_id, excluded.thread_id)",
                    (m["id"], m["entry_id"], m.get("in_reply_to"),
                     m.get("subject_norm", ""), m.get("sent_at"), m.get("thread_id")),
                )

    def list_conv_messages(self) -> list[dict[str, Any]]:
        """全部会话消息（线程分组用）。"""
        rows = self._conn.execute(
            "SELECT id, entry_id, in_reply_to, subject_norm, sent_at, thread_id"
            " FROM conv_messages ORDER BY sent_at, id").fetchall()
        return [{"id": r["id"], "entry_id": r["entry_id"],
                 "in_reply_to": r["in_reply_to"], "subject_norm": r["subject_norm"],
                 "sent_at": r["sent_at"], "thread_id": r["thread_id"]} for r in rows]

    def set_conv_thread(self, message_ids: Sequence[str], thread_id: str) -> None:
        """把消息映射到线程（分组结果持久化）。"""
        with self.transaction() as conn:
            conn.executemany(
                "UPDATE conv_messages SET thread_id=? WHERE id=?",
                [(thread_id, mid) for mid in message_ids])

    # ---- 检索 ----

    def search_fts(self, query: str, limit: int = 50) -> list[SearchHit]:
        """混合入口的 FTS 级。

        trigram 分词器对 <3 字符查询零命中（H2 返工定稿），两字词走 LIKE 兜底；
        有会红的测试钉住（tests/test_datalayer.py::test_two_char_query_finds_content）。
        """
        q = query.strip()
        if not q:
            return []
        if len(q) >= 3:
            match = '"' + q.replace('"', '""') + '"'
            try:
                rows = self._conn.execute(
                    "SELECT e.id, e.title, e.locator,"
                    " snippet(entries_fts, 0, '[', ']', '…', 12) AS snip,"
                    " bm25(entries_fts) AS rank"
                    " FROM entries_fts JOIN entries e ON e.rowid = entries_fts.rowid"
                    " WHERE entries_fts MATCH ? AND e.status='active'"
                    + _consumable("e") +
                    " ORDER BY rank LIMIT ?",
                    (match, limit),
                ).fetchall()
                return [SearchHit(r["id"], r["title"], r["locator"], r["snip"], r["rank"])
                        for r in rows]
            except sqlite3.OperationalError:
                pass  # 语法不兼容等异常 → 落到 LIKE 兜底
        return self._search_like(q, limit)

    @staticmethod
    def _escape_like(q: str) -> str:
        return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _search_like(self, q: str, limit: int) -> list[SearchHit]:
        like = f"%{self._escape_like(q)}%"
        rows = self._conn.execute(
            "SELECT e.id, e.title, e.locator, substr(COALESCE(e.inline_content,''),1,80) AS snip,"
            " 1.0 AS rank FROM entries e"
            " WHERE e.status='active'" + _consumable("e") + " AND (e.title LIKE ? ESCAPE '\\'"
            "    OR e.native_path LIKE ? ESCAPE '\\'"
            "    OR e.inline_content LIKE ? ESCAPE '\\')"
            " UNION"
            " SELECT e.id, e.title, e.locator, substr(COALESCE(e.inline_content,''),1,80) AS snip,"
            " 1.0 AS rank FROM entries e"
            " JOIN content_fts c ON c.content_hash = e.content_hash"
            " WHERE e.status='active'" + _consumable("e") + " AND c.text LIKE ? ESCAPE '\\'"
            " LIMIT ?",
            (like, like, like, like, limit),
        ).fetchall()
        return [SearchHit(r["id"], r["title"], r["locator"], r["snip"], r["rank"]) for r in rows]

    # ---- 日志与运行记录 ----

    def log_task(self, at: str, task_name: str, action: str, target: str,
                 detail: dict[str, Any]) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO task_log (at, task_name, action, target, detail) VALUES (?,?,?,?,?)",
                (at, task_name, action, target, _meta_json(detail)),
            )

    def get_task_log(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM task_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [{"id": r["id"], "at": r["at"], "task_name": r["task_name"],
                 "action": r["action"], "target": r["target"],
                 "detail": json.loads(r["detail"])} for r in rows]

    def start_run(self, run_id: str, kind: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs (id, kind, started_at, finished_at, stats)"
                " VALUES (?,?,?,NULL,'{}')",
                (run_id, kind, _now()),
            )

    def finish_run(self, run_id: str, stats: dict[str, Any]) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE runs SET finished_at=?, stats=? WHERE id=?",
                (_now(), _meta_json(stats), run_id),
            )

    def recent_runs(self, limit: int = 5) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [{"id": r["id"], "kind": r["kind"], "started_at": r["started_at"],
                 "finished_at": r["finished_at"], "stats": json.loads(r["stats"])}
                for r in rows]

    # ---- 统计（web /api/stats 用） ----

    def get_stats(self) -> dict[str, Any]:
        by_source = {
            r["source_type"]: r["n"] for r in self._conn.execute(
                "SELECT source_type, COUNT(*) AS n FROM entries"
                " WHERE status='active' GROUP BY source_type"
            )
        }
        uncategorized = self._conn.execute(
            "SELECT COUNT(*) AS n FROM entries e"
            " LEFT JOIN entry_categories ec ON ec.entry_id = e.id"
            " WHERE ec.entry_id IS NULL AND e.status='active'"
        ).fetchone()["n"]
        archived = self._conn.execute(
            "SELECT COUNT(*) AS n FROM entries WHERE status='archived'"
        ).fetchone()["n"]
        contents = self._conn.execute("SELECT COUNT(*) AS n FROM content_store").fetchone()["n"]
        return {"by_source": by_source, "uncategorized": uncategorized,
                "archived": archived, "contents": contents,
                "recent_runs": self.recent_runs(5)}

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
