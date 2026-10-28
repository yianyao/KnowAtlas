"""入库即处理测试（工单 2026-10-27《入库即抽点与自动老化》§2.2/2.3）。

覆盖：L0 守门激活/拒绝、按通道抽点（管道）、跳过理由落 meta、失败计数进 dead、
CLI 解析。全部人造数据 + LLM 替身，零网络零真实费用。
"""

from __future__ import annotations

from knowatlas.cli import build_parser
from knowatlas.models import Entry
from knowatlas.pipeline.ingest import _mark_failure, activate_pending, run_ingest_pass
from knowatlas.semantic.llm import LlmError

_BODY = ("SQLite 慢查询排查：先执行 EXPLAIN QUERY PLAN 看执行计划，定位全表扫描后，"
         "再用 ANALYZE 补统计信息。这样能判断是缺索引还是统计信息过期。") * 3


class FakeLlm:
    def __init__(self, replies: list[str] | None = None, broken: bool = False):
        self.replies = replies or []
        self.broken = broken
        self.calls: list[str] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append(system + "\n" + user)
        if self.broken:
            raise LlmError("模拟故障")
        idx = len(self.calls) - 1
        if idx >= len(self.replies):
            raise LlmError(f"多余调用 #{idx + 1}")
        return self.replies[idx]

    model_name = "fake-model"


_REPLY = ('{"summary":"SQLite 慢查询排查",'
          '"points":[{"text":"SQLite 慢查询排查：先 EXPLAIN QUERY PLAN 看执行计划，'
          '再 ANALYZE 补统计信息。","summary":"两步排查",'
          '"quote":"先执行 EXPLAIN QUERY PLAN 看执行计划"}]}')


def _entry(dl, key: str, *, locator: str, body: str | None = None,
           title: str | None = None) -> str:
    e = Entry.build(source_type="manual", source_key=f"ing:{key}",
                    title=title or f"条目{key}", locator=locator,
                    inline_content=body or "", meta={})
    return dl.upsert_entries([e]).ids[0]


def _meta(dl, eid: str) -> dict:
    return dl.get_entry(eid).meta


# ---- L0 守门与激活 ----

def test_activate_pending_rejects_junk_and_activates_rest(cfg, dl):
    junk = _entry(dl, "home", locator="https://example.com/")
    garbled = _entry(dl, "garble", locator="https://g.example/p/1",
                     body="\ufffd" * 200)
    good = _entry(dl, "good", locator="https://blog.example.com/post/1")
    dl.set_status([junk, garbled, good], "pending")

    stats = activate_pending(cfg, dl)
    assert stats["candidates"] == 3
    assert stats["rejected"] == 2 and stats["activated"] == 1
    assert dl.get_entry(junk).status == "rejected"
    assert _meta(dl, junk)["value_flag_reason"] == "portal_homepage"
    assert _meta(dl, garbled)["value_flag_reason"] == "garbled"
    assert dl.get_entry(good).status == "active"
    assert _meta(dl, good)["auto_activated_at"]
    # 审计留痕
    actions = {r["action"] for r in dl.get_task_log(limit=50)}
    assert {"auto_reject", "auto_activate"} <= actions


def test_activate_pending_dry_run_writes_nothing(cfg, dl):
    eid = _entry(dl, "home", locator="https://example.com/")
    dl.set_status([eid], "pending")
    stats = activate_pending(cfg, dl, dry_run=True)
    assert stats["rejected"] == 1
    assert dl.get_entry(eid).status == "pending"
    assert not _meta(dl, eid).get("value_flag")


# ---- 按通道抽点 ----

def test_pass_extracts_points_via_pipeline(cfg, dl):
    eid = _entry(dl, "a", locator="https://blog.example.com/post/1", body=_BODY)
    stats = run_ingest_pass(cfg, dl, llm=FakeLlm([_REPLY]), do_aging=False,
                            activate=False)
    assert stats["pipeline"] == 1
    assert stats["points_created"] >= 1
    assert dl.count_points() >= 1
    assert _meta(dl, eid)["ingest"]["route"] == "pipeline"
    # 幂等：同一条目再跑一轮不会再调用 LLM（已有溯源点）
    again = run_ingest_pass(cfg, dl, llm=FakeLlm([]), do_aging=False,
                            activate=False)
    assert again["pipeline"] == 0 and again["points_created"] == 0


def test_kpe_gets_a_budget_slot(cfg, dl, monkeypatch):
    """预算再紧也要给 KPE 留 1 个名额（2026-10-28 修：抓取后切分导致 kpe 恒为 0）。"""
    import knowatlas.pipeline.kpe_runner as kpe_runner

    calls: list[str] = []

    def fake_kpe(cfg_, dl_, entry, body, **kw):
        calls.append(entry.id)
        return {"status": "ok", "chunks": 3, "points": 2}

    monkeypatch.setattr(kpe_runner, "run_kpe_for_entry", fake_kpe)
    _entry(dl, "p", locator="https://blog.example.com/post/1", body=_BODY)
    book = _entry(dl, "b", locator="file://book.pdf", body="长文" * 10)
    stats = run_ingest_pass(cfg, dl, llm=FakeLlm([]), do_aging=False,
                            activate=False, limit=1)
    assert calls == [book]
    assert stats["kpe"] == 1 and stats["pipeline"] == 0
    assert stats["points_created"] == 2
    ing = _meta(dl, book)["ingest"]
    assert ing["route"] == "kpe" and ing["chunks"] == 3 and ing["points"] == 2


def test_pass_skips_repo_and_video_with_reason(cfg, dl):
    repo = _entry(dl, "repo", locator="https://github.com/u/r", body=_BODY)
    video = _entry(dl, "v", locator="https://www.bilibili.com/video/BV1", body=_BODY)
    stats = run_ingest_pass(cfg, dl, llm=FakeLlm([]), do_aging=False,
                            activate=False)
    assert stats["skipped"] == 2 and stats["pipeline"] == 0
    assert _meta(dl, repo)["ingest"]["reason"] == "repo_page"
    assert _meta(dl, video)["ingest"]["reason"] == "needs_capability"
    assert dl.count_points() == 0


def test_failure_counter_dead_after_retries(cfg, dl):
    eid = _entry(dl, "bad", locator="https://blog.example.com/x", body=_BODY)
    entry = dl.get_entry(eid)
    for _ in range(3):                      # 缺省 max_retries=2 → 第 3 次进 dead
        _mark_failure(dl, entry, "boom", max_retries=cfg.ingest_max_retries,
                      now="2026-10-27T23:00:00+08:00")
    ing = _meta(dl, eid)["ingest"]
    assert ing["failures"] == 3 and ing["dead"] is True
    # dead 条目不再进候选
    stats = run_ingest_pass(cfg, dl, llm=FakeLlm([]), do_aging=False,
                            activate=False)
    assert stats["pipeline"] == 0


def test_pass_llm_failure_records_error(cfg, dl):
    eid = _entry(dl, "err", locator="https://blog.example.com/e", body=_BODY)
    stats = run_ingest_pass(cfg, dl, llm=FakeLlm(broken=True), do_aging=False,
                            activate=False)
    assert stats["errors"]
    assert _meta(dl, eid)["ingest"]["failures"] == 1


# ---- CLI ----

def test_cli_kauto_flags():
    ns = build_parser().parse_args(["kauto"])
    assert ns.dry_run is False and ns.limit is None and ns.activate_only is False
    ns2 = build_parser().parse_args(
        ["kauto", "--dry-run", "--limit", "3", "--activate-only", "--no-aging"])
    assert ns2.dry_run and ns2.limit == 3 and ns2.activate_only and ns2.no_aging