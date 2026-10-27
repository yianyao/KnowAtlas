"""fetch 候选口径（只取 active + 转正优先）与 `--entry` 定向补抓补抽。

对应变更工单：docs/design/变更工单-2026-10-27-fetch候选口径与定向补抓.md

覆盖：
- `_fetch_candidates`：rejected/pending 不进候选、刚转正的排最前、定向按点名顺序；
- 端到端：`--fetch-limit 1` 的预算不被老 rejected 吃掉；定向同步只处理点名条目且不归档；
- `kpoints --entry`：只抽点名条目；
- CLI：`--entry` 可重复解析。
"""

from __future__ import annotations

import uuid

import pytest

from knowatlas.cli import build_parser
from knowatlas.models import Entry
from knowatlas.pipeline.points import run_points_extract
from knowatlas.pipeline.sync import _fetch_candidates, run_sync


# ---- 测试替身 ----

class FakeLlm:
    """按调用序返回预设响应（一条条目一次调用）。"""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[str] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append(system + "\n" + user)
        idx = len(self.calls) - 1
        if idx >= len(self.replies):
            raise AssertionError(f"多余调用 #{idx + 1}")
        return self.replies[idx]


_REFINE_REPLY = (
    '{"summary":"一套知识条目",'
    '"points":[{"text":"FTS5 中文检索用 trigram 分词。","summary":"分词选型",'
    '"quote":"FTS5 中文检索用 trigram 分词。"}]}'
)


# ---- fixtures ----

@pytest.fixture
def folder_tree(tmp_path):
    """两个文件：a 会被舍弃，b 保持 active（字母序上 a 在前，专门验证预算不吃 rejected）。"""
    root = tmp_path / "知识库"
    root.mkdir()
    (root / "a-丢弃.txt").write_text("junk body", encoding="utf-8", newline="\n")
    (root / "b-保留.txt").write_text("knowledge body", encoding="utf-8", newline="\n")
    return root


def _enable(cfg, root) -> None:
    cfg._data["sources"]["folders"] = {"enabled": True, "roots": [str(root)]}


def _entries(dl, n: int = 3, *, body: str | None = None) -> list[Entry]:
    batch = uuid.uuid4().hex[:6]
    es = [Entry.build(source_type="manual", source_key=f"tg:{batch}:{i}",
                      title=f"定向条目 {batch}:{i}",
                      locator=f"https://example.com/tg/{batch}/{i}",
                      inline_content=body,
                      meta={"source_type": "manual"})
          for i in range(n)]
    dl.upsert_entries(es)
    return es


# ---- _fetch_candidates（§2.1）----

def test_fetch_candidates_only_active(cfg, dl):
    """rejected / pending 不进候选，且计数记账（预算不白花）。"""
    es = _entries(dl, 3)
    dl.set_status([es[1].id], "rejected")
    dl.set_status([es[2].id], "pending")
    cand, info = _fetch_candidates(dl, es)
    assert [e.id for e in cand] == [es[0].id]
    assert info == {"fetch_mode": "active", "fetch_candidates": 1,
                    "fetch_skipped_non_active": 2, "fetch_promoted_first": 0}


def test_fetch_candidates_promoted_first(cfg, dl):
    """刚转正的排最前（按最近一次转正时间降序），其余保持采集顺序。"""
    es = _entries(dl, 3)
    dl.log_task("2026-10-27T20:00:00+08:00", "web", "bulk_activate", es[2].id,
                {"old_status": "pending"})
    dl.log_task("2026-10-27T20:30:00+08:00", "web", "restore", es[1].id,
                {"old_status": "rejected"})
    cand, info = _fetch_candidates(dl, es)
    assert [e.id for e in cand] == [es[1].id, es[2].id, es[0].id]
    assert info["fetch_promoted_first"] == 2


