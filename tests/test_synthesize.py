"""知识梳理合成层测试（批次 69，§7.9）：synthesize task + preview/commit API。

裁决口径：勾选点 → LLM 生成 Markdown → 预览不落库 → 人确认后落
source_type=synthesized 独立条目（回灌+隔离+强制溯源 meta.sources 必非空）。
LLM 用脚本替身；防幻觉闸门（空 sources 400）与幂等（同文重复确认 unchanged）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from knowatlas.models import Entry
from knowatlas.pipeline.points import point_hash
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import synthesize


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


_MD = "# 合成方案\n\n- 进销存以销售单为核心\n- 盘点核对库存"


def _good_llm():
    return FakeLlm(json.dumps({"markdown": _MD}, ensure_ascii=False))


def _seed_point(dl, key: str, text: str) -> str:
    e = dl.upsert_entries([Entry.build(
        source_type="manual", source_key=key, title="来源条目",
        locator="https://e.example/1", locator_canonical=None,
        inline_content="正文", native_path=None, meta={})]).ids[0]
    dl.put_point({"content_hash": point_hash(text), "text": text,
                  "summary": "", "source_type": "manual", "judge": "integral",
                  "meta": {}}, {"entry_id": e, "char_offset": 0,
                                "anchor": text[:120]})
    return dl.search_points(text[:6])[0].point_id


# ---- task ----

def test_synthesize_task_ok_and_guards():
    ctx_llm = TaskContext(run_id="t", llm=_good_llm())
    items = [{"point_id": "p1", "text": "进销存以销售单为核心",
              "summary": "", "source_title": "来源条目"}]
    res = synthesize.run(items, ctx_llm, instruction="按步骤组织")
    assert res["llm_used"] is True and "销售单" in res["markdown"]
    # 空清单 / 无 LLM / 全空文本：不调用
    assert synthesize.run([], ctx_llm)["llm_used"] is False
    assert synthesize.run(items, TaskContext(run_id="t", llm=None))["llm_used"] is False
    assert synthesize.run([{"point_id": "p", "text": "  "}], ctx_llm)["llm_used"] is False
    # 坏产出 / LLM 异常：llm_used=False + error 留痕
    bad = synthesize.run(items, TaskContext(run_id="t", llm=FakeLlm("不是JSON")))
    assert bad["llm_used"] is False and bad.get("error")
    boom = synthesize.run(items, TaskContext(run_id="t", llm=BoomLlm()))
    assert boom["llm_used"] is False and boom.get("error")


# ---- API ----

@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")),
                       "test-token-123")
    from knowatlas.web.app import create_app
    app = create_app(cfg, dl, *registries)
    return TestClient(app, headers={"Host": "127.0.0.1:8420",
                                    "X-KnowAtlas-Token": "test-token-123"})


def test_api_preview_no_persist(cfg, dl, client, monkeypatch):
    pid = _seed_point(dl, "sy:1", "进销存以销售单为核心驱动采购补货")
    monkeypatch.setattr("knowatlas.semantic.llm.LlmClient.from_config",
                        lambda cfg: _good_llm())
    r = client.post("/api/synthesize/preview",
                    json={"point_ids": [pid], "instruction": "自定义要求"})
    assert r.status_code == 200
    body = r.json()
    assert body["markdown"].startswith("# 合成方案")
    assert body["points"][0]["point_id"] == pid
    # 预览零副作用：条目数不变
    n = dl._conn.execute("SELECT COUNT(*) AS c FROM entries").fetchone()["c"]
    assert n == 1
    # 空勾选 400（防幻觉闸门）/ 不存在点 404
    assert client.post("/api/synthesize/preview",
                       json={"point_ids": []}).status_code == 400
    assert client.post("/api/synthesize/preview",
                       json={"point_ids": ["deadbeefdeadbeef"]}).status_code == 404


def test_api_commit_creates_synthesized_entry(cfg, dl, client):
    pid = _seed_point(dl, "sy:2", "库存盘点按 ABC 分类法分频次")
    r = client.post("/api/synthesize/commit",
                    json={"point_ids": [pid], "instruction": "x",
                          "markdown": _MD})
    assert r.status_code == 200
    eid = r.json()["entry_id"]
    row = dl._conn.execute(
        "SELECT source_type, title, locator, inline_content, meta FROM entries"
        " WHERE id=?", (eid,)).fetchone()
    assert row["source_type"] == "synthesized"
    assert row["title"] == "合成方案"          # 取自 markdown 一级标题
    assert row["locator"].startswith("synth://")
    meta = json.loads(row["meta"])
    assert meta["sources"] == [pid]            # 强制溯源落 meta.sources
    assert "盘点" in row["inline_content"]      # 回灌内容完整落条目
    # 内容寻址幂等：同文重复确认不产生新条目
    r2 = client.post("/api/synthesize/commit",
                     json={"point_ids": [pid], "markdown": _MD})
    assert r2.json()["entry_id"] == eid
    cnt = dl._conn.execute(
        "SELECT COUNT(*) AS c FROM entries WHERE source_type='synthesized'"
    ).fetchone()["c"]
    assert cnt == 1


def test_api_commit_hallucination_gate(cfg, dl, client):
    """防幻觉闸门：缺 sources / 空 markdown 拒绝落库。"""
    assert client.post("/api/synthesize/commit",
                       json={"point_ids": [], "markdown": _MD}).status_code == 400
    pid = _seed_point(dl, "sy:3", "销售单驱动补货")
    assert client.post("/api/synthesize/commit",
                       json={"point_ids": [pid], "markdown": ""}).status_code == 400
    cnt = dl._conn.execute(
        "SELECT COUNT(*) AS c FROM entries WHERE source_type='synthesized'"
    ).fetchone()["c"]
    assert cnt == 0
