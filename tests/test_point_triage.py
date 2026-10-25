"""点分诊测试（P0，2026-10-25 裁决）：三分诊落库 + 领域闸门。

覆盖：point_triage task（三值/非法值丢弃/越界丢弃/无 LLM/故障）、run_point_triage
编排（dupe 确定性标记、种子 JSON 零 LLM 导入、新点 LLM 增量、limit、幂等、dry-run
不写库、LLM 不可用整批 skip 不写半成品）、领域闸门（is_hard / HARD_SQL /
points_of_kind 只出 hard）。全部人造 fixture + LLM 替身，零真实费用。
"""

from __future__ import annotations

import json

from knowatlas.cli import build_parser
from knowatlas.models import Entry
from knowatlas.pipeline.points import point_hash
from knowatlas.pipeline.triage import HARD_SQL, is_hard, run_point_triage
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import point_triage


# ---- 替身与 fixture ----

class FakeLlm:
    """按调用序返回预设 JSON 数组；记录 system/user 以便断言 prompt 口径。"""

    model_name = "fake-model"

    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        if self.calls > len(self.replies):
            raise LlmError(f"多余调用 #{self.calls}")
        return self.replies[self.calls - 1]


class BoomLlm:
    def chat(self, system: str, user: str) -> str:
        raise LlmError("模拟故障")


def _point(dl, key: str, *, text: str | None = None,
           meta: dict | None = None) -> str:
    """落一条条目 + 一条点，返回 point_id（确定性 = content_hash[:16]）。"""
    text = text or f"知识点{key}：某项技术的客观事实"
    e = dl.upsert_entries([Entry.build(
        source_type="manual", source_key=f"pt:{key}", title=f"条目{key}",
        locator=f"https://e.example/pt/{key}", inline_content=f"正文{key}",
        meta={})]).ids[0]
    dl.put_point({"content_hash": point_hash(text), "text": text, "summary": "",
                  "source_type": "manual", "judge": "integral", "meta": meta or {}},
                 {"entry_id": e, "char_offset": 0, "anchor": text[:120]})
    return point_hash(text)[:16]


def _kinds_of(dl) -> dict:
    return {p["id"]: p["meta"].get("kind")
            for p in dl.list_points(500)}


# ---- point_triage task ----

def test_task_three_kinds_and_invalid_values_dropped():
    items = [{"point_id": "p1", "text": "MCP 协议规定握手阶段"},
             {"point_id": "p2", "text": "我认为 agent 应该先规划"},
             {"point_id": "p3", "text": "某内部系统用了特殊队列实现"},
             {"point_id": "p4", "text": "非法类别"},
             {"point_id": "p5", "text": "越界编号"}]
    payload = json.dumps([
        {"i": 1, "kind": "hard", "why": "协议标准，有客观对错"},
        {"i": 2, "kind": "opinion", "why": "个人主张"},
        {"i": 3, "kind": "unjudgeable", "why": "内部实现细节"},
        {"i": 4, "kind": "maybe", "why": "非法值应丢弃"},
        {"i": 99, "kind": "hard", "why": "越界应丢弃"},
    ], ensure_ascii=False)
    res = point_triage.run(items, TaskContext(run_id="t", llm=FakeLlm([payload])))
    assert res["llm_used"] is True
    assert set(res["kinds"]) == {"p1", "p2", "p3"}
    assert res["kinds"]["p1"]["kind"] == "hard"
    assert res["kinds"]["p2"]["kind"] == "opinion"
    assert res["kinds"]["p3"]["kind"] == "unjudgeable"


def test_task_no_llm_and_failure():
    assert point_triage.run([{"point_id": "p1", "text": "x"}],
                            TaskContext(run_id="t", llm=None))["llm_used"] is False
    res = point_triage.run([{"point_id": "p1", "text": "x"}],
                           TaskContext(run_id="t", llm=BoomLlm()))
    assert res["kinds"] == {} and res["llm_used"] is False
    assert "模拟故障" in res["error"]


# ---- run_point_triage 编排 ----

def test_seed_import_and_dupe_marking(dl, tmp_path):
    p_hard = _point(dl, "a", text="Python 的 GIL 使同一时刻只有一个线程执行字节码")
    p_op = _point(dl, "b", text="我觉得先写文档再写代码更好")
    p_dupe = _point(dl, "c", text="重复的一模一样的一句话",
                    meta={"dupe_of": "deadbeefdeadbeef"})
    seed = tmp_path / "triage.json"
    seed.write_text(json.dumps({
        p_hard: {"kind": "hard", "why": "语言规范"},
        p_op: {"kind": "opinion", "why": "个人主张"},
    }, ensure_ascii=False), encoding="utf-8")

    stats = run_point_triage(None, dl, seed_path=seed, llm=None)
    assert stats["imported"] == 2
    assert stats["dupes_marked"] == 1
    assert stats["triaged"] == 0
    assert stats["llm_skipped"] is None          # 种子全覆盖，不需要 LLM
    assert dl.point_kind_counts() == {"dupe": 1, "hard": 1, "opinion": 1}

    metas = {p["id"]: p["meta"] for p in dl.list_points(500)}
    assert metas[p_hard]["kind_model"] == "seed:triage.json"
    assert metas[p_hard]["kind_why"] == "语言规范"
    assert metas[p_hard]["kind_at"]                  # 时间戳非空
    assert metas[p_dupe]["kind"] == "dupe"
    assert metas[p_dupe]["kind_model"] == "rule:dupe_of"


