-- KnowAtlas 迁移 009：知识点向量索引（批次 87，点向量语义检索）
-- 权威契约：docs/design/知识索引工具-知识集与知识生命周期方案.md §9 批次 87
-- 迁移纪律：只进不前——本文件落库后禁止修改，新表新列一律新增 010_*.sql

-- point_vectors：点 text 向量（float32 little-endian BLOB，L2 归一化 → 余弦=点积）。
-- 与 entry_vectors（迁移 006）同构：point_id PK（一点一向量，重算覆盖）；
-- dim 记维度防模型换型后误算；model 记来源模型标识，换模型按 model 过滤/重建。
-- 向量是点 text 的压缩表示：原始 text 永在 points，本表可随时重建。
CREATE TABLE point_vectors (
    point_id   TEXT PRIMARY KEY REFERENCES points(id) ON DELETE CASCADE,
    dim        INTEGER NOT NULL,
    vector     BLOB NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_point_vectors_model ON point_vectors(model);
