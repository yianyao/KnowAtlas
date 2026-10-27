"""正文库域：按 content_hash 存取正文、孤儿回收、VACUUM INTO 备份。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..models import FetchResult
from ._common import _meta_json, _parse_iso


class _ContentMixin:
    def vacuum_into(self, dest: Path) -> None:
        """SQLite 官方一致性快照（VACUUM INTO）——备份专用（第四十六批）。

        WAL 开启状态下安全：直接拷 .db 文件会丢 -wal 内未 checkpoint 的数据，
        VACUUM INTO 是官方提供的一致性快照机制（含 WAL 内容），不自己拷文件。
        目标文件必须不存在（调用方保证）。
        """
        self._conn.execute("VACUUM INTO ?", (dest.as_posix(),))

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

    # ---- 内容库回收（TODO 8.15，2026-10-26） ----

    def gc_orphan_contents(self, max_age_days: float = 1.0,
                           dry_run: bool = True) -> dict[str, Any]:
        """回收无条目引用的正文块（content_store 孤儿；TODO 8.15）。

        口径：
        - 孤儿 = `content_store` 中不存在任何 `entries.content_hash` 指向的行
          （content_hash 变了 / 换解析通道 / 改清洗规则后留下的旧正文）；
        - 阈值保护 = 只回收 `fetched_at` 早于 `max_age_days` 的行，防同步进行中的
          竞态（刚抓完、条目尚未 upsert 的那一瞬）；`fetched_at` 缺失或不可解析的
          历史行按「最老」处理——正文是**缓存**，条目/点/向量一字不动，删了可重抓；
        - 只动 `content_store` + `content_fts`（正文检索索引同步清）；dry-run 零写入、
          不记 task_log，实跑写一条 `task_log(content_gc)` 审计。

        返回 {candidates, eligible, skipped_recent, deleted, freed_chars, max_age_days}。
        """
        horizon = datetime.now(timezone.utc) - timedelta(days=max(0.0, max_age_days))
        rows = self._conn.execute(
            "SELECT cs.content_hash, cs.fetched_at, LENGTH(cs.text) AS n"
            " FROM content_store cs"
            " WHERE NOT EXISTS (SELECT 1 FROM entries e"
            "                   WHERE e.content_hash=cs.content_hash)"
        ).fetchall()
        eligible: list[str] = []
        freed_chars = 0
        for r in rows:
            ts = _parse_iso(r["fetched_at"])
            if ts is not None and ts > horizon:
                continue                      # 过新：可能是同步进行中的竞态行
            eligible.append(r["content_hash"])
            freed_chars += int(r["n"] or 0)
        deleted = 0
        if eligible and not dry_run:
            at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            with self.transaction() as conn:
                for i in range(0, len(eligible), 400):   # 分批：避开 SQLite 变量上限
                    batch = eligible[i:i + 400]
                    marks = ",".join("?" * len(batch))
                    conn.execute(f"DELETE FROM content_fts WHERE content_hash IN ({marks})",
                                 batch)
                    deleted += conn.execute(
                        f"DELETE FROM content_store WHERE content_hash IN ({marks})",
                        batch).rowcount
                conn.execute(
                    "INSERT INTO task_log (at, task_name, action, target, detail)"
                    " VALUES (?,?,?,?,?)",
                    (at, "content_gc", "gc_orphan", "content_store",
                     _meta_json({"candidates": len(rows), "deleted": deleted,
                                 "freed_chars": freed_chars,
                                 "max_age_days": max_age_days})))
        return {"candidates": len(rows), "eligible": len(eligible),
                "skipped_recent": len(rows) - len(eligible), "deleted": deleted,
                "freed_chars": freed_chars, "max_age_days": max_age_days}