def test_fetch_candidates_entry_mode_ignores_status(cfg, dl):
    """定向模式：不看状态（用户点名即抓），顺序按命令行。"""
    es = _entries(dl, 3)
    dl.set_status([es[0].id], "rejected")
    dl.set_status([es[1].id], "pending")
    cand, info = _fetch_candidates(dl, es, entry_ids=[es[2].id, es[1].id, es[0].id])
    assert [e.id for e in cand] == [es[2].id, es[1].id, es[0].id]
    assert info["fetch_mode"] == "entry" and info["fetch_candidates"] == 3


# ---- 端到端：fetch 预算（§2.1）----

def test_fetch_limit_budget_skips_rejected(cfg, dl, registries, folder_tree):
    """`--fetch-limit 1` 只落在 active 上：排在前面的 rejected 不再吃预算。

    回归 R16 实测：转正 3 条链接后 `--fetch-limit 1` 三条都没抓到，
    fetch_status 一个没写——预算被老 rejected 吃掉。
    """
    _enable(cfg, folder_tree)
    locators, semantics = registries
    run_sync(cfg, dl, locators, semantics, full=True)
    junk = dl.find_by_locator("file://a-丢弃.txt")[0]
    keep = dl.find_by_locator("file://b-保留.txt")[0]
    dl.set_status([junk.id], "rejected")

    stats = run_sync(cfg, dl, locators, semantics, fetch_limit=1)
    src = stats["sources"]["folders"]
    assert src["fetch_mode"] == "active"
    assert src["fetch_skipped_non_active"] == 1
    assert src["fetched"] == 1
    assert dl.get_entry(keep.id).content_hash                 # active 的那条被抓到
    assert dl.get_entry(junk.id).content_hash is None          # rejected 一条没动


# ---- 端到端：定向同步（§2.2）----

def test_sync_targeted_only_named_and_no_archive(cfg, dl, registries, folder_tree):
    """定向模式：只处理点名条目；即使带 full 也不归档未点名的条目。"""
    _enable(cfg, folder_tree)
    locators, semantics = registries
    run_sync(cfg, dl, locators, semantics, full=True)
    keep = dl.find_by_locator("file://b-保留.txt")[0]
    junk = dl.find_by_locator("file://a-丢弃.txt")[0]

    stats = run_sync(cfg, dl, locators, semantics, full=True, entry_ids=[keep.id])
    src = stats["sources"]["folders"]
    assert src["entries"] == 1 and "archived" not in src
    assert stats["targeted"] == {"requested": 1, "matched": 1, "missing_ids": []}
    assert dl.get_entry(junk.id).status == "active"            # 未被错误归档
    assert dl.get_entry(keep.id).content_hash                   # 定向默认补抓


def test_sync_targeted_reports_missing_ids(cfg, dl, registries, folder_tree):
    """源里找不到的点名 id → 明确报出，不静默当成功。"""
    _enable(cfg, folder_tree)
    locators, semantics = registries
    ghost = "0123456789abcdef"
    stats = run_sync(cfg, dl, locators, semantics, entry_ids=[ghost])
    assert stats["targeted"] == {"requested": 1, "matched": 0, "missing_ids": [ghost]}


# ---- kpoints --entry（§2.2）----

def test_kpoints_entry_extracts_only_named(cfg, dl):
    """定向抽取：只抽点名条目，另两条不进候选。"""
    es = _entries(dl, 3, body="FTS5 中文检索用 trigram 分词。" * 3)
    for e in es:
        dl.merge_meta(e.id, {"force_form": "integral"})       # 跳过形态判定，省调用
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_REFINE_REPLY]),
                               entry_ids=[es[1].id])
    assert stats["processed"] == 1 and stats["points_created"] == 1
    per = dl.points_of_entries([e.id for e in es])
    assert len(per[es[1].id]) == 1
    assert per[es[0].id] == [] and per[es[2].id] == []


# ---- CLI 解析 ----

def test_cli_entry_is_repeatable():
    parser = build_parser()
    a = parser.parse_args(["kpoints", "--entry", "aaa", "--entry", "bbb"])
    assert a.entry == ["aaa", "bbb"]
    b = parser.parse_args(["ksync", "--entry", "ccc"])
    assert b.entry == ["ccc"] and b.fetch_limit is None
    assert parser.parse_args(["kpoints"]).entry is None