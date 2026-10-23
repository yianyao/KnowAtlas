-- KnowAtlas 迁移 008：知识点 FTS 索引（批次 86，2026-10-23）
-- 权威契约：docs/design/知识索引工具-知识集与知识生命周期方案.md §7.1
-- 背景：2026-10-23 用户方向性裁决——「检索出来的应该是具体的知识点，而不是
--   文件标题」「知识碎片不做检索主通道还有啥用」。点升格为检索主体（批次 86），
--   本迁移给 points 建 trigram 全文索引（与 entries_fts 同款 external content
--   模式 + 三触发器同步）。
-- 迁移纪律：只进不前——本文件落库后禁止修改，schema 变更一律新增 009_*.sql

CREATE VIRTUAL TABLE points_fts USING fts5(
    text, summary,
    content = 'points',
    tokenize = 'trigram'
);

CREATE TRIGGER points_ai AFTER INSERT ON points BEGIN
    INSERT INTO points_fts(rowid, text, summary)
    VALUES (new.rowid, new.text, new.summary);
END;
CREATE TRIGGER points_ad AFTER DELETE ON points BEGIN
    INSERT INTO points_fts(points_fts, rowid, text, summary)
    VALUES ('delete', old.rowid, old.text, old.summary);
END;
CREATE TRIGGER points_au AFTER UPDATE ON points BEGIN
    INSERT INTO points_fts(points_fts, rowid, text, summary)
    VALUES ('delete', old.rowid, old.text, old.summary);
    INSERT INTO points_fts(rowid, text, summary)
    VALUES (new.rowid, new.text, new.summary);
END;

-- 存量回填：触发器只管迁移之后的变化，既有点一次性灌入
INSERT INTO points_fts(rowid, text, summary)
    SELECT rowid, text, summary FROM points;
