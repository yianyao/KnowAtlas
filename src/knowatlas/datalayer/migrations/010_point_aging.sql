-- KnowAtlas 迁移 010：知识点级老化（批次 93，裁决 #14「只老化确实过时的部分点」）
-- 权威契约：docs/design/知识索引工具-知识集与知识生命周期方案.md §9 批次 93
-- 迁移纪律：只进不前——本文件落库后禁止修改，新表新列一律新增 011_*.sql

-- 点级老化三列（与条目级 freshness_flag/aging_verdict 同语义，下沉到点）：
--   aging_flag: ''=未判 / stale=确证过时（退出消费面，溯源条目保留）/ ok=复核仍有效（免疫复扫）
--   aging_reason: L2 判定理由（可核查依据；防幻觉闸门降级 keep 时写降级说明）
--   aging_checked_at: 复核游标（幂等重跑；keep=判不了留观不写 flag 只写游标）
-- 整篇全过时 → 条目级通道（§5.1-4 三级既有出口）不变；点级只标记永不物理删除
-- （点 text 是抽取产物，原文永在 entries/content_store）。
ALTER TABLE points ADD COLUMN aging_flag TEXT NOT NULL DEFAULT '';
ALTER TABLE points ADD COLUMN aging_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE points ADD COLUMN aging_checked_at TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_points_aging ON points(aging_flag) WHERE aging_flag != '';
