"""向量域：条目向量与点向量的 BLOB 存取（数学在 semantic/embed.py）。"""

from __future__ import annotations

from typing import Any

from ._common import _now


class _VectorsMixin:
    # ---- 条目向量（迁移 006，第五十六批；只存取 BLOB，数学在 semantic/embed.py） ----

    def put_vectors(self, records: list[dict[str, Any]]) -> int:
        """批量 upsert 条目向量 {entry_id, dim, vector(bytes), model}；返回写入数。"""
        if not records:
            return 0
        now = _now()
        with self.transaction() as conn:
            for r in records:
                conn.execute(
                    "INSERT INTO entry_vectors (entry_id, dim, vector, model, created_at) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(entry_id) DO UPDATE SET "
                    "dim=excluded.dim, vector=excluded.vector, model=excluded.model, "
                    "created_at=excluded.created_at",
                    (r["entry_id"], int(r["dim"]), r["vector"], r["model"], now),
                )
        self.log_task(now, "vectors", "put", records[0]["model"],
                      {"count": len(records), "model": records[0]["model"]})
        return len(records)

    def get_vector(self, entry_id: str) -> dict[str, Any] | None:
        """单条向量 {entry_id, dim, vector(bytes), model}；无则 None。"""
        row = self._conn.execute(
            "SELECT entry_id, dim, vector, model FROM entry_vectors WHERE entry_id=?",
            (entry_id,)).fetchone()
        return dict(row) if row else None

    def all_vectors(self, model: str | None = None) -> dict[str, bytes]:
        """{entry_id: vector_bytes}（model 过滤；缺省取全部——单模型场景够用）。"""
        if model:
            rows = self._conn.execute(
                "SELECT entry_id, vector FROM entry_vectors WHERE model=?",
                (model,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT entry_id, vector FROM entry_vectors").fetchall()
        return {r["entry_id"]: r["vector"] for r in rows}

    def count_vectors(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM entry_vectors").fetchone()[0]

    def delete_vectors(self, entry_ids: list[str]) -> None:
        with self.transaction() as conn:
            conn.executemany("DELETE FROM entry_vectors WHERE entry_id=?",
                             [(e,) for e in entry_ids])

    # ---- 点向量（迁移 009，批次 87；与条目向量同构——只存取 BLOB，数学在
    #      semantic/embed.py；点 text 是抽取产物可重抽，本表可随时重建） ----

    def put_point_vectors(self, records: list[dict[str, Any]]) -> int:
        """批量 upsert 点向量 {point_id, dim, vector(bytes), model}；返回写入数。"""
        if not records:
            return 0
        now = _now()
        with self.transaction() as conn:
            for r in records:
                conn.execute(
                    "INSERT INTO point_vectors (point_id, dim, vector, model, created_at) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(point_id) DO UPDATE SET "
                    "dim=excluded.dim, vector=excluded.vector, model=excluded.model, "
                    "created_at=excluded.created_at",
                    (r["point_id"], int(r["dim"]), r["vector"], r["model"], now),
                )
        self.log_task(now, "point_vectors", "put", records[0]["model"],
                      {"count": len(records), "model": records[0]["model"]})
        return len(records)

    def all_point_vectors(self, model: str | None = None) -> dict[str, bytes]:
        """{point_id: vector_bytes}（model 过滤；缺省取全部——单模型场景够用）。"""
        if model:
            rows = self._conn.execute(
                "SELECT point_id, vector FROM point_vectors WHERE model=?",
                (model,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT point_id, vector FROM point_vectors").fetchall()
        return {r["point_id"]: r["vector"] for r in rows}

    def all_points_text(self) -> dict[str, str]:
        """{point_id: text}（向量构建原料；text 是抽取产物，全量点均可编码）。"""
        rows = self._conn.execute("SELECT id, text FROM points").fetchall()
        return {r["id"]: (r["text"] or "") for r in rows}

    def count_point_vectors(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM point_vectors").fetchone()[0]

    def points_fingerprint(self) -> str:
        """点域指纹（R14，主题聚合缓存的失效依据）。

        `点数:最新点时间:向量数:最新向量时间`。任何一次 kpoints 重抽（删后重插）
        或 ksync --embed（向量重建）都会改动 COUNT 或 MAX(created_at)，指纹随之
        变化——缓存因此无需手工失效，也不怕「同数不同内容」的重建。
        只读两行聚合查询，真库 4500 点实测 < 10 ms。
        """
        p = self._conn.execute(
            "SELECT COUNT(*) AS n, MAX(created_at) AS m FROM points").fetchone()
        v = self._conn.execute(
            "SELECT COUNT(*) AS n, MAX(created_at) AS m FROM point_vectors").fetchone()
        return f"{p['n']}:{p['m'] or ''}:{v['n']}:{v['m'] or ''}"

