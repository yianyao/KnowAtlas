"""勘误三级测试（0.2.0 第六十四批，Phase 7 批次 65a，方案 §7.6）。

覆盖：L1 确定性检查（完整 Python 代码块语法验证、节选特征不下结论宁漏勿误、
已移除 API 对照表附官方依据、正文提及不误报、词边界防合法名误报）、L1 扫描
编排（ok 否决跳过/待清理与死链跳过/ksync --errata-scan 挂钩）、L2 errata_check
（error 必附依据否则降级 suspect——探针「疑似错误不到确认级不出裁决队列」、
ok 否决/suspect 留观、非法输出/未启用/故障降级）、L2 编排（三值落 meta、
errata_checked_at 游标幂等、limit 截断、dry-run 不写库）、L3 Web（裁决队列
只出确认级、附注追加原文 diff 为零、误报否决、task_log 留痕）。全部人造
fixture（临时库）+ LLM 替身，零真实 LLM 费用；全量核查等用户裁决（65b，
无人值守硬闸门）。会红的探针对应 CHANGELOG 第六十四批「复检探针」清单。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from knowatlas.models import Entry
from knowatlas.pipeline.errata import run_errata_check, run_errata_scan
from knowatlas.pipeline.sync import run_sync
from knowatlas.semantic import errata
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import errata_check
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


def _entry(dl, key: str, *, title: str = "教程", body: str = "正文内容。",
           meta: dict | None = None, content_hash: str | None = None) -> Entry:
    batch = uuid.uuid4().hex[:6]
    e = Entry.build(source_type="manual", source_key=f"er:{batch}:{key}",
                    title=title, locator=f"https://example.com/er/{batch}/{key}",
                    inline_content=body, content_hash=content_hash, meta=meta or {})
    dl.upsert_entries([e])
    return e


def _err_entry(dl, key: str, *, body: str, title: str = "教程") -> Entry:
    """人造「带确定性错误」的条目（直接预打 errata_flag=error，绕过扫描）。"""
    return _entry(dl, key, title=title, body=body,
                  meta={"errata_flag": "error", "errata_kind": "syntax",
                        "errata_reason": "完整代码块语法错误（行 1: invalid syntax）"})


# ---- L1：代码块提取与节选特征 ----

def test_extract_python_blocks():
    body = "前文\n```python\nx = 1\n```\n中文\n```bash\nls\n```\n```js\nvar x\n```\n未标语言\n```\nplain\n```\n"
    blocks = errata.extract_python_blocks(body)
    assert blocks == ["x = 1\n"]  # 只取标注 python 的围栏块（未标/bash/js 不收）


def test_excerpt_features_no_verdict():
    assert errata.looks_like_excerpt(">>> x = 1")            # REPL
    assert errata.looks_like_excerpt("    return y")          # 首行缩进（函数体节选）
    assert errata.looks_like_excerpt("a = 1\n...\nb = 2")     # ... 省略占位
    assert not errata.looks_like_excerpt("import os\nos.getcwd()")


def test_syntax_error_confirmed():
    # 完整块真语法错误 → 确定性结论
    findings = errata.check_text("说明\n```python\nx = (1 +\n```\n")
    assert any(f["kind"] == "syntax" for f in findings)
    assert "语法错误" in findings[0]["detail"]
    # 节选特征（REPL）块不下结论：只报第一个完整块的错误
    mixed = errata.check_text("```python\nx = (1 +\n```\n```python\n>>> x = (1 +\n```\n")
    assert len(mixed) == 1


def test_api_removed_hit_with_evidence():
    findings = errata.check_text("```python\nimport distutils\n```\n")
    assert len(findings) == 1 and findings[0]["kind"] == "api"
    assert "PEP 632" in findings[0]["detail"] and "Python 3.12" in findings[0]["detail"]


def test_api_prose_mention_no_false_positive():
    """正文（非代码块）提及已移除模块不报——讲废弃的文章是正常内容。"""
    assert errata.check_text("distutils 已在 Python 3.12 移除，请改用 setuptools。") == []


def test_api_word_boundary_no_false_positive():
    """np.float64/np.float32 合法名不误报；np.float(x) 才命中。"""
    assert errata.check_text("```python\nv = np.float64(1.0)\nw = np.float32(2.0)\n```\n") == []
    hits = errata.check_text("```python\nv = np.float(x)\n```\n")
    assert len(hits) == 1 and "NumPy 1.24" in hits[0]["detail"]


def test_clean_text_no_findings():
    assert errata.check_text("正常正文，无代码块。") == []
    assert errata.check_text("```python\nimport os\nprint(os.getcwd())\n```\n") == []


# ---- L1：扫描编排 ----

def test_scan_flags_confirmed_and_clean_kept(dl):
    bad = _entry(dl, "s1", body="代码\n```python\nx = (1 +\n```\n")
    good = _entry(dl, "s2", body="干净正文，无代码块。")
    stats = run_errata_scan(dl)
    assert stats["error"] == 1
    m = dl.get_entry(bad.id).meta
    assert m["errata_flag"] == "error" and m["errata_kind"] == "syntax"
    assert "语法错误" in m["errata_reason"]
    assert dl.get_entry(good.id).meta.get("errata_flag") is None


def test_scan_skips_ok_notk_dead(dl):
    ok = _entry(dl, "k1", body="代码\n```python\nx = (1 +\n```\n",
                meta={"errata_flag": "ok"})  # 用户否决过 → 不再标记
    nonk = _entry(dl, "k2", body="```python\nx = (1 +\n```",
                  meta={"value_flag": "not_knowledge"})
    dead = _entry(dl, "k3", body="```python\nx = (1 +\n```",
                  meta={"link_status": "dead"})
    stats = run_errata_scan(dl)
    assert stats["error"] == 0 and stats["scanned"] == 0
    assert dl.get_entry(ok.id).meta.get("errata_flag") == "ok"


def test_scan_dry_run_no_writes(dl):
    e = _entry(dl, "dr", body="```python\nimport distutils\n```")
    stats = run_errata_scan(dl, dry_run=True)
    assert stats["error"] == 1 and stats["dry_run"] is True
    assert dl.get_entry(e.id).meta.get("errata_flag") is None  # 未写库


def test_ksync_errata_scan_hook(cfg, dl, registries):
    """ksync --errata-scan 挂钩：L1 扫描在主流程中执行。"""
    _entry(dl, "hk", body="```python\nimport imp\n```")
    locators, semantics = registries
    stats = run_sync(cfg, dl, locators, semantics, errata_scan=True)
    assert stats["errata_scan"]["error"] == 1


# ---- L2：errata_check 任务 ----

def test_task_error_with_evidence():
    llm = FakeLlm(['```json\n[{"i":1,"verdict":"error","reason":"DataFrame.append 已移除",'
                   '"evidence":"pandas 2.0 官方变更说明"}]\n```'])
    res = errata_check.run([{"entry_id": "e1", "title": "t", "body": "…"}],
                           TaskContext(run_id="t", llm=llm))
    assert res["llm_used"] and res["verdicts"]["e1"]["verdict"] == "error"
    assert res["verdicts"]["e1"]["evidence"]


def test_task_error_without_evidence_downgrades_to_suspect():
    """防幻觉闸门：error 无可核查依据 → 降级 suspect（不到确认级不出裁决队列）。"""
    llm = FakeLlm(['[{"i":1,"verdict":"error","reason":"感觉不对","evidence":""}]'])
    res = errata_check.run([{"entry_id": "e1", "title": "t", "body": ""}],
                           TaskContext(run_id="t", llm=llm))
    v = res["verdicts"]["e1"]
    assert v["verdict"] == "suspect" and "降级" in v["reason"]


def test_task_ok_veto_and_suspect_uncertain():
    llm = FakeLlm(['[{"i":1,"verdict":"ok","reason":"现行有效"},'
                   '{"i":2,"verdict":"suspect","reason":"知识截止后才有变更","evidence":""}]'])
    res = errata_check.run([{"entry_id": "e1", "title": "a", "body": ""},
                            {"entry_id": "e2", "title": "b", "body": ""}],
                           TaskContext(run_id="t", llm=llm))
    assert res["verdicts"]["e1"]["verdict"] == "ok"
    assert res["verdicts"]["e2"]["verdict"] == "suspect"


def test_task_garbage_and_no_llm():
    llm = FakeLlm(["这不是 JSON"])
    res = errata_check.run([{"entry_id": "e1", "title": "t", "body": ""}],
                           TaskContext(run_id="t", llm=llm))
    assert not res["llm_used"] and res["error"]
    assert errata_check.run([{"entry_id": "e1", "title": "t", "body": ""}],
                            TaskContext(run_id="t", llm=None))["llm_used"] is False


# ---- L2：流水线编排 ----

def test_pipeline_applies_three_verdicts(dl, cfg):
    es = [_entry(dl, "v1", body="甲"), _entry(dl, "v2", body="乙"),
          _entry(dl, "v3", body="丙")]
    llm = FakeLlm(['[{"i":1,"verdict":"error","reason":"已移除","evidence":"官方文档"},'
                   '{"i":2,"verdict":"ok","reason":"成立"},'
                   '{"i":3,"verdict":"suspect","reason":"证据不足"}]'])
    stats = run_errata_check(cfg, dl, limit=3, llm=llm)
    assert stats["processed"] == 3
    assert (stats["error"], stats["ok"], stats["suspect"]) == (1, 1, 1)
    flags = [dl.get_entry(e.id).meta["errata_flag"] for e in es]
    assert flags == ["error", "ok", "suspect"]
    assert all(dl.get_entry(e.id).meta.get("errata_checked_at") for e in es)
    assert dl.get_entry(es[0].id).meta["errata_evidence"] == "官方文档"


def test_pipeline_idempotent_and_limit(dl, cfg):
    _entry(dl, "i1", body="正文一")
    _entry(dl, "i2", body="正文二")
    _entry(dl, "i3", body="正文三")
    llm = FakeLlm(['[{"i":1,"verdict":"ok","reason":"r"},{"i":2,"verdict":"suspect","reason":"r"}]'])
    stats = run_errata_check(cfg, dl, limit=2, llm=llm)
    assert stats["processed"] == 2 and stats["candidates"] == 2
    assert stats["llm_calls"] == 1 and stats["pool_remaining"] == 1
    # 重跑：已核查条目跳过（errata_checked_at 游标幂等），只剩 1 条候选
    llm2 = FakeLlm(['[{"i":1,"verdict":"suspect","reason":"r"}]'])
    stats2 = run_errata_check(cfg, dl, limit=10, llm=llm2)
    assert stats2["candidates"] == 1 and stats2["processed"] == 1


def test_pipeline_skips_not_knowledge(dl, cfg):
    _entry(dl, "nk", body="正文", meta={"value_flag": "not_knowledge"})
    llm = FakeLlm(replies=[])
    stats = run_errata_check(cfg, dl, limit=10, llm=llm)
    assert stats["candidates"] == 0 and stats["llm_calls"] == 0


def test_pipeline_llm_downgrade_no_writes(dl, cfg):
    e = _entry(dl, "d1", body="正文")
    stats = run_errata_check(cfg, dl, llm=FakeLlm(broken=True))
    assert stats["processed"] == 0 and len(stats["errors"]) == 1
    assert dl.get_entry(e.id).meta.get("errata_flag") is None  # 原样保留


def test_pipeline_dry_run_no_writes(dl, cfg):
    e = _entry(dl, "dr", body="正文")
    run_errata_check(cfg, dl, limit=1, dry_run=True,
                     llm=FakeLlm(['[{"i":1,"verdict":"error","reason":"r","evidence":"官方"}]']))
    m = dl.get_entry(e.id).meta
    assert m.get("errata_flag") is None and "errata_checked_at" not in m


def test_pipeline_no_llm_skipped(dl, cfg):
    stats = run_errata_check(cfg, dl)
    assert stats.get("skipped")  # LLM 未启用 → SKIP（试跑口径）


# ---- L3：Web 端点（裁决队列只出确认级 + 附注层原文不改写） ----

@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_TEST_TOKEN")), "test-token-123")
    locators, semantics = registries
    return TestClient(create_app(cfg, dl, locators, semantics),
                      headers={"Host": "127.0.0.1:8420"})


def _auth():
    return {"X-KnowAtlas-Token": "test-token-123", "Origin": "http://127.0.0.1:8420"}


def test_queue_only_confirmed_not_suspect(client, dl):
    """探针：疑似错误不到确认级不出裁决队列。"""
    confirmed = _err_entry(dl, "q1", body="原文甲")
    suspect = _entry(dl, "q2", body="原文乙",
                     meta={"errata_flag": "suspect", "errata_kind": "llm_fact",
                           "errata_reason": "证据不足"})
    rows = client.get("/api/errata").json()["entries"]
    ids = [r["id"] for r in rows]
    assert confirmed.id in ids and suspect.id not in ids
    row = next(r for r in rows if r["id"] == confirmed.id)
    assert row["kind"] == "syntax" and "语法错误" in row["reason"]


def test_errata_add_appends_note_original_untouched(client, dl):
    """改正=附注层：meta.errata 追加、原文（inline/content_store）diff 为零、
    flag 清除退出队列、task_log 留痕。"""
    e = _err_entry(dl, "a1", body="原始正文，一字不改。")
    r = client.post(f"/api/entries/{e.id}/errata",
                    json={"text": "正确做法是 x = 1", "evidence": "PEP 632"},
                    headers=_auth())
    assert r.status_code == 200
    assert r.json()["errata_count"] == 1
    m = dl.get_entry(e.id).meta
    assert m["errata"][0]["text"] == "正确做法是 x = 1"
    assert m["errata"][0]["evidence"] == "PEP 632" and m["errata"][0]["source"] == "user"
    assert m.get("errata_flag") is None  # 裁决完成退出队列
    assert dl.get_entry(e.id).inline_content == "原始正文，一字不改。"  # 原文 diff 为零
    # 二次附注：数组追加不覆盖（可多条勘误）
    client.post(f"/api/entries/{e.id}/errata", json={"text": "补充：也迁移到 importlib"},
                headers=_auth())
    assert len(dl.get_entry(e.id).meta["errata"]) == 2
    # 详情端点带附注（并显数据源）
    detail = client.get(f"/api/entries/{e.id}").json()
    assert detail["entry"]["meta"]["errata"][0]["text"] == "正确做法是 x = 1"
    # 审计留痕
    with dl.transaction() as conn:
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM task_log WHERE target=?", (e.id,)).fetchall()]
    assert "errata_add" in actions
    # 附注后退出裁决队列
    assert all(r["id"] != e.id for r in client.get("/api/errata").json()["entries"])


def test_errata_add_requires_text(client, dl):
    e = _err_entry(dl, "a2", body="正文")
    r = client.post(f"/api/entries/{e.id}/errata", json={"text": "  "}, headers=_auth())
    assert r.status_code == 400
    assert dl.get_entry(e.id).meta.get("errata_flag") == "error"  # 未动


def test_errata_dismiss_marks_ok(client, dl):
    """误报否决：errata_flag=ok，退出队列，L1 重扫不再标记。"""
    e = _err_entry(dl, "a3", body="```python\nx = (1 +\n```")
    r = client.post(f"/api/entries/{e.id}/errata/dismiss", json={}, headers=_auth())
    assert r.json()["errata_flag"] == "ok"
    assert all(x["id"] != e.id for x in client.get("/api/errata").json()["entries"])
    run_errata_scan(dl)  # L1 重扫不再翻转 ok（freshness 同口径）
    assert dl.get_entry(e.id).meta.get("errata_flag") == "ok"
    with dl.transaction() as conn:
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM task_log WHERE target=?", (e.id,)).fetchall()]
    assert "errata_dismiss" in actions


def test_errata_write_endpoints_require_token(client, dl):
    e = _err_entry(dl, "a4", body="正文")
    for path in (f"/api/entries/{e.id}/errata", f"/api/entries/{e.id}/errata/dismiss"):
        assert client.post(path, json={"text": "x"}).status_code == 403
