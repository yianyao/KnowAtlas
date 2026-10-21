"""回归集 v0（0.2.0 第五十一批）：表 CRUD / 三级判级 / 回填 / 确认端点 / CLI。"""

from __future__ import annotations

import json

import pytest

from knowatlas.datalayer.db import DataLayer
from knowatlas.models import Entry
from knowatlas.pipeline.regress import run_regress, seed_from_log


def _entry(source_key: str, title: str, source_type: str = "manual",
           native_path: str | None = None) -> Entry:
    return Entry.build(source_type=source_type, source_key=source_key,
                       title=title, locator=f"https://x.com/{source_key}",
                       locator_canonical=f"https://x.com/{source_key}",
                       native_path=native_path, meta={})


def test_regress_cases_crud(dl: DataLayer):
    """表存在 + upsert 覆盖语义 + 条目删除 CASCADE。"""
    e1 = dl.upsert_entries([_entry("r1", "甲")]).ids[0]
    e2 = dl.upsert_entries([_entry("r2", "乙")]).ids[0]
    assert dl.count_regress_cases() == 0

    dl.add_regress_case(e1, "技术开发/后端", source="manual")
    dl.add_regress_case(e2, "人工智能", source="log_seed")
    assert dl.count_regress_cases() == 2

    # 同条目重复确认 = 覆盖（改主意语义），不产生第二行
    dl.add_regress_case(e1, "技术开发/前端")
    cases = {c["entry_id"]: c for c in dl.list_regress_cases()}
    assert len(cases) == 2
    assert cases[e1]["expected_path"] == "技术开发/前端"
    assert cases[e1]["source"] == "manual"          # 默认 source 回填
    assert cases[e2]["source"] == "log_seed"

    # 删条目 → 案例 CASCADE 消失
    assert dl.count_regress_cases() == 2
    with dl.transaction() as conn:
        conn.execute("DELETE FROM entries WHERE id=?", (e1,))
    assert dl.count_regress_cases() == 1


def test_run_regress_verdicts(dl, cfg):
    """三级判级：exact（先验命中=期望）/ prefix（层级差半级）/ miss（无输出）。"""
    e_exact = dl.upsert_entries([_entry(
        "b1", "PostgreSQL 指南", source_type="bookmark",
        native_path="书签栏/AI/画图")]).ids[0]   # prior: 书签栏/AI → 人工智能
    e_prefix = dl.upsert_entries([_entry(
        "b2", "AI 工具合集", source_type="bookmark",
        native_path="书签栏/AI")]).ids[0]        # prior → 人工智能；期望更深
    e_miss = dl.upsert_entries([_entry(
        "m1", "zzz无规则命中样本q")]).ids[0]     # manual 无 native_path → 无输出
    dl.add_regress_case(e_exact, "人工智能")
    dl.add_regress_case(e_prefix, "人工智能/AI绘图")
    dl.add_regress_case(e_miss, "技术开发/后端")

    report = run_regress(dl, cfg)
    assert report["total"] == 3
    assert report["exact"] == 1 and report["prefix"] == 1 and report["miss"] == 1
    assert report["exact_rate"] == round(1 / 3, 4)   # 报告口径保留 4 位
    by_id = {r["entry_id"]: r for r in report["prefixes"] + report["misses"]}
    assert by_id[e_prefix]["actual"] == "人工智能"       # 方向对、差半级
    assert by_id[e_miss]["actual"] is None
    # 报告落 task_log
    log = [t for t in dl.get_task_log() if t["task_name"] == "ktest"]
    assert log and log[0]["action"] == "regress" and log[0]["detail"]["total"] == 3


def test_run_regress_empty(dl, cfg):
    report = run_regress(dl, cfg)
    assert report["total"] == 0 and report["exact_rate"] is None


