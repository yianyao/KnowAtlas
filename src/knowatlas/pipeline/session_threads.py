"""AI 会话线程还原（0.2.0 第五十七批，复用 conv_messages/threads 基建）。

与会话源约定同构：collect_sessions 产出 conv_messages（全部轮次元数据，
msg_key=session_id#序号，父子关系如实为空）；本模块落库 + 每会话建一条
threads(thread_type='source')（🤖 标题），thread_items 挂会话条目。
幂等：conv_messages 按消息 id upsert（不覆盖已有 thread_id）；thread 按名
查重复用；add_thread_item (thread, entry) 去重。

thread_items 是条目级粒度，轮次顺序由 msg_key 序号 + sent_at 承载——
与会话源「平铺无引用头」的产物结构如实一致（探针口径）。
"""

from __future__ import annotations

from typing import Any

from .mail_threads import _now_iso


def rebuild_session_threads(dl: Any, convs: list[dict[str, Any]],
                            run_id: str) -> dict[str, int]:
    """把会话轮次落 conv_messages 并每会话建一条 source 线程。返回统计。"""
    if not convs:
        return {"messages_staged": 0, "threads_built": 0}
    dl.upsert_conv_messages([
        {"id": c["message_id"], "entry_id": c["entry_id"],
         "in_reply_to": None, "subject_norm": c.get("subject_norm", ""),
         "sent_at": c.get("sent_at")}
        for c in convs
    ])
    staged = len(convs)

    by_entry: dict[str, list[dict[str, Any]]] = {}
    for m in dl.list_conv_messages():
        if m["id"] in {c["message_id"] for c in convs} and not m["thread_id"]:
            by_entry.setdefault(m["entry_id"], []).append(m)

    existing = dl.list_threads(thread_type="source", limit=1000)
    by_name = {t["name"]: t["id"] for t in existing}
    threads_built = 0
    for entry_id, msgs in by_entry.items():
        msgs.sort(key=lambda x: (x.get("sent_at") or "9999", x["id"]))
        title = msgs[0].get("subject_norm") or "(无标题会话)"
        name = f"🤖 {title[:60]}"
        thread_id = by_name.get(name)
        if thread_id is None:
            thread = dl.create_thread(
                name, note=f"AI 会话线程（{len(msgs)} 轮）", thread_type="source")
            thread_id = thread.id
            by_name[name] = thread_id
            threads_built += 1
        dl.add_thread_item(thread_id, entry_id, relation_type="seq")
        dl.set_conv_thread([m["id"] for m in msgs], thread_id)
        dl.log_task(_now_iso(), "session_threads", "build", thread_id,
                    {"entry_id": entry_id, "turns": len(msgs), "run_id": run_id})
    return {"messages_staged": staged, "threads_built": threads_built}
