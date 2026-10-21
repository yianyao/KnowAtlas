"""知识点抽取测试（0.2.0 第六十二批，Phase 7 批次 61a，方案 §7.1）。

覆盖：规范化 hash 去重（空白/大小写/零宽不敏感）、迁移 007 两表、
一点多溯源（同 hash 跨条目合并）、形态判定 integral/split、判定理由落
meta.judge_reason、流水线幂等重跑、LLM 未启用/故障降级、dry-run 不写库。
会红的探针对应 CHANGELOG 第六十二批「复检探针」清单。
"""

from __future__ import annotations

import uuid

from knowatlas.models import Entry
from knowatlas.pipeline.points import (
    normalize_point_text, point_hash, run_points_extract,
)
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import point_extract


# ---- 测试替身 ----

class FakeLlm:
    """按调用序返回预设响应；broken=True 抛 LlmError。"""

    def __init__(self, replies: list[str] | None = None, broken: bool = False):
        self.replies = replies or []
        self.broken = broken
        self.calls: list[str] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append(user)
        if self.broken:
            raise LlmError("模拟故障")
        idx = len(self.calls) - 1
        if idx >= len(self.replies):
            raise LlmError(f"多余调用 #{idx + 1}")
        return self.replies[idx]


_INTEGRAL_REPLY = (
    '```json\n{"judge":"integral","reason":"单主题方案文档，整体不可拆",'
    '"summary":"一套 SQLite 慢查询排查方案",'
    '"points":[{"text":"SQLite 慢查询排查：先 EXPLAIN QUERY PLAN 看计划，'
    '再补统计信息 ANALYZE。","summary":"SQLite 慢查询排查两步"}]}\n```'
)
_SPLIT_REPLY = (
    '{"judge":"split","reason":"问答合集，两条独立知识点",'
    '"summary":"FTS5 与 WAL 两问",'
    '"points":[{"text":"FTS5 中文检索用 trigram 分词。","summary":"FTS5 分词选型"},'
    '{"text":"WAL 模式提升并发读：PRAGMA journal_mode=WAL。","summary":"WAL 开启方式"}]}'
)


def _seed_entries(dl, n: int = 1, *, body: str = "FTS5 中文检索用 trigram 分词。" * 3,
                  source_type: str = "manual") -> list[Entry]:
    # source_key 带随机段：entry_id 确定性生成，跨调用同 key 会撞成同一条目
    batch = uuid.uuid4().hex[:6]
    es = [Entry.build(source_type=source_type, source_key=f"pt:{batch}:{i}",
                      title=f"测试条目 {batch}:{i}",
                      locator=f"https://example.com/pt/{batch}/{i}",
                      inline_content=body,
                      meta={"source_type": source_type})
          for i in range(n)]
    dl.upsert_entries(es)
    return es


# ---- 规范化与去重键 ----

def test_point_hash_ignores_whitespace_case_zerowidth():
    """空白折叠 + casefold + 零宽剔除 → 同观点不同排版同 hash。"""
    a = "Hello　World：FTS5 trigram"
    b = "hello\u200b world：fts5  trigram"          # 零宽 + 连续空白
    c = "  HELLO\n\tWorld：FTS5\tTRIGRAM  \n"       # 大小写 + 制表换行
    assert point_hash(a) == point_hash(b) == point_hash(c)
    assert point_hash("完全不同的另一条观点") != point_hash(a)


def test_normalize_point_text_keeps_punctuation():
    """标点不归一（宁漏勿误：去重键错了会错误合并不同观点）。"""
    assert normalize_point_text("版本 1.2 发布") != normalize_point_text("版本 12 发布")


# ---- 数据层：迁移 007 / 一点多溯源 ----

def test_put_point_creates_and_lists(dl):
    es = _seed_entries(dl, 1)
    ph = point_hash("SQLite 慢查询排查两步。")
    status = dl.put_point(
        {"content_hash": ph, "text": "SQLite 慢查询排查两步。", "summary": "排查",
         "source_type": "manual", "judge": "integral",
         "meta": {"judge_reason": "单主题"}},
        {"entry_id": es[0].id, "char_offset": 0, "anchor": "SQLite"})
    assert status == "created"
    assert dl.count_points() == 1
    pts = dl.list_points()
    assert pts[0]["judge"] == "integral"
    assert pts[0]["source_count"] == 1
    assert pts[0]["meta"]["judge_reason"] == "单主题"


