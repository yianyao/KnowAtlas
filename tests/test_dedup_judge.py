"""去重边界对裁定测试（R30，2026-10-29 工单 `变更工单-2026-10-29-dedupe误并裁定.md`）。

覆盖：point_dupe_judge task（无 LLM / 合法解析 / 非法编号丢弃 / 故障）、dedup_points 的
边界对编排（无 LLM 保守不并、判不同不并 + task_log、判同并 + 裁定来源、judge 故障整批不并、
dry-run 零写入、向量不足的统计键）、以及「非边界对照旧路径照旧合并」。

全部人造 fixture + LLM 替身，零真实费用。
"""

from __future__ import annotations

from knowatlas.models import Entry
from knowatlas.pipeline.embed_index import dedup_points
from knowatlas.pipeline.points import point_hash
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.embed import normalize, vec_to_blob
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import point_dupe_judge

# ---- 替身 ----

class FakeLlm:
    """按调用序返回预设 JSON 数组；记录 prompt 便于断言口径。"""

    model_name = "fake-model"

    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls = 0
        self.prompts: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        self.prompts.append((system, user))
        if self.calls > len(self.replies):
            raise LlmError(f"多余调用 #{self.calls}")
        return self.replies[self.calls - 1]


class BoomLlm:
    def chat(self, system: str, user: str) -> str:
        raise LlmError("模拟故障")


# ---- fixture 工具 ----

#: 误并形态：同模板、只差一个数字（真库 labuladong「k=1 vs k=2」）
T_RISKY_A = "当交易次数上限 k 固定为 1 时，状态转移方程可化简，去掉 k 维度。"
T_RISKY_B = "当交易次数 k = 2 时，k 对状态转移的影响无法消除，方程必须保留 k 维度。"

#: 真重复形态：纯同义改写（无数字/否定词差异 → 旧路径直接合并）
T_SAME_A = "Agent = LLM + 上下文 + 工具，三者构成智能体的基本结构。"
T_SAME_B = "智能体的基本结构：Agent 等于大模型加上下文加工具的组合。"

