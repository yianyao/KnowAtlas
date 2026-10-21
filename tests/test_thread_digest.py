"""delta_summarize + thread_digest 测试（0.2.0 第五十五批，完整方案 §9.4）。

覆盖：LLM 摘要任务（正常/降级/故障/部分节）、threads.digest 落库（迁移 005）、
Web /digest 端点（落库 + LLM 关闭不写库 + 守卫）、探针「关闭 LLM 后线程视图
不受影响」。会红的探针对应 CHANGELOG 第五十五批「复检探针」清单。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knowatlas.datalayer.db import DataLayer
from knowatlas.models import Entry
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import delta_summarize, thread_digest
from knowatlas.web.app import create_app


# ---- 测试替身 ----

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


_DELTA_REPLY = '[{"i":1,"summary":"确认了部署窗口，定在本周五。"},{"i":2,"summary":"补充了费用数字。"}]'
_DIGEST_REPLY = ('[{"problem":"部署窗口与费用分摊。",'
                 '"progress":"- 第一轮定窗口\\n- 第二轮给出费用数字",'
                 '"conclusion":"- 待周五部署"}]')


def _seed_mail_turns(dl: DataLayer) -> list[Entry]:
    """两封邮件条目（inline_content=quote_strip 产物，meta 带发件人/日期）。"""
    es = [
        Entry.build(source_type="mail", source_key="dg:m1", title="Re: 部署窗口",
                    locator="mail://a/m1", locator_canonical=None,
                    inline_content="部署窗口确认在周五，请相关同学准备。",
                    native_path="INBOX",
                    meta={"source_type": "mail", "account": "a", "from": "a@x.com",
                          "date": "2026-10-20T10:00:00+08:00"}),
        Entry.build(source_type="mail", source_key="dg:m2", title="Re: 部署窗口",
                    locator="mail://a/m2", locator_canonical=None,
                    inline_content="费用分摊数字见附件：合计 1.2 万。",
                    native_path="INBOX",
                    meta={"source_type": "mail", "account": "a", "from": "b@x.com",
                          "date": "2026-10-20T11:00:00+08:00"}),
    ]
    dl.upsert_entries(es)
    return es


# ---- 任务级：delta_summarize ----

def test_delta_summarize_degrades_without_llm():
    """llm 未配置 → 空 summaries，绝不臆造。"""
    res = delta_summarize.run([{"entry_id": "e1", "delta": "新增结论"}],
                              TaskContext(run_id="r1"))
    assert res == {"summaries": {}, "llm_used": False}


def test_delta_summarize_llm_ok():
    llm = FakeLlm([_DELTA_REPLY])
    items = [{"entry_id": "e1", "title": "Re: 部署", "delta": "定了周五",
              "sender": "a@x.com", "sent_at": "2026-10-20"},
             {"entry_id": "e2", "title": "Re: 部署", "delta": "费用 1.2 万",
              "sender": "b@x.com", "sent_at": "2026-10-20"}]
    res = delta_summarize.run(items, TaskContext(run_id="r1", llm=llm))
    assert res["llm_used"] is True
    assert res["summaries"]["e1"] == "确认了部署窗口，定在本周五。"
    assert "增量正文" in llm.calls[0] and "定了周五" in llm.calls[0]


def test_delta_summarize_llm_failure_degrades():
    """LLM 故障 → 空 summaries + error，不阻塞不写库。"""
    res = delta_summarize.run([{"entry_id": "e1", "delta": "x"}],
                              TaskContext(run_id="r1", llm=FakeLlm(broken=True)))
    assert res["llm_used"] is False and res["summaries"] == {} and "error" in res


def test_delta_summarize_garbage_reply():
    """LLM 回复无法解析 → 降级并带 error（不把垃圾写进 meta）。"""
    res = delta_summarize.run([{"entry_id": "e1", "delta": "x"}],
                              TaskContext(run_id="r1", llm=FakeLlm(["好的，我明白了"])))
    assert res["llm_used"] is False and res["summaries"] == {} and "error" in res


# ---- 任务级：thread_digest ----

def test_thread_digest_degrades_without_llm():
    res = thread_digest.run([{"delta": "x"}], "线", TaskContext(run_id="r1"))
    assert res == {"digest": "", "llm_used": False}


def test_thread_digest_llm_ok_assembles_sections():
    """三节组装成带标记行的纯文本；空节剔除。"""
    llm = FakeLlm([_DIGEST_REPLY])
    items = [{"sender": "a@x.com", "sent_at": "2026-10-20T10:00", "title": "t",
              "delta": "定了周五"}]
    res = thread_digest.run(items, "部署线", TaskContext(run_id="r1", llm=llm))
    assert res["llm_used"] is True
    d = res["digest"]
    assert d.startswith("【问题】") and "【关键进展】" in d and "【当前结论/待办】" in d
    # 轮次与线程名注入提示词
    assert "部署线" in llm.calls[0] and "定了周五" in llm.calls[0]


def test_thread_digest_partial_sections():
    reply = '[{"problem":"窗口","progress":"","conclusion":""}]'
    res = thread_digest.run([{"delta": "x"}], "线",
                            TaskContext(run_id="r1", llm=FakeLlm([reply])))
    assert res["digest"] == "【问题】\n窗口"


def test_thread_digest_llm_failure_degrades():
    res = thread_digest.run([{"delta": "x"}], "线",
                            TaskContext(run_id="r1", llm=FakeLlm(broken=True)))
    assert res == {"digest": "", "llm_used": False, "error": "模拟故障"}


# ---- 数据层：threads.digest（迁移 005） ----

def test_set_thread_digest_persists(dl):
    es = _seed_mail_turns(dl)
    t = dl.create_thread("摘要线")
    dl.add_thread_item(t.id, es[0].id)
    assert dl.get_thread(t.id).digest is None          # 初始为空
    dl.set_thread_digest(t.id, "【问题】\n窗口")
    got = dl.get_thread(t.id)
    assert got.digest == "【问题】\n窗口"               # 重开库仍在（持久化）
    assert any(x["id"] == t.id and x["digest"] == "【问题】\n窗口"
               for x in dl.list_threads())
    # 重算覆盖（摘要是压缩表示，可随时重算）
    dl.set_thread_digest(t.id, "【问题】\n新摘要")
    assert dl.get_thread(t.id).digest == "【问题】\n新摘要"
    with pytest.raises(Exception):                     # 空 digest 拒写
        dl.set_thread_digest(t.id, "  ")


# ---- Web API ----

@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_TEST_TOKEN")),
                       "test-token-123")
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def _auth():
    return {"X-KnowAtlas-Token": "test-token-123", "Origin": "http://127.0.0.1:8420"}


def test_digest_endpoint_needs_token_and_404(client, dl):
    es = _seed_mail_turns(dl)
    t = dl.create_thread("守卫线")
    dl.add_thread_item(t.id, es[0].id)
    assert client.post(f"/api/threads/{t.id}/digest", json={}).status_code == 403
    assert client.post(f"/api/threads/ffffffffffffffff/digest", json={},
                       headers=_auth()).status_code == 404


def test_digest_endpoint_no_llm_writes_nothing(client, dl):
    """探针：LLM 关闭 → 不写 digest 不写 delta_summary，线程视图照常。"""
    es = _seed_mail_turns(dl)
    t = dl.create_thread("无 LLM 线")
    dl.add_thread_item(t.id, es[0].id)
    r = client.post(f"/api/threads/{t.id}/digest", json={}, headers=_auth())
    assert r.status_code == 200
    assert r.json()["llm_used"] is False and r.json()["applied"] is False
    assert dl.get_thread(t.id).digest is None          # 未写库
    detail = client.get(f"/api/threads/{t.id}").json()  # 线程视图不受影响
    assert detail["digest"] is None and detail["items"][0]["delta_summary"] == ""


def test_digest_endpoint_with_llm_persists(client, dl, monkeypatch):
    """LLM 可用 → meta.delta_summary + threads.digest 双落库，GET 回读；
    二次调用缺摘要条目为空 → 只跑 thread_digest（一次调用）。"""
    es = _seed_mail_turns(dl)
    t = dl.create_thread("摘要端点线")
    dl.add_thread_item(t.id, es[0].id)
    dl.add_thread_item(t.id, es[1].id)
    fake = FakeLlm([_DELTA_REPLY, _DIGEST_REPLY])

    import knowatlas.semantic.llm as kll
    monkeypatch.setattr(kll.LlmClient, "from_config",
                        classmethod(lambda cls, cfg: fake))
    r = client.post(f"/api/threads/{t.id}/digest", json={}, headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["llm_used"] is True and body["applied"] is True
    assert body["summarized"] == 2 and len(fake.calls) == 2  # 先 delta 后 digest
    assert dl.get_entry(es[0].id).meta["delta_summary"] == "确认了部署窗口，定在本周五。"
    assert dl.get_thread(t.id).digest.startswith("【问题】")
    detail = client.get(f"/api/threads/{t.id}").json()
    assert detail["digest"].startswith("【问题】")
    assert detail["items"][1]["delta_summary"] == "补充了费用数字。"

    # 二次调用：摘要已齐 → delta_summarize 不再调 LLM，只有 thread_digest 一次调用
    fake2 = FakeLlm([_DIGEST_REPLY])
    monkeypatch.setattr(kll.LlmClient, "from_config",
                        classmethod(lambda cls, cfg: fake2))
    r2 = client.post(f"/api/threads/{t.id}/digest", json={}, headers=_auth())
    assert r2.json()["summarized"] == 0 and len(fake2.calls) == 1
    assert dl.get_entry(es[0].id).meta["delta_summary"] == "确认了部署窗口，定在本周五。"


def test_digest_endpoint_llm_failure_writes_nothing(client, dl, monkeypatch):
    """LLM 故障 → 两层都不写库，返回 error（原始正文永在，视图不受影响）。"""
    es = _seed_mail_turns(dl)
    t = dl.create_thread("故障线")
    dl.add_thread_item(t.id, es[0].id)
    import knowatlas.semantic.llm as kll
    monkeypatch.setattr(kll.LlmClient, "from_config",
                        classmethod(lambda cls, cfg: FakeLlm(broken=True)))
    r = client.post(f"/api/threads/{t.id}/digest", json={}, headers=_auth())
    assert r.status_code == 200
    assert r.json()["llm_used"] is False and "error" in r.json()
    assert dl.get_thread(t.id).digest is None
    assert "delta_summary" not in dl.get_entry(es[0].id).meta
