-- KnowAtlas 迁移 006：条目向量索引（0.2.0 第五十六批，M4 本地 embedding）
-- 权威契约：docs/design/知识索引工具-完整方案.md §1（本地向量可选依赖）/ §8（hybrid）
--   / 设计方案 §6.2（embedding 聚类）；改动必须先写变更工单并跑 test_canary
-- 迁移纪律：只进不前——本文件落库后禁止修改，新表新列一律新增 007_*.sql

-- entry_vectors：条目正文向量（float32 little-endian BLOB，L2 归一化 → 余弦=点积）。
-- entry_id PK（一条目一向量，重算覆盖）；dim 记维度防模型换型后误算；
-- model 记来源模型标识（st:BAAI/bge-m3 / 测试 fake 等），换模型按 model 过滤/重建。
-- 向量是正文的压缩表示：原始正文永在 content_store，本表可随时重建（ksync --embed-force）。
CREATE TABLE entry_vectors (
    entry_id   TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    dim        INTEGER NOT NULL,
    vector     BLOB NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_vectors_model ON entry_vectors(model);