def test_put_point_same_hash_merges_sources(dl):
    """同 hash 不同条目 → 一点多溯源（溯源数=可信度信号）；同条目重复补指针幂等。"""
    es = _seed_entries(dl, 2)
    ph = point_hash("同观点重复文档。")
    point = {"content_hash": ph, "text": "同观点重复文档。", "summary": "",
             "source_type": "manual", "judge": "split", "meta": {}}
    assert dl.put_point(point, {"entry_id": es[0].id, "char_offset": 0,
                                "anchor": "同观点"}) == "created"
    assert dl.put_point(point, {"entry_id": es[1].id, "char_offset": None,
                                "anchor": "同观点"}) == "linked"
    assert dl.count_points() == 1                    # 合并为一点
    assert dl.list_points()[0]["source_count"] == 2  # 两处溯源
    assert dl.put_point(point, {"entry_id": es[1].id, "char_offset": None,
                                "anchor": "同观点"}) == "linked"  # 重放不重计
    assert dl.list_points()[0]["source_count"] == 2
    srcs = dl.point_sources_of(ph[:16])
    assert {s["entry_id"] for s in srcs} == {es[0].id, es[1].id}
    assert srcs[0]["title"].startswith("测试条目")    # JOIN 条目供抽检


def test_point_source_entry_ids_is_cursor(dl):
    es = _seed_entries(dl, 2)
    ph = point_hash("游标验证。")
    dl.put_point({"content_hash": ph, "text": "游标验证。", "summary": "",
                  "source_type": "manual", "judge": "split", "meta": {}},
                 {"entry_id": es[0].id, "char_offset": None, "anchor": ""})
    assert dl.point_source_entry_ids() == {es[0].id}


# ---- 任务级：point_extract ----

def test_point_extract_degrades_without_llm_and_body():
    res = point_extract.run({"body": "x"}, TaskContext(run_id="r1"))
    assert res["llm_used"] is False and res["points"] == []
    res2 = point_extract.run({"body": ""}, TaskContext(run_id="r1", llm=FakeLlm()))
    assert res2["llm_used"] is False


def test_point_extract_integral_wraps_single_point():
    """integral 归一为单元素 points；判定理由/摘要透传。"""
    llm = FakeLlm([_INTEGRAL_REPLY])
    res = point_extract.run({"source_type": "emmx", "title": "方案", "body": "正文"
                             * 30}, TaskContext(run_id="r1", llm=llm))
    assert res["llm_used"] is True and res["judge"] == "integral"
    assert len(res["points"]) == 1
    assert "SQLite" in res["points"][0]["text"]
    assert res["reason"] == "单主题方案文档，整体不可拆"
    assert "方案" in llm.calls[0]  # 标题进提示词


def test_point_extract_split_and_garbage_and_broken():
    llm = FakeLlm([_SPLIT_REPLY])
    res = point_extract.run({"body": "a" * 60}, TaskContext(run_id="r1", llm=llm))
    assert res["judge"] == "split" and len(res["points"]) == 2

    bad = point_extract.run({"body": "a" * 60},
                            TaskContext(run_id="r1",
                                        llm=FakeLlm(['{"judge":"错误","points":[]}'])))
    assert bad["llm_used"] is False and "非法" in bad["error"]

    res3 = point_extract.run({"body": "a" * 60},
                             TaskContext(run_id="r1", llm=FakeLlm(broken=True)))
    assert res3["llm_used"] is False and res3["error"] == "模拟故障"


# ---- 流水线 ----

def test_pipeline_no_llm_skipped(cfg, dl):
    """LLM 未启用（cfg 无 [llm]）→ skipped，不写库。"""
    _seed_entries(dl, 1)
    stats = run_points_extract(cfg, dl, limit=5)
    assert "skipped" in stats and dl.count_points() == 0