def test_seed_from_log(dl: DataLayer):
    """历史 recategorize 回填：同条目取最后一次 new_path；其他 action 不回填。"""
    e1 = dl.upsert_entries([_entry("s1", "一")]).ids[0]
    e2 = dl.upsert_entries([_entry("s2", "二")]).ids[0]
    dl.log_task("2026-10-21T10:00:00+08:00", "web", "recategorize", e1,
                {"old_paths": ["旧"], "new_path": "技术开发"})
    dl.log_task("2026-10-21T11:00:00+08:00", "web", "recategorize", e1,
                {"old_paths": ["技术开发"], "new_path": "技术开发/后端"})
    dl.log_task("2026-10-21T12:00:00+08:00", "web", "reject", e2, {})
    dl.log_task("2026-10-21T13:00:00+08:00", "web", "recategorize", e2,
                {"old_paths": [], "new_path": "  人工智能  "})  # 空白容忍

    stats = seed_from_log(dl, dry_run=True)
    assert stats == {"actions_seen": 3, "entries_seeded": 2, "dry_run": True}
    assert dl.count_regress_cases() == 0                 # dry_run 不写库

    seed_from_log(dl)
    cases = {c["entry_id"]: c for c in dl.list_regress_cases()}
    assert len(cases) == 2
    assert cases[e1]["expected_path"] == "技术开发/后端"  # 最后一次
    assert cases[e2]["expected_path"] == "人工智能"       # strip 生效
    assert all(c["source"] == "log_seed" for c in cases.values())


# ---- Web 确认端点 ----

@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    from fastapi.testclient import TestClient

    from knowatlas.web.app import create_app
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")), "test-token-123")
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def _auth():
    return {"X-KnowAtlas-Token": "test-token-123", "Origin": "http://127.0.0.1:8420"}


def test_confirm_category_endpoint(client, dl: DataLayer):
    """确认归类：manual 挂接优先；重复确认覆盖；无挂接 400。"""
    e = dl.upsert_entries([_entry("c1", "确认样本")]).ids[0]
    r = client.post(f"/api/entries/{e}/confirm-category", json={}, headers=_auth())
    assert r.status_code == 400                            # 未归类先拒
    assert "未挂任何分类" in r.json()["error"]["message"]

    other = dl.create_category("其他分类", [], "manual")
    dev = dl.create_category("技术开发", [], "manual")
    be = dl.create_category("后端", [dev.id], "manual")
    dl.attach_category(e, other.id, 0.5, "rule", "t")
    dl.attach_category(e, be.id, 1.0, "manual", "t")
    r = client.post(f"/api/entries/{e}/confirm-category", json={}, headers=_auth())
    assert r.status_code == 200
    assert r.json()["expected_path"] == "技术开发/后端"     # manual 优先于 rule

    # 无 token 被安全中间件拦
    assert client.post(f"/api/entries/{e}/confirm-category", json={}).status_code == 403


# ---- CLI ----

def test_cmd_ktest_regress(dl, cfg, monkeypatch, capsys):
    """CLI regress：空集 SKIP；有案例出报告；--seed-from-log 回填。"""
    from knowatlas import cli
    import knowatlas.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "load_config", lambda: cfg)
    args = lambda **kw: type("A", (), {"what": "regress", "seed_from_log": False,
                                       "dry_run": False, **kw})()
    assert cli._cmd_ktest(args()) == 0                     # 空集
    assert "SKIP" in capsys.readouterr().out

    e = dl.upsert_entries([_entry("k1", "PostgreSQL 指南", source_type="bookmark",
                                  native_path="书签栏/AI")]).ids[0]
    dl.add_regress_case(e, "人工智能")
    capsys.readouterr()
    assert cli._cmd_ktest(args()) == 0
    out = capsys.readouterr().out
    assert "1 案例" in out and "exact 1" in out

    capsys.readouterr()
    assert cli._cmd_ktest(args(seed_from_log=True)) == 0
    assert "回填统计" in capsys.readouterr().out
