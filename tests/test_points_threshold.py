"""抽点阈值参数化测试（工单 2026-10-27 §2.3：`[points]` 键生效）。

两处阈值必须同源：
- `points.max_per_chunk` → 语义任务 `point_extract` 的单条点数上限（prompt + 截断）；
- `points.chunk_chars` → 管道分块目标字数（超过才切块）。
"""

from __future__ import annotations

import json

from knowatlas.models import Entry, FetchResult
from knowatlas.pipeline.points import run_points_extract
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.tasks import point_extract

_BODY = ("SQLite 慢查询排查：先执行 EXPLAIN QUERY PLAN 看执行计划，定位全表扫描后，"
         "再用 ANALYZE 补统计信息。这样能判断是缺索引还是统计信息过期。\n\n") * 8


class FakeLlm:
    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls: list[str] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append(system + "\n" + user)
        idx = len(self.calls) - 1
        if idx >= len(self.replies):
            raise AssertionError(f"多余调用 #{idx + 1}")
        return self.replies[idx]

    model_name = "fake-model"


def _reply(n: int, *, judge: str = "split") -> str:
    points = [{"text": f"SQLite 排查知识第 {i} 条：先看执行计划再补统计信息，避免全表扫描。",
               "summary": f"第 {i} 条", "quote": "先执行 EXPLAIN QUERY PLAN 看执行计划"}
              for i in range(1, n + 1)]
    return json.dumps({"judge": judge, "reason": "多主题清单",
                       "summary": "排查清单", "points": points}, ensure_ascii=False)


def test_point_extract_caps_points_and_tunes_prompt(dl):
    llm = FakeLlm([_reply(5)])
    res = point_extract.run({"entry_id": "e1", "title": "t", "source_type": "manual",
                             "body": _BODY, "max_points": 3},
                            TaskContext(run_id="r", llm=llm))
    assert len(res["points"]) == 3
    assert "2-3 个点" in llm.calls[0]
    assert "2-8 个点" not in llm.calls[0]


def test_point_extract_default_keeps_old_cap(dl):
    llm = FakeLlm([_reply(9)])
    res = point_extract.run({"entry_id": "e1", "title": "t", "source_type": "manual",
                             "body": _BODY},
                            TaskContext(run_id="r", llm=llm))
    assert len(res["points"]) == 8
    assert "2-8 个点" in llm.calls[0]


def _long_entry(dl, key: str, body: str) -> str:
    """长正文条目：inline 只放截断摘要，全文进 content_store（与真实链路同构）。"""
    dl.put_content(FetchResult(text=body, content_hash=f"h-{key}",
                               fetcher="test", fetched_at="2026-10-27T23:00:00+08:00"))
    return dl.upsert_entries([Entry.build(
        source_type="manual", source_key=f"th:{key}", title=f"长文{key}",
        locator=f"https://e.example/th/{key}", inline_content=body[:200],
        content_hash=f"h-{key}", meta={})]).ids[0]


def test_pipeline_reads_points_chunk_chars(cfg, dl):
    cfg.raw["points"] = {"chunk_chars": 1000, "chunk_total_max": 60000,
                         "max_per_chunk": 6}
    body = "\n\n".join(
        f"第 {i} 节：SQLite 慢查询排查步骤 {i}——先执行 EXPLAIN QUERY PLAN 看执行计划，"
        f"定位全表扫描后再用 ANALYZE 补统计信息，并用 {i} 号样例验证。" for i in range(1, 26))
    eid = _long_entry(dl, "1", body)
    llm = FakeLlm([_reply(1, judge="integral")] * 4)
    stats = run_points_extract(cfg, dl, limit=1, llm=llm, entry_ids=[eid])
    assert stats["chunked"] == 1
    assert stats["chunks_total"] == len(llm.calls) >= 2
    assert stats["points_created"] >= 1


def test_chunk_total_max_routes_to_kpe_marker(cfg, dl):
    # 超过 points.chunk_total_max 的正文不打点，落 meta.points_pending_kpe（kauto 会接走）
    cfg.raw["points"] = {"chunk_chars": 1000, "chunk_total_max": 7000,
                         "max_per_chunk": 6}
    eid = _long_entry(dl, "2", "长" * 8000)
    stats = run_points_extract(cfg, dl, limit=1, llm=FakeLlm([_reply(1)]),
                               entry_ids=[eid])
    assert stats["pending_kpe"] == 1
    assert dl.get_entry(eid).meta["points_pending_kpe"]["chars"] == 8000