def test_pipeline_integral_and_split_and_reason_meta(cfg, dl):
    """两条目两种形态：integral 1 点 / split 2 点；判定理由落 meta.judge_reason。"""
    es = _seed_entries(dl, 1, body="一套完整的 SQLite 慢查询排查方案，" + "细节 " * 60)
    es2 = _seed_entries(dl, 1, body="问一：FTS5 trigram。问二：WAL 并发。补充说明 " * 8)
    llm = FakeLlm([_INTEGRAL_REPLY, _SPLIT_REPLY])
    stats = run_points_extract(cfg, dl, limit=5, llm=llm)
    assert stats["processed"] == 2 and stats["integral"] == 1 and stats["split"] == 1
    assert stats["points_created"] == 3 and stats["points_total"] == 3
    assert stats["skip_counts"]["already_done"] == 0
    assert dl.count_points() == 3
    by_judge = {p["judge"]: p for p in dl.list_points()}
    assert by_judge["integral"]["meta"]["judge_reason"] == "单主题方案文档，整体不可拆"
    # 溯源指针落对条目（候选按 rowid 序，integral 先跑）
    assert dl.point_source_entry_ids() == {es[0].id, es2[0].id}


def test_pipeline_dedup_across_entries_one_point_multi_source(cfg, dl):
    """同观点重复文档：两候选返回同文点 → 合并一点、两处溯源（一点多溯源探针）。"""
    es = _seed_entries(dl, 2, body="FTS5 中文检索用 trigram 分词。" * 3)
    same = ('{"judge":"split","reason":"单点问答",'
            '"points":[{"text":"FTS5 中文检索用 trigram 分词。","summary":"分词"}]}')
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([same, same]))
    assert stats["points_created"] == 1 and stats["points_linked"] == 1
    assert dl.count_points() == 1
    assert dl.list_points()[0]["source_count"] == 2  # 一点多溯源


def test_pipeline_rerun_is_idempotent(cfg, dl):
    """重跑：已抽条目跳过（游标），零新调用零新点。"""
    _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    llm1 = FakeLlm([_INTEGRAL_REPLY])
    run_points_extract(cfg, dl, limit=5, llm=llm1)
    llm2 = FakeLlm([])  # 任何多余调用都会抛「多余调用」→ 若不跳过必红
    stats2 = run_points_extract(cfg, dl, limit=5, llm=llm2)
    assert stats2["processed"] == 0 and stats2["points_total"] == 1
    assert stats2["skip_counts"]["already_done"] == 1
    assert len(llm2.calls) == 0


def test_pipeline_llm_failure_recorded_not_blocking(cfg, dl):
    """LLM 故障 → errors 记录、不写点、不中断（下次重跑自然补抽）。"""
    _seed_entries(dl, 2, body="一套完整的排查方案，" + "细节 " * 60)
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm(broken=True))
    assert stats["processed"] == 0
    assert len(stats["errors"]) == 2
    assert dl.count_points() == 0


def test_pipeline_dry_run_writes_nothing(cfg, dl):
    _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_INTEGRAL_REPLY]),
                               dry_run=True)
    assert stats["dry_run"] is True and stats["points_created"] == 1
    assert "points_total" not in stats
    assert dl.count_points() == 0                    # 未写库
    assert dl.point_source_entry_ids() == set()      # 游标未推进（重跑可真写）


def test_pipeline_truncates_long_body(cfg, dl):
    """超长正文（走 content_store，绕开 inline_content 4096 上限）截断送 LLM。"""
    from knowatlas.models import FetchResult

    long_text = "长" * 9000
    dl.put_content(FetchResult(text=long_text, content_hash="pt-long-0001",
                               fetcher="test", fetched_at="2026-10-22T00:00:00+08:00"))
    e = Entry.build(source_type="folder", source_key="pt:long:0", title="长文",
                    locator="file:///d/long.md", inline_content=None,
                    content_hash="pt-long-0001", meta={"source_type": "folder"})
    dl.upsert_entries([e])
    llm = FakeLlm([_INTEGRAL_REPLY])
    stats = run_points_extract(cfg, dl, limit=5, llm=llm)
    assert stats["body_truncated"] == 1
    assert len(llm.calls[0]) < 9000                  # 提示词远小于原文
