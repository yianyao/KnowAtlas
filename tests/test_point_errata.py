"""点级勘误测试（P1，2026-10-25 裁决）。

覆盖：point_errata task（三值 / wrong 无依据降 suspect / 原因码 fact_error·overclaim /
非法值丢弃 / 无 LLM / 故障）、run_point_errata 编排（hard 闸门、种子回放、新点 LLM
增量、幂等零写、dry-run 不写、LLM 不可用整批 skip）、只读队列 API
（GET /api/errata/points：只出 wrong、带理由+依据+溯源、人裁否决后出队）、CLI 参数。
全部人造 fixture + LLM 替身，零真实费用。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from knowatlas.cli import build_parser
from knowatlas.models import Entry
from knowatlas.pipeline.errata_points import run_point_errata
from knowatlas.pipeline.points import point_hash
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import point_errata
from knowatlas.web.app import create_app


# ---- 替身与 fixture ----

class FakeLlm:
    model_name = "fake-model"

    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls = 0
        self.users: list[str] = []

    def chat(self, system: str, user: str) -> str:
        self.users.append(user)
        self.calls += 1
        if self.calls > len(self.replies):
            raise LlmError(f"多余调用 #{self.calls}")
        return self.replies[self.calls - 1]


class BoomLlm:
    def chat(self, system: str, user: str) -> str:
        raise LlmError("模拟故障")


def _point(dl, key: str, *, kind: str | None = "hard",
           meta: dict | None = None, text: str | None = None) -> str:
    text = text or f"知识点{key}：某项技术的客观事实"
    e = dl.upsert_entries([Entry.build(
        source_type="manual", source_key=f"pe:{key}", title=f"条目{key}",
        locator=f"https://e.example/pe/{key}", inline_content=f"正文{key}",
        meta={})]).ids[0]
    m = dict(meta or {})
    if kind:
        m["kind"] = kind
    dl.put_point({"content_hash": point_hash(text), "text": text, "summary": "",
                  "source_type": "manual", "judge": "integral", "meta": m},
                 {"entry_id": e, "char_offset": 0, "anchor": text[:120]})
    return point_hash(text)[:16]


@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_TEST_TOKEN")), "test-token-123")
    locators, semantics = registries
    return TestClient(create_app(cfg, dl, locators, semantics),
                      headers={"Host": "127.0.0.1:8420"})


# ---- point_errata task ----

def test_task_verdicts_reason_code_and_hallucination_gate():
    items = [{"point_id": "p1", "text": "事实错误"},
             {"point_id": "p2", "text": "绝对化表述"},
             {"point_id": "p3", "text": "证据不足"},
             {"point_id": "p4", "text": "成立"},
             {"point_id": "p5", "text": "wrong 无依据"}]
    payload = json.dumps([
        {"i": 1, "verdict": "wrong", "reason": "PPO 裁剪公式写错",
         "evidence": "arXiv:1707.06347 §3.2", "reason_code": "fact_error"},
        {"i": 2, "verdict": "wrong", "reason": "说只能这样",
         "evidence": "官方文档示例给了两种写法 https://example.org/doc",
         "reason_code": "overclaim"},
        {"i": 3, "verdict": "suspect", "reason": "证据不足"},
        {"i": 4, "verdict": "ok", "reason": "与官方文档一致"},
        {"i": 5, "verdict": "wrong", "reason": "说错了", "evidence": ""},
    ], ensure_ascii=False)
    res = point_errata.run(items, TaskContext(run_id="t", llm=FakeLlm([payload])))
    assert res["llm_used"] is True
    assert res["verdicts"]["p1"]["reason_code"] == "fact_error"
    assert res["verdicts"]["p2"]["reason_code"] == "overclaim"
    assert res["verdicts"]["p3"]["verdict"] == "suspect"
    assert res["verdicts"]["p4"]["verdict"] == "ok"
    assert res["verdicts"]["p5"]["verdict"] == "suspect"      # 防幻觉闸门
    assert "降级" in res["verdicts"]["p5"]["reason"]


def test_task_no_llm_error_and_bad_values():
    assert point_errata.run([{"point_id": "p1", "text": "x"}],
                            TaskContext(run_id="t", llm=None))["llm_used"] is False
    res = point_errata.run([{"point_id": "p1", "text": "x"}],
                           TaskContext(run_id="t", llm=BoomLlm()))
    assert res["verdicts"] == {} and "模拟故障" in res["error"]
    bad = json.dumps([{"i": 1, "verdict": "maybe", "reason": "x"},
                      {"i": 99, "verdict": "wrong", "reason": "越界"}],
                     ensure_ascii=False)
    res2 = point_errata.run([{"point_id": "p1", "text": "x"}],
                            TaskContext(run_id="t", llm=FakeLlm([bad])))
    assert res2["verdicts"] == {}


# ---- run_point_errata 编排 ----

def test_seed_replay_and_domain_gate(dl, tmp_path):
    p_wrong = _point(dl, "a")
    p_ok = _point(dl, "b")
    p_op = _point(dl, "c", kind="opinion")     # 观点：永不成候选
    seed = tmp_path / "verify.json"
    seed.write_text(json.dumps({
        p_wrong: {"verdict": "wrong", "reason": "公式错", "evidence": "官方文档"},
        p_ok: {"verdict": "ok", "reason": "成立"},
        p_op: {"verdict": "wrong", "reason": "不应被写入", "evidence": "x"},
    }, ensure_ascii=False), encoding="utf-8")

    stats = run_point_errata(None, dl, seed_path=seed, llm=None)
    assert stats["candidates"] == 2            # opinion 被闸门挡住
    assert stats["imported"] == 2
    assert stats["wrong"] == 1 and stats["ok"] == 1
    assert dl.points_fact_check_counts() == {"ok": 1, "wrong": 1}
    metas = {p["id"]: p["meta"] for p in dl.list_points(50)}
    assert metas[p_wrong]["fact_check"]["stage"] == "seed"
    assert metas[p_wrong]["fact_check"]["model"] == "seed:verify.json"
    assert "fact_check" not in metas[p_op]


def test_llm_increment_only_hard(dl):
    p_hard = _point(dl, "a")
    p_op = _point(dl, "b", kind="opinion")
    payload = json.dumps([{"i": 1, "verdict": "suspect", "reason": "证据不足"}],
                         ensure_ascii=False)
    llm = FakeLlm([payload])
    stats = run_point_errata(None, dl, llm=llm)
    assert stats["candidates"] == 1 and stats["checked"] == 1
    assert stats["suspect"] == 1
    assert "知识点b" not in llm.users[0]        # opinion 文本没送 LLM
    metas = {p["id"]: p["meta"] for p in dl.list_points(50)}
    assert metas[p_hard]["fact_check"]["verdict"] == "suspect"
    assert metas[p_hard]["fact_check"]["model"] == "fake-model"
    assert "fact_check" not in metas[p_op]


def test_idempotent_and_dry_run(dl, tmp_path):
    p1 = _point(dl, "a")
    seed = tmp_path / "v.json"
    seed.write_text(json.dumps({p1: {"verdict": "ok", "reason": "x"}}),
                    encoding="utf-8")
    dry = run_point_errata(None, dl, seed_path=seed, dry_run=True, llm=None)
    assert dry["imported"] == 1
    assert dl.points_fact_check_counts() == {"(none)": 1}     # 未写库
    run_point_errata(None, dl, seed_path=seed, llm=None)
    before = json.dumps([p["meta"] for p in dl.list_points(50)], sort_keys=True)
    stats = run_point_errata(None, dl, seed_path=seed, llm=None)
    after = json.dumps([p["meta"] for p in dl.list_points(50)], sort_keys=True)
    assert stats["candidates"] == 0 and stats["imported"] == 0
    assert before == after


def test_llm_unavailable_skips_without_writes(dl):
    p1 = _point(dl, "a")
    stats = run_point_errata(None, dl, llm=None)
    assert stats["llm_skipped"]
    assert stats["checked"] == 0
    metas = {p["id"]: p["meta"] for p in dl.list_points(50)}
    assert "fact_check" not in metas[p1]


# ---- 队列 API ----

def test_queue_api_only_wrong_with_evidence_and_sources(dl, client):
    p_wrong = _point(dl, "a", text="伪造的 wrong 点：三元运算符优先级最高")
    p_ok = _point(dl, "b", text="正确的 ok 点")
    p_sus = _point(dl, "c", text="可疑的点")
    dl.merge_meta_of_point(p_wrong, {"fact_check": {
        "verdict": "wrong", "reason": "优先级低于加减", "evidence": "Python 官方文档",
        "reason_code": "fact_error", "at": "2026-10-25T23:00:00+08:00",
        "model": "fake", "stage": "seed"}})
    dl.merge_meta_of_point(p_ok, {"fact_check": {
        "verdict": "ok", "reason": "对", "evidence": "", "reason_code": "",
        "at": "2026-10-25T23:00:00+08:00", "model": "fake", "stage": "seed"}})
    dl.merge_meta_of_point(p_sus, {"fact_check": {
        "verdict": "suspect", "reason": "证据不足", "evidence": "", "reason_code": "",
        "at": "2026-10-25T23:00:00+08:00", "model": "fake", "stage": "seed"}})

    body = client.get("/api/errata/points").json()
    assert body["count"] == 1
    item = body["points"][0]
    assert item["id"] == p_wrong
    assert item["reason"] and item["evidence"] and item["reason_code"] == "fact_error"
    assert item["sources"] and item["sources"][0]["entry_id"]
    assert item["sources"][0]["title"]

    # 人裁「误报」→ dismissed 出队（不动其他 fact_check 字段）
    fact = dict(dl.points_wrong_queue(limit=10)[0]["meta"]["fact_check"])
    fact["dismissed"] = True
    dl.merge_meta_of_point(p_wrong, {"fact_check": fact})
    assert client.get("/api/errata/points").json()["count"] == 0


# ---- CLI 参数 ----

def test_cli_kerrata_points_flags():
    ns = build_parser().parse_args(["kerrata", "--points", "--from-json", "v.json"])
    assert ns.points is True and ns.from_json == "v.json"
    assert ns.limit is None
    ns2 = build_parser().parse_args(["kerrata"])
    assert ns2.points is False and ns2.scan is False