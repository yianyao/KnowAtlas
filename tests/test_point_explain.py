"""大白话释疑测试（批次 90）：point_explain task + /api/points/{id}/explain。

释疑=用户逐点触发的交互动作（LLM 几分钱/次），缓存点 meta.explain 零重复
费用；?refresh=1 强制重释；LLM 未启用 503。LLM 用脚本替身。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from knowatlas.models import Entry
from knowatlas.pipeline.points import point_hash
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import point_explain


class FakeLlm:
    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        return self.payload


class BoomLlm:
    def chat(self, system: str, user: str) -> str:
        raise LlmError("boom")


_GOOD = json.dumps({
    "explanation": "进销存就是管「买进来、卖出去、还剩多少」的一套流程。",
    "examples": "例：进货 10 台手机（采购），卖出 6 台（销售），系统自动记库存剩 4 台。",
}, ensure_ascii=False)


def _seed_point(dl) -> str:
    e = dl.upsert_entries([Entry.build(
        source_type="manual", source_key="pe:1", title="条目",
        locator="https://e.example/1", locator_canonical=None,
        inline_content="正文", native_path=None, meta={})]).ids[0]
    text = "进销存系统以销售单为核心驱动采购补货与库存盘点"
    dl.put_point({"content_hash": point_hash(text), "text": text,
                  "summary": "", "source_type": "manual", "judge": "integral",
                  "meta": {}}, {"entry_id": e, "char_offset": 0,
                                "anchor": text[:120]})
    return dl.search_points("进销存")[0].point_id


# ---- task ----

def test_point_explain_ok_and_empty_text():
    res = point_explain.run({"text": "进销存以销售单为核心"},
                            TaskContext(run_id="t", llm=FakeLlm(_GOOD)))
    assert res["llm_used"] is True
    assert "买进来" in res["explanation"] and res["examples"]
    # 空文本/无 LLM 不调用
    assert point_explain.run({"text": ""},
                             TaskContext(run_id="t", llm=FakeLlm(_GOOD)))["llm_used"] is False
    assert point_explain.run({"text": "x"},
                             TaskContext(run_id="t", llm=None))["llm_used"] is False


def test_point_explain_bad_output_and_error():
    res = point_explain.run({"text": "x"}, TaskContext(run_id="t", llm=FakeLlm("不是JSON")))
    assert res["llm_used"] is False
    res2 = point_explain.run({"text": "x"}, TaskContext(run_id="t", llm=BoomLlm()))
    assert res2["llm_used"] is False and res2.get("error")


# ---- API ----

@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")),
                       "test-token-123")
    from knowatlas.web.app import create_app
    app = create_app(cfg, dl, *registries)
    return TestClient(app, headers={"Host": "127.0.0.1:8420",
                                    "X-KnowAtlas-Token": "test-token-123"})


def test_api_explain_lifecycle(cfg, dl, client, monkeypatch):
    pid = _seed_point(dl)
    calls = {"n": 0}

    class CountLlm(FakeLlm):
        def chat(self, system: str, user: str) -> str:
            calls["n"] += 1
            return _GOOD

    monkeypatch.setattr("knowatlas.semantic.llm.LlmClient.from_config",
                        lambda cfg: CountLlm(_GOOD))
    # 首次释疑：LLM 调用 + 缓存落 meta
    r = client.post(f"/api/points/{pid}/explain", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is False and "买进来" in body["explanation"]
    assert calls["n"] == 1
    row = dl._conn.execute("SELECT meta FROM points WHERE id=?", (pid,)).fetchone()
    assert "explain" in json.loads(row["meta"])
    # 二次释疑：缓存命中零费用
    r2 = client.post(f"/api/points/{pid}/explain", json={})
    assert r2.json()["cached"] is True and calls["n"] == 1
    # refresh=1 强制重释
    r3 = client.post(f"/api/points/{pid}/explain?refresh=1", json={})
    assert r3.json()["cached"] is False and calls["n"] == 2
    # 不存在的点 404
    assert client.post("/api/points/deadbeef/explain", json={}).status_code == 404


def test_api_explain_llm_disabled(cfg, dl, client, monkeypatch):
    pid = _seed_point(dl)
    monkeypatch.setattr("knowatlas.semantic.llm.LlmClient.from_config",
                        lambda cfg: None)
    r = client.post(f"/api/points/{pid}/explain", json={})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "LLM_DISABLED"
