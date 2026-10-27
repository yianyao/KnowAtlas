"""分类域：DAG 增删改移、路径、挂载/摘除、空分类清理。"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Sequence

from ..errors import ContractError
from ..models import Category
from ._common import _ORIGINS, _PATHS_CTE, _now


class _CategoriesMixin:
    def all_categories_dag(self) -> list[dict[str, Any]]:
        """全部分类的原始 DAG 投影（id/name/note/origin/created_at/parents/first_path）——
        导出用（第四十五批）；多父分类在每个父的 children 展开由调用方按 parents 重建。"""
        cats = {r["id"]: dict(r) for r in
                self._conn.execute("SELECT * FROM categories").fetchall()}
        parents: dict[str, list[str]] = {}
        for r in self._conn.execute("SELECT category_id, parent_id FROM category_parents"):
            parents.setdefault(r["category_id"], []).append(r["parent_id"])
        paths = dict(self._all_paths())
        return [
            {"id": cid, "name": c["name"], "note": c["note"], "origin": c["origin"],
             "created_at": c["created_at"], "parents": sorted(parents.get(cid, [])),
             "path": paths.get(cid, c["name"])}
            for cid, c in sorted(cats.items(), key=lambda kv: kv[1]["name"])]

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

    # ---- 词云视图（第四十三批：scoped cloud 聚合数据源） ----

    def category_names(self) -> dict[str, str]:
        """全部分类 id→name 映射（词云着色/前端展示用，只读轻查询）。"""
        return {r["id"]: r["name"] for r in
                self._conn.execute("SELECT id, name FROM categories").fetchall()}

