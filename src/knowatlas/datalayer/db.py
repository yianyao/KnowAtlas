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
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from ..errors import ContractError, LocatorFormatError
from ..models import (
    SCHEMES, SOURCE_TYPES, STATUSES,
    Category, Entry, FetchResult, SearchHit, UpsertResult,
)
from .schema import USER_VERSION, load_initial_schema

_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_ORIGINS = ("prior", "rule", "embedding", "llm", "manual")
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
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self._conn.executescript(load_initial_schema())
            self._conn.execute(f"PRAGMA user_version = {USER_VERSION}")
            self._conn.commit()
            return USER_VERSION
        if version != USER_VERSION:
            raise ContractError(
                f"数据库 user_version={version} 与代码期望 {USER_VERSION} 不一致",
                hint="迁移只进不前：新增 migrations/00N_*.sql，禁止修改历史迁移",
            )
        return version

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
            "SELECT id, title, locator FROM entries WHERE status='active' LIMIT ?",
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
            ph = ",".join("?" * len(ids))
            count = self._conn.execute(
                "SELECT count(DISTINCT ec.entry_id) FROM entry_categories ec"
                " JOIN entries e ON e.id=ec.entry_id AND e.status='active'"
                f" WHERE ec.category_id IN ({ph})", ids).fetchone()[0]
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
            f" WHERE ec.category_id IN ({ph}) AND e.status='active'"
            " ORDER BY e.created_at DESC LIMIT ?", (*sub_ids, limit)).fetchall()
        entry_ids = [e["id"] for e in entries]
        nodes: list[dict[str, Any]] = [
            {"id": f"c:{a}", "name": cats.get(a, "?"), "kind": "category", "ctx": True}
            for a in anc_ids]
        for cid in sub_ids:
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
        """合并写入条目 meta（浅合并 patch；条目不存在时静默跳过）。"""
        with self.transaction() as conn:
            row = conn.execute("SELECT meta FROM entries WHERE id=?", (entry_id,)).fetchone()
            if row is None:
                return
            meta = json.loads(row["meta"])
            meta.update(patch)
            conn.execute("UPDATE entries SET meta=? WHERE id=?", (_meta_json(meta), entry_id))

    def list_by_value_flag(self, value_flag: str, limit: int = 500) -> list[Entry]:
        """按价值标记列出条目（meta.value_flag；not_knowledge = 规则或 LLM 判非知识，待用户清理）。"""
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE status='active'"
            "   AND json_extract(meta, '$.value_flag')=? ORDER BY rowid LIMIT ?",
            (value_flag, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

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
            f" WHERE ec.category_id IN ({marks}) AND e.status=?"
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
                    " WHERE entries_fts MATCH ? ORDER BY rank LIMIT ?",
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
            " WHERE e.status='active' AND (e.title LIKE ? ESCAPE '\\'"
            "    OR e.native_path LIKE ? ESCAPE '\\'"
            "    OR e.inline_content LIKE ? ESCAPE '\\')"
            " UNION"
            " SELECT e.id, e.title, e.locator, substr(COALESCE(e.inline_content,''),1,80) AS snip,"
            " 1.0 AS rank FROM entries e"
            " JOIN content_fts c ON c.content_hash = e.content_hash"
            " WHERE e.status='active' AND c.text LIKE ? ESCAPE '\\'"
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