def test_idempotent_rerun_writes_nothing(dl, tmp_path):
    p1 = _point(dl, "a")
    seed = tmp_path / "s.json"
    seed.write_text(json.dumps({p1: {"kind": "hard", "why": "x"}}), encoding="utf-8")
    run_point_triage(None, dl, seed_path=seed, llm=None)
    before = json.dumps([p["meta"] for p in dl.list_points(50)],
                        ensure_ascii=False, sort_keys=True)
    stats = run_point_triage(None, dl, seed_path=seed, llm=None)
    after = json.dumps([p["meta"] for p in dl.list_points(50)],
                       ensure_ascii=False, sort_keys=True)
    assert stats["candidates"] == 0
    assert stats["imported"] == stats["triaged"] == stats["dupes_marked"] == 0
    assert before == after


def test_llm_increment_and_limit(dl):
    _point(dl, "a")
    _point(dl, "b")
    _point(dl, "c")
    # limit=2 取 created_at+id 序的前两条；按实际顺序构造 payload（不假定插入序即 id 序）
    cands = dl.points_without_kind()
    first, second = cands[0]["id"], cands[1]["id"]
    rest = cands[2]["id"]
    payload = json.dumps([{"i": 1, "kind": "hard", "why": "机制"},
                          {"i": 2, "kind": "opinion", "why": "主张"}],
                         ensure_ascii=False)
    stats = run_point_triage(None, dl, limit=2, llm=FakeLlm([payload]))
    assert stats["triaged"] == 2
    kinds = _kinds_of(dl)
    assert kinds[first] == "hard" and kinds[second] == "opinion"
    assert kinds[rest] is None                  # limit 截断，未处理
    metas = {p["id"]: p["meta"] for p in dl.list_points(50)}
    assert metas[first]["kind_model"] == "fake-model"


def test_llm_unavailable_skips_without_half_writes(dl):
    p1 = _point(dl, "a")
    _point(dl, "b")
    stats = run_point_triage(None, dl, llm=None)   # cfg=None → 不启用 LLM
    assert stats["llm_skipped"]
    assert stats["triaged"] == 0
    assert dl.point_kind_counts() == {"(none)": 2}
    assert _kinds_of(dl)[p1] is None


def test_llm_error_writes_nothing(dl):
    p1 = _point(dl, "a")
    stats = run_point_triage(None, dl, llm=BoomLlm())
    assert stats["errors"]
    assert stats["triaged"] == 0
    assert _kinds_of(dl)[p1] is None


def test_dry_run_writes_nothing(dl, tmp_path):
    p1 = _point(dl, "a")
    p_dupe = _point(dl, "b", meta={"dupe_of": "x" * 16})
    seed = tmp_path / "s.json"
    seed.write_text(json.dumps({p1: {"kind": "hard", "why": "x"}}), encoding="utf-8")
    stats = run_point_triage(None, dl, seed_path=seed, dry_run=True, llm=None)
    assert stats["imported"] == 1 and stats["dupes_marked"] == 1
    assert dl.point_kind_counts() == {"(none)": 2}
    assert _kinds_of(dl)[p1] is None and _kinds_of(dl)[p_dupe] is None


# ---- 领域闸门 ----

def test_domain_gate_only_hard(dl):
    p_hard = _point(dl, "a")
    p_op = _point(dl, "b")
    p_un = _point(dl, "c")
    for pid, kind in ((p_hard, "hard"), (p_op, "opinion"), (p_un, "unjudgeable")):
        dl.merge_meta_of_point(pid, {"kind": kind})
    assert is_hard({"kind": "hard"}) is True
    assert is_hard({"kind": "opinion"}) is False
    assert is_hard({"kind": "unjudgeable"}) is False
    assert is_hard({}) is False and is_hard(None) is False
    assert [p["id"] for p in dl.points_of_kind("hard")] == [p_hard]
    # HARD_SQL 与 is_hard 同口径（SQL 片段供后续 P1/P2 复用）
    row = dl._conn.execute(
        "SELECT COUNT(*) FROM points p WHERE " + HARD_SQL).fetchone()[0]
    assert row == 1


# ---- CLI 参数 ----

def test_cli_triage_flags_parse():
    ns = build_parser().parse_args(["kpoints", "--triage", "--from-json", "x.json"])
    assert ns.triage is True and ns.from_json == "x.json"
    # --limit 未给：抽取默认 10，分诊默认不限（在 handler 里解析）
    assert ns.limit is None
    ns2 = build_parser().parse_args(["kpoints"])
    assert ns2.triage is False