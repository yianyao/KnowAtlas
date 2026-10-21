"""AI 会话源测试（0.2.0 第五十七批，TODO Phase 3 探针）。

harvester exports 产物 fixture 按真实 exporter 格式构造：
<root>/<category>/<YYYY-MM>/*.json（SessionRecord 平铺结构）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowatlas.adapters.session import collect_sessions
from knowatlas.errors import AdapterError
from knowatlas.pipeline.sync import run_sync


def _export(rec: dict, root: Path, category: str = "Agent", month: str = "2026-07",
            name: str = "202607200912__a__t__88efde") -> Path:
    d = root / category / month
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{name}.json"
    f.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return f


def _rec(sid: str = "ws-a/abc.jsonl", title: str = "部署窗口讨论",
         n_turns: int = 3, source: str = "workbuddy-transcript") -> dict:
    msgs = []
    for i in range(n_turns):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role,
                     "text": f"{title}·第{i}轮{'问题' if role == 'user' else '回答'}内容",
                     "timestamp": f"2026-07-20 09:{10 + i:02d}:00"})
    return {"source": source, "session_id": sid, "title": title,
            "created_at": "2026-07-20 09:10:00",
            "updated_at": "2026-07-20 09:45:00",
            "extra": {"workspace": "ws-a", "origin": "workbuddy-projects-transcript",
                      "lossy": False, "models": {"glm-5": 2}},
            "messages": msgs}


def _cfg(root: Path, enabled: bool = True):
    class Cfg:
        def get(self, key):
            assert key in ("sources.session", "sources.sessions")
            return {"enabled": enabled, "harvester_dirs": [str(root)]}
    return Cfg()


# ---- collect_sessions ----

def test_collect_maps_record(tmp_path):
    _export(_rec(), tmp_path)
    out = collect_sessions(_cfg(tmp_path))
    assert len(out.entries) == 1
    e = out.entries[0]
    assert e.source_type == "session"
    assert e.locator == "session://ws-a%2Fabc.jsonl"
    assert e.title == "部署窗口讨论"
    assert e.locator.startswith("session://")
    assert e.created_at == "2026-07-20 09:10:00"
    assert e.native_path == "Agent/2026-07"          # 先验路径信号
    # 探针：turns 摘要（role: 首行）
    assert e.inline_content.startswith("user: 部署窗口讨论·第0轮问题内容")
    assert "assistant: 部署窗口讨论·第1轮回答内容" in e.inline_content
    assert e.meta["turns"] == 3 and e.meta["turns_content"] == 3
    assert e.meta["harvester_source"] == "workbuddy-transcript"
    assert e.meta["workspace"] == "ws-a"
    assert e.meta["export_file"] == "Agent/2026-07/202607200912__a__t__88efde.json"
    assert e.content_hash and out.stats["_full_bodies"][e.id].startswith("## [user]")


def test_collect_skips_manifest_and_bad_files(tmp_path):
    _export(_rec(), tmp_path)
    (tmp_path / "export_manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "Agent" / "2026-07" / "broken.json").write_text("{oops", encoding="utf-8")
    _export(_rec(sid="ws-b/d.jsonl", title="另一会话"), tmp_path,
            name="202607210912__a__t2__aabbcc")
    out = collect_sessions(_cfg(tmp_path))
    assert out.stats["files"] == 3 and out.stats["skipped_parse"] == 1
    assert {e.locator for e in out.entries} == {
        "session://ws-a%2Fabc.jsonl", "session://ws-b%2Fd.jsonl"}


def test_collect_note_turns_excluded_from_body(tmp_path):
    rec = _rec(n_turns=2)
    rec["messages"].insert(0, {"role": "note", "text": "[context] <system-reminder>巨块注入</system-reminder>",
                               "timestamp": "2026-07-20 09:09:00"})
    _export(rec, tmp_path)
    out = collect_sessions(_cfg(tmp_path))
    e = out.entries[0]
    assert e.meta["turns"] == 3 and e.meta["turns_content"] == 2
    assert "system-reminder" not in out.stats["_full_bodies"][e.id]  # note 不进正文
    assert "[context]" not in (e.inline_content or "")
    # 但轮次元数据全落（探针：与产物一致）
    assert len(out.stats["conv_messages"]) == 3
    assert out.stats["conv_messages"][0]["message_id"].endswith("#0000")


def test_collect_empty_and_disabled(tmp_path):
    with pytest.raises(AdapterError):
        collect_sessions(_cfg(tmp_path / "nope"))  # 目录不存在
    out = collect_sessions(_cfg(tmp_path, enabled=False))
    assert out.stats == {"skipped_disabled": 1}


# ---- 端到端：ksync sessions 源（入库→content_store→conv_messages→线程）----

def test_sync_sessions_end_to_end(cfg, dl, registries, tmp_path):
    _export(_rec(), tmp_path)
    _export(_rec(sid="ws-a/def.jsonl", title="费用核对"), tmp_path,
            name="202607210912__a__t2__112233")
    cfg._data["sources"]["session"] = {
        "enabled": True, "harvester_dirs": [str(tmp_path)]}
    locators, semantics = registries

    stats = run_sync(cfg, dl, locators, semantics, full=True)
    src = stats["sources"]["sessions"]
    assert src["entries"] == 2 and src["created"] == 2
    assert src["contents_stored"] == 2
    assert src["messages_staged"] == 6 and src["threads_built"] == 2
    # 全量正文进 content_store；轮次落 conv_messages 且原文不复制
    by_title = {e.title: e for e in dl.list_entries(status="active", limit=10)}
    full = dl.get_content(by_title["部署窗口讨论"].content_hash)
    assert "部署窗口讨论·第0轮问题内容" in full
    convs = dl.list_conv_messages()
    assert len(convs) == 6
    assert "第0轮" not in json.dumps(convs, ensure_ascii=False)  # 原文不复制
    # 每会话一条 source 线程，item 挂会话条目
    threads = dl.list_threads(thread_type="source")
    assert len(threads) == 2 and all(t["item_count"] == 1 for t in threads)
    assert all(t["name"].startswith("🤖 ") for t in threads)
    # conv 轮次已挂 thread（父子关系如实为空 = 产物平铺结构）
    assert all(m["thread_id"] for m in dl.list_conv_messages())

    # 二跑幂等：不重建线程、conv 不重复
    stats2 = run_sync(cfg, dl, locators, semantics, full=True)
    src2 = stats2["sources"]["sessions"]
    assert src2["created"] == 0 and src2["threads_built"] == 0
    assert len(dl.list_conv_messages()) == 6
    assert len(dl.list_threads(thread_type="source")) == 2
