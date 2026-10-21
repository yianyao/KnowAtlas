"""老化三级测试（0.2.0 第六十三批，Phase 7 批次 64a，方案 §7.5）。

覆盖：L2 复核三值结论（stale 升级退出消费面 / ok 否决 / keep 下沉人裁）、
stale 无依据降级 keep（防幻觉闸门）、非法输出/LLM 未启用/故障降级、
aging_checked_at 游标幂等、limit 截断、dry-run 不写库；L3 删除出口
（冷却期满物理删除、未满不动、历史 rejected 不动、共享内容块只减计数、
独占内容块回收、point_sources 级联与点本体保留、task_log 审计留痕、
ksync 顺手执行）；reject/restore 端点 rejected_at 生命周期。全部人造
fixture（临时库）+ LLM 替身，不触碰真实数据——删除出口落库不批量执行
（无人值守硬闸门）。会红的探针对应 CHANGELOG 第六十三批「复检探针」清单。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from knowatlas.datalayer.db import REJECT_COOLING_DAYS
from knowatlas.models import Entry, FetchResult
from knowatlas.pipeline.aging import run_aging_judgment, sweep_rejections
from knowatlas.pipeline.sync import run_sync
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import aging_judge
from knowatlas.web.app import create_app


# ---- 测试替身与 fixture ----

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


def _suspect_entry(dl, key: str, *, title: str = "Python 2 教程",
                   body: str = "教程内容。最后更新于 2021-05-12。",
                   content_hash: str | None = None) -> Entry:
    """人造 suspect 条目（绕过规则扫描，直接打 freshness_flag=suspect 标）。"""
    batch = uuid.uuid4().hex[:6]
    e = Entry.build(source_type="manual", source_key=f"ag:{batch}:{key}",
                    title=title, locator=f"https://example.com/ag/{batch}/{key}",
                    inline_content=body, content_hash=content_hash,
                    meta={"freshness_flag": "suspect", "freshness_reason": "date_old"})
    dl.upsert_entries([e])
    return e


def _reject(dl, entry: Entry, *, days_ago: int | None = 40) -> None:
    """把条目置 rejected（aging 删除出口的输入形态）。"""
    dl.set_status([entry.id], "rejected")
    patch: dict[str, object] = {}
    if days_ago is not None:
        patch["rejected_at"] = (datetime.now(timezone.utc)
                                - timedelta(days=days_ago)).isoformat()
    if patch:
        dl.merge_meta(entry.id, patch)


def _put_content(dl, content_hash: str, text: str) -> None:
    dl.put_content(FetchResult(content_hash=content_hash, text=text,
                               fetched_at="2026-01-01T00:00:00", fetcher="manual"))


def _ref_now() -> datetime:
    return datetime.now(timezone.utc)


# ---- L2：aging_judge 任务 ----

def test_task_stale_upgrade_with_evidence():
    llm = FakeLlm(['```json\n[{"i":1,"verdict":"stale","reason":"Python 2 于 '
                   '2020-01-01 停止维护（PEP 373，官方口径）","suggest":"改用 Python 3"}]\n```'])
    res = aging_judge.run([{"entry_id": "e1", "title": "Python 2 教程",
                            "freshness_reason": "date_old", "body": "…"}],
                          TaskContext(run_id="t", llm=llm))
    assert res["llm_used"] and res["verdicts"]["e1"]["verdict"] == "stale"
    assert "PEP 373" in res["verdicts"]["e1"]["reason"]


def test_task_stale_without_evidence_downgrades_to_keep():
    """防幻觉闸门：stale 无可核查依据 → 自动降级 keep（宁漏勿误）。"""
    llm = FakeLlm(['[{"i":1,"verdict":"stale","reason":"","suggest":""}]'])
    res = aging_judge.run([{"entry_id": "e1", "title": "t", "body": ""}],
                          TaskContext(run_id="t", llm=llm))
    assert res["verdicts"]["e1"]["verdict"] == "keep"
    assert "降级" in res["verdicts"]["e1"]["reason"]


def test_task_ok_veto_and_keep_uncertain():
    llm = FakeLlm(['[{"i":1,"verdict":"ok","reason":"版权年份是页面脚注，内容现行有效"},'
                   '{"i":2,"verdict":"keep","reason":"新版本在知识截止后发布"}]'])
    res = aging_judge.run([{"entry_id": "e1", "title": "a", "body": ""},
                           {"entry_id": "e2", "title": "b", "body": ""}],
                          TaskContext(run_id="t", llm=llm))
    assert res["verdicts"]["e1"]["verdict"] == "ok"
    assert res["verdicts"]["e2"]["verdict"] == "keep"


def test_task_garbage_output_and_no_llm():
    llm = FakeLlm(["这不是 JSON"])
    res = aging_judge.run([{"entry_id": "e1", "title": "t", "body": ""}],
                          TaskContext(run_id="t", llm=llm))
    assert not res["llm_used"] and res["error"]
    assert aging_judge.run([{"entry_id": "e1", "title": "t", "body": ""}],
                           TaskContext(run_id="t", llm=None))["llm_used"] is False


# ---- L2：流水线编排 ----

def test_pipeline_applies_three_verdicts(dl, cfg):
    es = [_suspect_entry(dl, "v1"), _suspect_entry(dl, "v2"), _suspect_entry(dl, "v3")]
    llm = FakeLlm(['[{"i":1,"verdict":"stale","reason":"官方已停止维护"},'
                   '{"i":2,"verdict":"ok","reason":"内容现行有效"},'
                   '{"i":3,"verdict":"keep","reason":"无法确证"}]'])
    stats = run_aging_judgment(cfg, dl, limit=3, llm=llm)
    assert stats["processed"] == 3
    assert (stats["stale"], stats["ok"], stats["keep"]) == (1, 1, 1)
    flags = [dl.get_entry(e.id).meta["freshness_flag"] for e in es]
    assert flags == ["stale", "ok", "suspect"]  # keep 维持 suspect 下沉人裁
    assert all(dl.get_entry(e.id).meta.get("aging_checked_at") for e in es)
    # stale 退出消费面口径由 _consumable 判 meta（list_by_freshness_flag 可见性不变）


def test_pipeline_idempotent_and_limit(dl, cfg):
    _suspect_entry(dl, "i1")
    _suspect_entry(dl, "i2")
    _suspect_entry(dl, "i3")
    # batch 20：limit=2 的两条候选合入单次 LLM 调用
    llm = FakeLlm(['[{"i":1,"verdict":"ok","reason":"r"},{"i":2,"verdict":"keep","reason":"r"}]'])
    stats = run_aging_judgment(cfg, dl, limit=2, llm=llm)
    assert stats["processed"] == 2 and stats["candidates"] == 2
    assert stats["llm_calls"] == 1 and stats["pool_remaining"] == 1
    # 重跑：已复核条目跳过，只剩 1 条候选，零重复判定
    llm2 = FakeLlm(['[{"i":1,"verdict":"keep","reason":"r"}]'])
    stats2 = run_aging_judgment(cfg, dl, limit=10, llm=llm2)
    assert stats2["candidates"] == 1 and stats2["processed"] == 1


def test_pipeline_llm_downgrade_no_writes(dl, cfg):
    e = _suspect_entry(dl, "d1")
    stats = run_aging_judgment(cfg, dl, llm=FakeLlm(broken=True))
    assert stats["processed"] == 0 and len(stats["errors"]) == 1
    assert dl.get_entry(e.id).meta["freshness_flag"] == "suspect"  # 原样保留


def test_pipeline_dry_run_no_writes(dl, cfg):
    e = _suspect_entry(dl, "dr1")
    run_aging_judgment(cfg, dl, limit=1, dry_run=True,
                       llm=FakeLlm(['[{"i":1,"verdict":"stale","reason":"官方停止维护"}]']))
    m = dl.get_entry(e.id).meta
    assert m["freshness_flag"] == "suspect" and "aging_checked_at" not in m


# ---- L3：删除出口 ----

def test_sweep_expired_unique_content_recycled(dl):
    """冷却期满 + 独占正文块：条目物理删除、正文回收、审计留痕、历史日志保留。"""
    e = _suspect_entry(dl, "s1", body="独占正文", content_hash="c" * 40)
    _put_content(dl, e.content_hash, "独占正文")
    dl.log_task("2026-01-01T00:00:00", "kadd", "manual_add", e.id, {})  # 历史审计
    _reject(dl, e, days_ago=40)
    stats = sweep_rejections(dl)
    assert len(stats["swept"]) == 1 and stats["content_recycled"] == 1
    assert dl.get_entry(e.id) is None
    assert dl.get_content(e.content_hash) is None  # 引用归零 → 正文回收
    # 审计链：历史日志保留 + sweep_delete 追加
    with dl.transaction() as conn:
        targets = [r["action"] for r in conn.execute(
            "SELECT action FROM task_log WHERE target=?", (e.id,)).fetchall()]
    assert "manual_add" in targets and "sweep_delete" in targets


def test_sweep_shared_content_only_decrements(dl):
    """多条目共享同一内容块：删其一只减计数，正文保留；删到零才回收。"""
    shared = "d" * 40
    a = _suspect_entry(dl, "h1", body="共享正文块内容", content_hash=shared)
    _suspect_entry(dl, "h2", body="共享正文块内容", content_hash=shared)
    _put_content(dl, shared, "共享正文块内容")
    _reject(dl, a, days_ago=40)
    sweep_rejections(dl)
    assert dl.get_entry(a.id) is None
    assert dl.get_content(shared) == "共享正文块内容"  # h2 还在引用，不回收
    # 删到零 → 回收
    b = next(e for e in dl.list_entries(status="active") if e.content_hash == shared)
    dl.set_status([b.id], "rejected")
    dl.merge_meta(b.id, {"rejected_at": (_ref_now() - timedelta(days=40)).isoformat()})
    stats = sweep_rejections(dl)
    assert stats["content_recycled"] == 1 and dl.get_content(shared) is None


def test_sweep_keeps_cooling_and_legacy(dl):
    """冷却未满不动；无 rejected_at 的历史 rejected 不动（非本机制裁决）。"""
    cooling = _suspect_entry(dl, "c1")
    legacy = _suspect_entry(dl, "c2")
    _reject(dl, cooling, days_ago=5)
    _reject(dl, legacy, days_ago=None)
    stats = sweep_rejections(dl)
    assert stats["swept"] == [] and stats["kept_cooling"] == 1 and stats["kept_legacy"] == 1
    assert dl.get_entry(cooling.id) is not None and dl.get_entry(legacy.id) is not None


def test_sweep_dry_run_reports_without_deleting(dl):
    e = _suspect_entry(dl, "dr")
    _reject(dl, e, days_ago=40)
    stats = sweep_rejections(dl, dry_run=True)
    assert len(stats["swept"]) == 1 and stats["dry_run"] is True
    assert dl.get_entry(e.id) is not None  # 未删除


def test_sweep_cascades_point_sources_keeps_point(dl):
    """point_sources 级联消失（溯源指针跟条目走），点本体保留（可重建溯源）。"""
    e = _suspect_entry(dl, "p1")
    status = dl.put_point(
        {"content_hash": "a" * 40, "text": "一点知识", "summary": "",
         "source_type": "manual", "judge": "split", "meta": {}},
        {"entry_id": e.id, "char_offset": 0, "anchor": "一点知识"})
    assert status == "created"
    _reject(dl, e, days_ago=40)
    sweep_rejections(dl)
    assert dl.get_entry(e.id) is None
    assert dl.count_points() == 1          # 点本体保留
    assert dl.point_sources_of("a" * 16) == []  # 溯源指针级联消失


def test_ksync_runs_sweep(cfg, dl, registries):
    """ksync 顺手执行：冷却期满条目在主流程同步中被物理删除。"""
    e = _suspect_entry(dl, "k1")
    _reject(dl, e, days_ago=40)
    locators, semantics = registries
    stats = run_sync(cfg, dl, locators, semantics, full=True, source="bookmarks")
    assert stats["rejected_sweep"]["swept"]
    assert dl.get_entry(e.id) is None


# ---- L3：Web 端点（人裁入口 + 冷却倒计时） ----

@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_TEST_TOKEN")), "test-token-123")
    locators, semantics = registries
    return TestClient(create_app(cfg, dl, locators, semantics),
                      headers={"Host": "127.0.0.1:8420"})


def _auth():
    return {"X-KnowAtlas-Token": "test-token-123", "Origin": "http://127.0.0.1:8420"}


def test_reject_records_cooling_and_restore_clears(client, dl):
    """人裁废弃：reject 落 rejected_at 起冷却；restore 清起点（反悔窗口语义）。"""
    e = _suspect_entry(dl, "w1")
    r = client.post(f"/api/entries/{e.id}/reject", json={}, headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected" and body["cooling_days"] == REJECT_COOLING_DAYS
    rows = client.get("/api/rejected").json()["entries"]
    row = next(x for x in rows if x["id"] == e.id)
    assert row["rejected_at"] and row["cooling_days_left"] == REJECT_COOLING_DAYS
    r = client.post(f"/api/entries/{e.id}/restore", json={}, headers=_auth())
    assert r.json()["status"] == "active"
    assert dl.get_entry(e.id).meta.get("rejected_at") is None  # 冷却起点已清


def test_rejected_list_marks_legacy_without_cooling(client, dl):
    e = _suspect_entry(dl, "w2")
    dl.set_status([e.id], "rejected")  # 历史形态：无 rejected_at
    row = client.get("/api/rejected").json()["entries"][0]
    assert row["rejected_at"] is None and row["cooling_days_left"] is None
