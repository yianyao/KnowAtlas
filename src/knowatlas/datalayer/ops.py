"""运维域：任务日志、运行记录（runs）、回归测试集（regress）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ._common import _meta_json, _now


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

