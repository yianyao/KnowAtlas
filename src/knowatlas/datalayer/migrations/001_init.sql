-- KnowAtlas 数据层初始 DDL（完整方案 §3.4 定稿，user_version 由 db.py 置 1）
-- 权威契约：docs/design/知识索引工具-完整方案.md §3.4；改动必须先写变更工单并跑 test_canary

CREATE TABLE entries (
    id                TEXT PRIMARY KEY,
    source_type       TEXT NOT NULL,
    title             TEXT NOT NULL,
    locator           TEXT NOT NULL,          -- 主 locator；其余见 entry_locators
    locator_canonical TEXT,                   -- https 主 locator 规范化形式；kadd 判重走此索引
    native_path       TEXT,
    inline_content    TEXT,
    content_hash      TEXT,
    meta              TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT,
    exported_at       TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX idx_entries_source   ON entries(source_type);
CREATE INDEX idx_entries_status   ON entries(status);
CREATE INDEX idx_entries_exported ON entries(exported_at);
CREATE INDEX idx_entries_hash     ON entries(content_hash);
CREATE INDEX idx_entries_loccanon ON entries(locator_canonical);

CREATE TABLE entry_locators (            -- 一条知识的多个定位（跨源合并的落点）
    entry_id   TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    locator    TEXT NOT NULL,
    scheme     TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    UNIQUE (entry_id, locator)
);
CREATE INDEX idx_entryloc_locator ON entry_locators(locator);
CREATE INDEX idx_entryloc_scheme  ON entry_locators(scheme);

CREATE TABLE categories (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    note       TEXT,
    origin     TEXT NOT NULL,            -- prior / rule / embedding / llm / manual
    created_at TEXT NOT NULL
);
-- path 不落库：由 category_parents + 递归 CTE 派生（多父分类有多条路径）。
-- 存 path 会在每次 move 时级联重写整棵子树，是持续的债（完整方案 §3.4/§3.5）。

CREATE TABLE category_parents (           -- DAG：一个分类可有多个父分类
    category_id TEXT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    parent_id   TEXT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (category_id, parent_id)
);
CREATE INDEX idx_catparents_parent ON category_parents(parent_id);

CREATE TABLE entry_categories (           -- 条目-分类多对多
    entry_id    TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    category_id TEXT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    confidence  REAL NOT NULL DEFAULT 1.0,
    origin      TEXT NOT NULL,
    task_run_id TEXT,
    PRIMARY KEY (entry_id, category_id)
);
CREATE INDEX idx_entrycats_category ON entry_categories(category_id);
CREATE INDEX idx_entrycats_origin   ON entry_categories(origin);

CREATE TABLE content_store (              -- 大正文缓存，同一内容只存一份
    content_hash TEXT PRIMARY KEY,
    text         TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    fetcher      TEXT NOT NULL
);
CREATE INDEX idx_content_fetched ON content_store(fetched_at);

CREATE TABLE task_log (                   -- 审计与增量处理基础
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    task_name TEXT NOT NULL,
    action    TEXT NOT NULL,              -- classify / retag / merge / move / archive / import
    target    TEXT NOT NULL,
    detail    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_tasklog_at     ON task_log(at);
CREATE INDEX idx_tasklog_target ON task_log(target);

CREATE TABLE runs (                       -- 每次同步/任务运行的记录（可回溯、可重放）
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,            -- sync_full / sync_incremental / kadd / task:<name>
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    stats       TEXT NOT NULL DEFAULT '{}'
);

CREATE VIRTUAL TABLE entries_fts USING fts5(
    title, native_path, inline_content,
    content = 'entries',
    tokenize = 'trigram'
);

CREATE VIRTUAL TABLE content_fts USING fts5(   -- 大正文索引（H2：正文原先无索引覆盖）
    content_hash UNINDEXED,
    text,
    tokenize = 'trigram'
);

-- 外部内容表必须配触发器保持同步
CREATE TRIGGER entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, title, native_path, inline_content)
    VALUES (new.rowid, new.title, new.native_path, new.inline_content);
END;
CREATE TRIGGER entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, native_path, inline_content)
    VALUES ('delete', old.rowid, old.title, old.native_path, old.inline_content);
END;
CREATE TRIGGER entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, native_path, inline_content)
    VALUES ('delete', old.rowid, old.title, old.native_path, old.inline_content);
    INSERT INTO entries_fts(rowid, title, native_path, inline_content)
    VALUES (new.rowid, new.title, new.native_path, new.inline_content);
END;
