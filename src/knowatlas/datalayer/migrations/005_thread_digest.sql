-- KnowAtlas 迁移 005：thread_digest 摘要列（0.2.0 第五十五批，LLM 线程语义任务）
-- 权威契约：docs/design/知识索引工具-完整方案.md §9.4（thread_digest，thread 层跑一次）；
-- 改动必须先写变更工单并跑 test_canary
-- 迁移纪律：只进不前——本文件落库后禁止修改，新表新列一律新增 006_*.sql

-- digest = thread_digest 产物（LLM 累积式摘要：问题→关键进展→当前结论/待办，
-- 组装后的纯文本，含节标记行）；可空=尚未生成。摘要是压缩表示，原始层
-- （entries/content_store）永在，摘要可随时重算；每轮「新增了什么」落在
-- entries.meta.delta_summary（不复制正文，本列只存 thread 级压缩）。
ALTER TABLE threads ADD COLUMN digest TEXT;
