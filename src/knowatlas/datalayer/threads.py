"""Thread 串联工作区：线程/条目排序、会话消息还原。"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Sequence

from ..errors import ContractError
from ..models import THREAD_TYPES, Thread, ThreadItem
from ._common import _consumable, _now


class _ThreadsMixin:
    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ThreadItem:
        return ThreadItem(
            id=row["id"], thread_id=row["thread_id"], entry_id=row["entry_id"],
            position=row["position"], relation_type=row["relation_type"], note=row["note"],
        )

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
                      updated_at=row["updated_at"], digest=row["digest"],
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
             "digest": r["digest"],
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

    def set_thread_digest(self, thread_id: str, digest: str) -> None:
        """写入 thread_digest 产物（第五十五批；可重复调用=重算覆盖，原始层不受影响）。"""
        text = (digest or "").strip()
        if not text:
            raise ContractError("digest 为空（LLM 关闭或未产出时不应写库）")
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM threads WHERE id=?", (thread_id,)).fetchone()
            if row is None:
                raise ContractError(f"线索不存在：{thread_id}")
            conn.execute(
                "UPDATE threads SET digest=?, updated_at=? WHERE id=?",
                (text, _now(), thread_id),
            )
            self.log_task(_now(), "threads", "digest", thread_id,
                          {"chars": len(text)})

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

