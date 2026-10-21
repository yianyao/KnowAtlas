-- KnowAtlas 迁移 007：知识点层（0.2.0 第六十二批，Phase 7 批次 61a）
-- 权威契约：docs/design/知识索引工具-知识集与知识生命周期方案.md §7.1
--   （点层独立表，块/簇/集查询期聚合）/ SOP §7.7 总纪律第 2 条（形态判定先行、
--   切后规范化 hash 去重、一点多溯源）；改动必须先写变更工单并跑 test_canary
-- 迁移纪律：只进不前——本文件落库后禁止修改，schema 变更一律新增 008_*.sql

-- points：知识点（抽取产物，可随时重抽重建）。原文条目永不动、不复制入库正文
-- （点 text 是抽取产物，原文在 entries/content_store）；content_hash 为规范化
-- 去重键（point_hash，见 pipeline/points.py），同观点重复文档合并为一点多溯源。
-- points 不进 entries_fts/content_fts 触发器体系（方案 §7.1），点检索独立演进。
CREATE TABLE points (
    id           TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE,
    text         TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    source_type  TEXT NOT NULL,
    judge        TEXT NOT NULL,              -- integral=整条即点 / split=集合型切出
    created_at   TEXT NOT NULL,
    meta         TEXT NOT NULL DEFAULT '{}'  -- 判定理由 judge_reason 等（抽检口径）
);
CREATE INDEX idx_points_judge ON points(judge);
CREATE INDEX idx_points_source ON points(source_type);

-- point_sources：点 ← 条目 溯源指针（一点多源：同观点重复文档一植多指针）。
-- 溯源数=可信度信号、最早 created_at=知识形成时间（方案 §7.1）；
-- char_offset=点正文在条目正文中的字符偏移（integral 整条即点或 LLM 改写定位
-- 不中时为 NULL）；anchor=定位锚点（点正文前 80 字符摘句）。
-- 条目物理删除时指针级联消失（FK CASCADE），点本体保留。
CREATE TABLE point_sources (
    point_id    TEXT NOT NULL REFERENCES points(id) ON DELETE CASCADE,
    entry_id    TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    char_offset INTEGER,
    anchor      TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (point_id, entry_id)
);
CREATE INDEX idx_point_sources_entry ON point_sources(entry_id);