_V1 = normalize([1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
_V2 = normalize([0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])


def _point(dl, key: str, text: str) -> str:
    entry = dl.upsert_entries([Entry.build(
        source_type="manual", source_key=f"dj:{key}", title=f"条目{key}",
        locator=f"https://e.example/dj/{key}", inline_content=f"正文{key}",
        meta={})]).ids[0]
    dl.put_point({"content_hash": point_hash(text), "text": text, "summary": "",
                  "source_type": "manual", "judge": "integral", "meta": {}},
                 {"entry_id": entry, "char_offset": 0, "anchor": text[:60]})
    return point_hash(text)[:16]


def _pair(dl, key_a: str, key_b: str, text_a: str, text_b: str,
          vec: list[float] | None = None) -> tuple[str, str]:
    """落两条同向量的点（默认 v1；第二组传 v2 让两簇互不相似）。"""
    v = vec if vec is not None else _V1
    pa = _point(dl, key_a, text_a)
    pb = _point(dl, key_b, text_b)
    dl.put_point_vectors([
        {"point_id": pa, "dim": 8, "vector": vec_to_blob(v), "model": "fake"},
        {"point_id": pb, "dim": 8, "vector": vec_to_blob(v), "model": "fake"}])
    return pa, pb


def _meta_of(dl, pid: str) -> dict:
    return next(p for p in dl.list_points(limit=100) if p["id"] == pid)["meta"]


# ---- point_dupe_judge task ----

def test_judge_without_llm_is_noop():
    res = point_dupe_judge.run([{"pair_id": "a|b", "a": "x", "b": "y"}],
                               TaskContext(run_id="t", llm=None))
    assert res == {"verdicts": {}, "llm_used": False}


def test_judge_parses_and_drops_invalid():
    """合法 JSON 解析；非法编号 / 越界编号 / 非法 same 值一律丢弃（宁漏勿错）。"""
    reply = ('[{"i":1,"same":false,"why":"限定条件不同"},'
             '{"i":2,"same":true,"why":"同义改写"},'
             '{"i":9,"same":true,"why":"越界"},'
             '{"i":"x","same":true,"why":"非法编号"},'
             '{"i":3,"same":"maybe","why":"非法值"}]')
    items = [{"pair_id": "p1|q1", "a": "A1", "b": "B1"},
             {"pair_id": "p2|q2", "a": "A2", "b": "B2"},
             {"pair_id": "p3|q3", "a": "A3", "b": "B3"}]
    res = point_dupe_judge.run(items, TaskContext(run_id="t", llm=FakeLlm([reply])))
    assert res["llm_used"] is True and "error" not in res
    assert res["verdicts"]["p1|q1"]["same"] is False
    assert res["verdicts"]["p2|q2"]["same"] is True
    assert "p3|q3" not in res["verdicts"]          # same=maybe 丢弃
    assert "越界" not in str(res["verdicts"])


def test_judge_tolerates_chinese_booleans():
    reply = '[{"i":1,"same":"是","why":"同一"},{"i":2,"same":"否","why":"不同"}]'
    items = [{"pair_id": "a", "a": "x", "b": "y"}, {"pair_id": "b", "a": "x", "b": "y"}]
    res = point_dupe_judge.run(items, TaskContext(run_id="t", llm=FakeLlm([reply])))
    assert res["verdicts"]["a"]["same"] is True
    assert res["verdicts"]["b"]["same"] is False


def test_judge_llm_failure_reports_error():
    res = point_dupe_judge.run([{"pair_id": "a", "a": "x", "b": "y"}],
                               TaskContext(run_id="t", llm=BoomLlm()))
    assert res["verdicts"] == {} and "error" in res


# ---- dedup_points 编排 ----

def test_risky_pair_not_merged_without_llm(cfg, dl):
    """无 LLM：边界对一律不并（宁漏勿误）；非边界对照照旧合并。"""
    pa, pb = _pair(dl, "r1", "r2", T_RISKY_A, T_RISKY_B)
    pc, pd = _pair(dl, "s1", "s2", T_SAME_A, T_SAME_B, _V2)
    stats = dedup_points(dl)
    assert stats["risky"] == 1 and stats["vetoed_no_llm"] == 1
    assert stats["dupes"] == 1 and stats["judged"] == 0
    assert "dupe_of" not in _meta_of(dl, pa) and "dupe_of" not in _meta_of(dl, pb)
    assert sum(1 for pid in (pc, pd) if _meta_of(dl, pid).get("dupe_of")) == 1
    # 审计：veto 对进 task_log（可回答「为什么没并」）
    veto_rows = dl.list_task_log_actions("dedup_points", "veto")
    assert veto_rows and "未启用" in veto_rows[-1]["detail"]


def test_risky_pair_merged_when_judged_same(cfg, dl):
    pa, pb = _pair(dl, "r1", "r2", T_RISKY_A, T_RISKY_B)
    reply = '[{"i":1,"same":true,"why":"同一条知识的两种写法"}]'
    stats = dedup_points(dl, llm=FakeLlm([reply]))
    assert stats["judged"] == 1 and stats["vetoed"] == 0 and stats["dupes"] == 1
    metas = {pid: _meta_of(dl, pid) for pid in (pa, pb)}
    kept = next(pid for pid, m in metas.items() if "dupe_of" not in m)
    dupe = next(pid for pid in metas if pid != kept)
    assert metas[dupe]["dupe_of"] == kept
    assert "裁定" in metas[dupe]["dupe_reason"]


def test_risky_pair_vetoed_when_judged_different(cfg, dl):
    """真库 6 对误并的形态：LLM 判不同 → 不并 + task_log 留痕。"""
    pa, pb = _pair(dl, "r1", "r2", T_RISKY_A, T_RISKY_B)
    reply = '[{"i":1,"same":false,"why":"k=1 与 k=2 是不同事实"}]'
    stats = dedup_points(dl, llm=FakeLlm([reply]))
    assert stats["judged"] == 1 and stats["vetoed"] == 1 and stats["dupes"] == 0
    assert "dupe_of" not in _meta_of(dl, pa) and "dupe_of" not in _meta_of(dl, pb)
    veto_rows = dl.list_task_log_actions("dedup_points", "veto")
    assert veto_rows and "不同知识" in veto_rows[-1]["detail"]
    # 幂等：重跑仍不并（副点标记没有出现，候选照旧进裁定）
    assert dedup_points(dl, llm=FakeLlm([reply]))["dupes"] == 0


def test_judge_failure_merges_nothing(cfg, dl):
    """LLM 故障 → 边界对整批不并（不写半成品），错误计数可见。"""
    _pair(dl, "r1", "r2", T_RISKY_A, T_RISKY_B)
    stats = dedup_points(dl, llm=BoomLlm())
    assert stats["judge_errors"] == 1 and stats["dupes"] == 0 and stats["judged"] == 0
    assert all("dupe_of" not in _meta_of(dl, p["id"]) for p in dl.list_points(limit=10))


def test_dry_run_writes_nothing(cfg, dl):
    _pair(dl, "r1", "r2", T_RISKY_A, T_RISKY_B)
    _pair(dl, "s1", "s2", T_SAME_A, T_SAME_B, _V2)
    before = dl.list_task_log_actions("dedup_points", "run")
    stats = dedup_points(dl, dry_run=True)
    assert stats["dry_run"] is True and stats["dupes"] == 1   # 只报「会并几条」
    assert all("dupe_of" not in _meta_of(dl, p["id"]) for p in dl.list_points(limit=10))
    assert dl.list_task_log_actions("dedup_points", "run") == before


def test_insufficient_vectors_returns_new_keys(cfg, dl):
    _point(dl, "only", T_SAME_A)
    stats = dedup_points(dl)
    assert stats["dupes"] == 0 and stats["vectors"] == 0
    for key in ("risky", "judged", "vetoed", "vetoed_no_llm", "judge_errors", "dry_run"):
        assert key in stats