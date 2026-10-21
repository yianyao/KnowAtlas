-- KnowAtlas 迁移 004：回归测试集（0.2.0 第五十一批，Phase 0.5 回归集 v0）
-- 权威契约：docs/design/知识索引工具-TODO.md Phase 0.5「回归测试集 v0」；
-- 改动必须先跑 test_canary
-- 迁移纪律：只进不前——本文件落库后禁止修改，新表新列一律新增 005_*.sql

-- regress_cases：人工确认的「条目 → 期望分类路径」对照集。
-- 用途：ktest regress 重跑自动分类链路（L1/L2 规则层，零 LLM 费用）对比
-- 期望，守住分类质量基线；同时作为 LLM few-shot 底稿（Phase 4）。
-- entry_id 主键 = 一条条目一个确认（改主意覆盖旧确认）；
-- expected_path 存完整分类路径（人对分类的自然表达，不存 id——分类重建
-- 后 id 漂移、路径不漂）；source 标确认来源（manual=页面点确认 /
-- log_seed=历史 recategorize 回填）。
CREATE TABLE regress_cases (
    entry_id     TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    expected_path TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT 'manual',
    confirmed_at TEXT NOT NULL
);
CREATE INDEX idx_regress_source ON regress_cases(source);
