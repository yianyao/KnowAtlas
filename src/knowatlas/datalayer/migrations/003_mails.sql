-- KnowAtlas 迁移 003：邮件源会话消息表（0.2.0 第三十九批，邮件适配器）
-- 权威契约：docs/design/知识索引工具-完整方案.md §9.4（threads thread_type='source'）；
-- 改动必须先写变更工单并跑 test_canary
-- 迁移纪律：只进不前——本文件落库后禁止修改，新表新列一律新增 004_*.sql

-- conv_messages：邮件消息 ↔ 条目 ↔ 会话线程的映射（源同步自动还原原始会话线程）。
-- id = Message-ID 归一（去 <>；缺失用 sha1(原文)[:16] 兜底）；
-- in_reply_to = 被引用消息的 conv_messages.id（轮次锚点）；
-- subject_norm = Subject 去 Re:/Fwd:/回复:/转发: 等前缀链后的归一化主题（分组键）；
-- thread_id = 所属 source 线程（FK threads；可空=尚未分组；持久化映射保证重复同步幂等）。
CREATE TABLE conv_messages (
    id           TEXT PRIMARY KEY,
    entry_id     TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    in_reply_to  TEXT,
    subject_norm TEXT NOT NULL DEFAULT '',
    sent_at      TEXT,
    thread_id    TEXT REFERENCES threads(id) ON DELETE SET NULL
);
CREATE INDEX idx_convmsg_entry ON conv_messages(entry_id);
CREATE INDEX idx_convmsg_irt   ON conv_messages(in_reply_to);
CREATE INDEX idx_convmsg_thread ON conv_messages(thread_id);
