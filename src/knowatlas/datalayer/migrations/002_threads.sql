-- KnowAtlas 迁移 002：Thread 串联工作区（主题工作区，完整方案 §9.4，0.2.0 第三十二批）
-- 权威契约：docs/design/知识索引工具-完整方案.md §9.4；改动必须先写变更工单并跑 test_canary
-- 迁移纪律：只进不前——本文件落库后禁止修改，新表新列一律新增 003_*.sql

-- threads：线索（串联主题工作区）——可命名、保存、复用的有序条目组；
-- 反复走的探索路径也可一键固化为 Thread（操作日志天然可复用）。
-- thread_type：curated=用户串联线索（本批 UI/CLI 建）；source=源同步自动还原的
-- 原始会话线程（邮件/AI 会话，Phase 2/3 适配器落 conv_messages 时使用）。
CREATE TABLE threads (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    note        TEXT,
    thread_type TEXT NOT NULL DEFAULT 'curated',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX idx_threads_type ON threads(thread_type);

-- thread_items：线索内条目与顺序。
-- relation_type 开放枚举：首现定义 seq（顺承）/ because（因果）/ prereq（前置）/
-- contrast（对比）；新增取值走 CHANGELOG 工单，不建查找表（YAGNI）。
CREATE TABLE thread_items (
    id            TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    entry_id      TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'seq',
    note          TEXT
);
CREATE INDEX idx_threaditems_thread ON thread_items(thread_id, position);
CREATE INDEX idx_threaditems_entry  ON thread_items(entry_id);
