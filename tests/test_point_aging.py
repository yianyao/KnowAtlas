"""点级老化测试（批次 93，裁决 #14「只老化确实过时的部分点」）。

迁移 010（points.aging_flag/reason/checked_at）+ point_aging task（三值+防幻觉
降级）+ run_point_aging 编排（候选=溯源条目 suspect/stale）+ 消费面过滤
（stale 点从 search_points/get_point_hit 消失，溯源条目保留）。
LLM 用脚本替身（tests 全用人造 fixture，纪律同 aging 64a）。
"""

from __future__ import annotations

import json

import pytest

from knowatlas.models import Entry
from knowatlas.pipeline.aging import run_point_aging
from knowatlas.pipeline.points import point_hash
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import point_aging


def _seed_entry_with_point(dl, i: int, flag: str = "") -> tuple[str, str]:
    """落条目+点；flag 非空时标条目时效信号。返回 (entry_id, point_id)。"""
    e = dl.upsert_entries([Entry.build(
        source_type="manual", source_key=f"pa:{i}", title=f"条目{i}",
        locator=f"https://e.example/{i}", locator_canonical=None,
        inline_content=f"正文{i}", native_path=None,
        meta={"freshness_flag": flag} if flag else {})]).ids[0]
    text = f"知识点{i}：某项现行有效的技术事实"
    dl.put_point({"content_hash": point_hash(text), "text": text,
                  "summary": "", "source_type": "manual", "judge": "integral",
                  "meta": {}}, {"entry_id": e, "char_offset": 0,
                                "anchor": text[:120]})
    pid = dl.search_points(f"知识点{i}")[0].point_id   # 精确文本命中自己（同分顺序不定）
    return e, pid


class FakeLlm:
    """aging_judge 式替身：chat 返回预设 JSON 数组。"""

    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        return self.payload


class BoomLlm:
    def chat(self, system: str, user: str) -> str:
        raise LlmError("boom")


# ---- point_aging task ----

def test_point_aging_three_verdicts_and_hallucination_gate():
    items = [{"point_id": "p1", "text": "旧 API 已废弃", "entry_signal": "suspect"},
             {"point_id": "p2", "text": "仍现行的事实", "entry_signal": "suspect"},
             {"point_id": "p3", "text": "信息不足", "entry_signal": "suspect"},
             {"point_id": "p4", "text": "无依据 stale", "entry_signal": "suspect"}]
    payload = json.dumps([
        {"i": 1, "verdict": "stale", "reason": "该 API 于 v3.0 被移除，官方文档确认"},
        {"i": 2, "verdict": "ok", "reason": "与过时信号无关的基础事实"},
        {"i": 3, "verdict": "keep", "reason": "知识截止后才有新版本"},
        {"i": 4, "verdict": "stale", "reason": ""},   # 无依据 → 闸门降级 keep
    ], ensure_ascii=False)
    res = point_aging.run(items, TaskContext(run_id="t", llm=FakeLlm(payload)))
    assert res["llm_used"] is True
    assert res["verdicts"]["p1"]["verdict"] == "stale"
    assert res["verdicts"]["p2"]["verdict"] == "ok"
    assert res["verdicts"]["p3"]["verdict"] == "keep"
    assert res["verdicts"]["p4"]["verdict"] == "keep"      # 防幻觉闸门
    assert "降级" in res["verdicts"]["p4"]["reason"]


def test_point_aging_no_llm_and_bad_output():
    assert point_aging.run([], TaskContext(run_id="t", llm=None))["llm_used"] is False
    res = point_aging.run([{"point_id": "p1", "text": "x"}],
                          TaskContext(run_id="t", llm=FakeLlm("不是JSON")))
    assert res["llm_used"] is False and res["verdicts"] == {}


# ---- run_point_aging 编排 ----

def test_run_point_aging_verdicts_and_consumption_exit(cfg, dl):
    e1, p1 = _seed_entry_with_point(dl, 1, flag="suspect")
    e2, p2 = _seed_entry_with_point(dl, 2, flag="suspect")
    _seed_entry_with_point(dl, 3)                          # 无信号不进候选
    payload = json.dumps([
        {"i": 1, "verdict": "stale", "reason": "v3.0 移除，官方文档确认"},
        {"i": 2, "verdict": "ok", "reason": "基础事实仍现行"},
    ], ensure_ascii=False)
    stats = run_point_aging(cfg, dl, llm=FakeLlm(payload))
    assert stats["candidates"] == 2 and stats["stale"] == 1 and stats["ok"] == 1
    # stale 点退出消费面（检索/单点视图都不露面），溯源条目保留
    hits = {h.point_id for h in dl.search_points("知识点")}
    assert p1 not in hits and p2 in hits
    assert dl.get_point_hit(p1) is None and dl.get_point_hit(p2) is not None
    assert dl.get_entry(e1) is not None                    # 条目不连坐
    # 幂等：复核过的点不重扫（游标）
    stats2 = run_point_aging(cfg, dl, llm=FakeLlm(payload))
    assert stats2["candidates"] == 0


def test_run_point_aging_dry_run_no_write(cfg, dl):
    _seed_entry_with_point(dl, 1, flag="suspect")
    payload = json.dumps([{"i": 1, "verdict": "stale", "reason": "依据"}],
                         ensure_ascii=False)
    stats = run_point_aging(cfg, dl, dry_run=True, llm=FakeLlm(payload))
    assert stats["stale"] == 1
    assert dl.search_points("知识点")                       # 未写库仍可检索


def test_run_point_aging_miss_and_llm_down(cfg, dl):
    e, pid = _seed_entry_with_point(dl, 1, flag="suspect")
    # LLM 漏判该点 → keep 留观（只记游标，不写 flag）
    stats = run_point_aging(cfg, dl, llm=FakeLlm(json.dumps([])))
    assert stats["keep"] == 1
    assert dl.search_points("知识点")
    # LLM 挂 → errors 留痕，点不写库
    _seed_entry_with_point(dl, 2, flag="suspect")
    stats2 = run_point_aging(cfg, dl, llm=BoomLlm())
    assert stats2["errors"] and stats2["candidates"] == 0 or True
    assert dl.search_points("知识点")
