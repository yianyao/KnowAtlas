"""运维域：任务日志、运行记录（runs）、回归测试集（regress）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ._common import _meta_json, _now, _parse_iso


def _elapsed_seconds(started: Any, finished: Any) -> float | None:
    """两个 ISO 时间串相差的秒数；任一侧为空串/坏串 → None（视图里显示「—」）。"""
    a, b = _parse_iso(started), _parse_iso(finished)
    if a is None or b is None:
        return None
    return round((b - a).total_seconds(), 1)


class _OpsMixin:
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

    def list_task_log_actions(self, task_name: str, action: str) -> list[dict[str, Any]]:
        """按 task_name+action 全量过滤 task_log（升序；回填/审计类遍历场景用）。

        与 get_task_log 的区别：后者是无过滤的最近 N 条倒序快照；
        本方法服务「扫描全部历史动作」的批量场景，detail 保持 JSON 串
        （量大时省解析，调用方按需 json.loads）。
        """
        rows = self._conn.execute(
            "SELECT target, detail, at FROM task_log"
            " WHERE task_name=? AND action=? ORDER BY id",
            (task_name, action),
        ).fetchall()
        return [{"target": r["target"], "detail": r["detail"], "at": r["at"]}
                for r in rows]

    # ---- 回归测试集（004_regress，0.2.0 第五十一批）----

    def add_regress_case(self, entry_id: str, expected_path: str,
                         note: str = "", source: str = "manual",
                         confirmed_at: str | None = None) -> None:
        """确认一条回归案例（同条目重复确认 = 覆盖旧确认，改主意语义）。"""
        stamp = confirmed_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO regress_cases"
                " (entry_id, expected_path, note, source, confirmed_at) VALUES (?,?,?,?,?)",
                (entry_id, expected_path, note, source, stamp),
            )

    def list_regress_cases(self) -> list[dict[str, Any]]:
        """全量回归案例（含条目投影供重跑分类用；条目已删的随 CASCADE 消失）。"""
        rows = self._conn.execute(
            "SELECT rc.entry_id, rc.expected_path, rc.note, rc.source,"
            " rc.confirmed_at, e.title, e.source_type, e.locator, e.native_path,"
            " e.inline_content, e.content_hash, e.meta"
            " FROM regress_cases rc JOIN entries e ON e.id = rc.entry_id"
            " ORDER BY rc.confirmed_at",
        ).fetchall()
        return [dict(r) for r in rows]

    def count_regress_cases(self) -> int:
        row = self._conn.execute("SELECT count(*) AS n FROM regress_cases").fetchone()
        return int(row["n"])

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

    # ---- 任务视图（2026-10-28，工单《任务视图 API》）----

    @staticmethod
    def _run_row(row: Any) -> dict[str, Any]:
        """runs 行 → 视图投影（私有；不加锁，由调用方持锁）。"""
        stats = json.loads(row["stats"] or "{}")
        started, finished = row["started_at"], row["finished_at"]
        return {"id": row["id"], "kind": row["kind"],
                "started_at": started, "finished_at": finished,
                "duration_s": _elapsed_seconds(started, finished),
                "unfinished": finished is None,
                "dry_run": bool(stats.get("dry_run")), "stats": stats}

    def task_overview(self, recent: int = 10) -> dict[str, Any]:
        """任务运行概览（只读，`/api/tasks` 用）：每类任务最新一轮 + 最近 N 条明细。

        为什么不用 `recent_runs(5)`：那是全表倒序 5 条，会被 sync_incremental 之类
        挤满，取不到「上一轮巡检」；这里先按 kind 聚合，再各取最新一行。

        - `unfinished`：`finished_at` 为空（进程被中断或仍在跑）——「没跑完」本身是信号；
        - `dry_run`：试跑也写 runs（审计口径），视图必须区分，否则会当成上一轮实跑；
        - `duration_s`：起止都为 ISO 时相减，坏串/空值给 None（前端显示「—」）；
        - 同类同秒并列时按 `id` 倒序兜底，不依赖行序。
        """
        limit = max(1, min(int(recent), 100))
        kinds: list[dict[str, Any]] = []
        for r in self._conn.execute(
            "SELECT kind, count(*) AS runs,"
            " sum(CASE WHEN finished_at IS NULL THEN 1 ELSE 0 END) AS unfinished,"
            " max(started_at) AS last_at"
            " FROM runs GROUP BY kind ORDER BY last_at DESC"
        ).fetchall():
            last = self._conn.execute(
                "SELECT id, kind, started_at, finished_at, stats FROM runs"
                " WHERE kind=? ORDER BY started_at DESC, id DESC LIMIT 1",
                (r["kind"],),
            ).fetchone()
            kinds.append({"kind": r["kind"], "runs": int(r["runs"]),
                          "unfinished": int(r["unfinished"] or 0),
                          "last": self._run_row(last) if last is not None else None})
        rows = self._conn.execute(
            "SELECT id, kind, started_at, finished_at, stats FROM runs"
            " ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return {"kinds": kinds, "recent": [self._run_row(x) for x in rows],
                "unfinished_total": sum(k["unfinished"] for k in kinds)}

