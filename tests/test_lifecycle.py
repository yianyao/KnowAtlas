"""点级老化两型测试（P2，2026-10-26 工单 `P2点级老化两型`）。

覆盖：版本抽取与 EOL 判定（含家族 N.x、大版本存活声明、表覆盖）、
run_lifecycle 两段编排（版本型三值 / 领域闸门 / 退场型按技术栈分组 / 防幻觉降级 /
幂等 / dry-run 不写）、CLI 开关。全部人造 fixture + LLM 替身，零真实费用。
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from knowatlas.cli import build_parser
from knowatlas.models import Entry
from knowatlas.pipeline.lifecycle import run_lifecycle
from knowatlas.pipeline.points import point_hash
from knowatlas.semantic import eol
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.tasks import point_lifecycle

TODAY = date(2026, 10, 26)


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
            raise AssertionError(f"多余调用 #{self.calls}")
        return self.replies[self.calls - 1]


def _pt(dl, key: str, text: str, *, kind: str | None = "hard") -> str:
    e = dl.upsert_entries([Entry.build(
        source_type="manual", source_key=f"lc:{key}", title=f"条目{key}",
        locator=f"https://e.example/lc/{key}", inline_content=f"正文{key}",
        meta={})]).ids[0]
    meta = {"kind": kind} if kind else {}
    dl.put_point({"content_hash": point_hash(text), "text": text, "summary": "",
                  "source_type": "manual", "judge": "integral", "meta": meta},
                 {"entry_id": e, "char_offset": 0, "anchor": text[:120]})
    return point_hash(text)[:16]


def _meta(dl, pid: str) -> dict:
    return dl.get_point_meta(pid)["meta"]


# ---- EOL 表与版本抽取 ----

def test_detect_versions_and_eol_status():
    hits = {h.tech: h.version for h in eol.detect_versions("Python 2.7 中 print 是语句")}
    assert hits == {"python": "2.7"}
    assert eol.eol_status("python", "2.7", today=TODAY)[0] == "eol"
    assert eol.eol_status("python", "3.8", today=TODAY)[0] == "eol"
    # 未收录版本 → unknown（调用方降 suspect，绝不猜「新版本就是支持的」）
    assert eol.eol_status("python", "3.12", today=TODAY)[0] == "unknown"
    # 大版本存活声明：'Python 3.x' 不能因 3.6–3.9 的 EOL 记录被误杀
    assert eol.eol_status("python", "3.x", today=TODAY)[0] == "supported"
    assert eol.eol_status("python", "2.x", today=TODAY)[0] == "eol"
    # 表按大版本记（nodejs）：14.18 落到 14 上比
    assert eol.eol_status("nodejs", "14.18", today=TODAY)[0] == "eol"
    # 裸 node 不是别名（图节点不能算 Node.js）
    assert eol.detect_versions("节点(node)之间通过边相连") == []
    # 年份不是版本
    assert eol.detect_versions("Python 2019 年的生态") == []
    # 「或更高版本」是最低门槛，不是「在用这个版本」（真库自检抓到的假阳性）
    assert eol.detect_versions("需要 Python 3.10 或更高版本、Node.js 16.0 或更高版本") == []
    assert eol.detect_versions("Node.js 22.19+ 或 24+") == []
    assert eol.detect_versions("Python 3.8 及以上") == []
    # 但「教程用的是 3.8」仍要判
    assert [h.version for h in eol.detect_versions("Python 3.8 的 dict 有序性")] == ["3.8"]


def test_load_table_override(tmp_path):
    (tmp_path / "eol.json").write_text(json.dumps(
        {"meteor": {"1.0": "2020-01-01"}}), encoding="utf-8")
    table = eol.load_table(tmp_path)
    assert eol.eol_status("meteor", "1.0", table=table, today=TODAY)[0] == "eol"
    assert "meteor" not in eol.EOL           # 内置表不被就地污染
    # 坏文件不炸
    (tmp_path / "eol.json").write_text("{not json", encoding="utf-8")
    assert eol.load_table(tmp_path)["python"]["2.7"] == "2020-01-01"


# ---- 版本型（A 段）与验收样本 ----

def test_version_type_acceptance_samples(dl):
    """6 条验收样本：前两条 stale，其余不判 stale；opinion 被闸门挡掉。"""
    p_old_py = _pt(dl, "a", "Python 2.7 中 print 是语句而不是函数，需 from __future__ import print_function")
    p_old_jq = _pt(dl, "b", "jQuery 1.x 插件写法：用 $.fn.extend 注册方法，兼容 IE8")
    p_new_py = _pt(dl, "c", "Python 3.12 支持 PEP 695 的类型参数语法")
    p_method = _pt(dl, "d", "通用方法论：先定义问题边界，再收集数据，最后验证假设")
    p_opinion = _pt(dl, "e", "Python 2.7 早已过时，大家都应该迁移", kind="opinion")
    p_future = _pt(dl, "f", "2027 年 AGI 将普及，模型能力每 18 个月翻倍")

    stats = run_lifecycle(None, dl, llm=None, today=TODAY)
    assert stats["candidates"] == 5                     # opinion 被领域闸门挡掉
    assert stats["version_stale"] == 2 and stats["version_suspect"] == 1

    for pid in (p_old_py, p_old_jq):
        m = _meta(dl, pid)
        assert m["lifecycle"]["verdict"] == "stale"
        assert m["lifecycle"]["kind"] == "version"
        assert m["lifecycle"]["evidence"]               # 必附官方依据
    assert _meta(dl, p_old_py)["lifecycle"]["tech"] == "python"
    assert dl.get_point_meta(p_old_py)["meta"]           # 点本身没被删
    # Python 3.12：不在表内 → suspect（不判 stale）
    assert _meta(dl, p_new_py)["lifecycle"]["verdict"] == "suspect"
    # 无技术栈的点不写结论（也不白烧 LLM）
    assert "lifecycle" not in _meta(dl, p_method)
    assert "lifecycle" not in _meta(dl, p_future)
    assert "lifecycle" not in _meta(dl, p_opinion)
    # stale 走现成机制退出消费面
    flags = {p["id"]: p["aging_flag"] for p in dl.points_of_kind("hard")}
    assert flags[p_old_py] == "stale" and flags[p_old_jq] == "stale"
    assert flags[p_new_py] == "" and flags[p_method] == ""


# ---- 退场型（B 段） ----

def test_retired_type_grouped_by_tech(dl):
    p_ng = _pt(dl, "a", "AngularJS 的双向绑定依赖 $scope 脏检查机制")
    p_py = _pt(dl, "b", "Python 的 GIL 让多线程无法并行执行 CPU 密集任务")
    payload = json.dumps([
        {"i": 1, "verdict": "retired",
         "evidence": "AngularJS 已于 2021-12-31 结束长期支持 https://docs.angularjs.org/misc/version-support-status"},
        {"i": 2, "verdict": "active",
         "evidence": "Python 3.13 仍在发布 https://devguide.python.org/versions/"},
    ], ensure_ascii=False)
    llm = FakeLlm([payload])
    stats = run_lifecycle(None, dl, llm=llm, today=TODAY)
    assert stats["tech_groups"] == 2 and stats["llm_calls"] == 1   # 按技术栈分组，一批
    assert stats["retired_stale"] == 1 and stats["retired_ok"] == 1
    assert _meta(dl, p_ng)["lifecycle"]["verdict"] == "stale"
    assert _meta(dl, p_ng)["lifecycle"]["kind"] == "retired"
    assert _meta(dl, p_py)["lifecycle"]["verdict"] == "ok"
    # ok 不动 aging 列（留给 L2 与人裁），只有 stale 退出消费面
    assert dl.get_point_meta(p_py)["meta"].get("lifecycle")["verdict"] == "ok"
    flags = {p["id"]: p["aging_flag"] for p in dl.points_of_kind("hard")}
    assert flags[p_ng] == "stale" and flags[p_py] == ""


def test_task_retired_without_evidence_downgrades_to_keep():
    payload = json.dumps([{"i": 1, "verdict": "retired", "evidence": ""}],
                         ensure_ascii=False)
    res = point_lifecycle.run([{"tech": "jquery", "sample": "x"}],
                              TaskContext(run_id="t", llm=FakeLlm([payload])))
    assert res["verdicts"]["jquery"]["verdict"] == "keep"
    assert "降级" in res["verdicts"]["jquery"]["evidence"]
    assert point_lifecycle.run([{"tech": "x"}],
                               TaskContext(run_id="t", llm=None))["verdicts"] == {}


def test_llm_unavailable_keeps_version_segment(dl):
    """LLM 不可用：A 段落库，B 段 skip 且不写半成品。"""
    p_old = _pt(dl, "a", "PHP 7.4 的箭头函数写法")
    p_tech = _pt(dl, "b", "Vue 的响应式原理是新版本优势之一")   # 无版本 → 依赖 B 段
    stats = run_lifecycle(None, dl, llm=None, today=TODAY)
    assert stats["version_stale"] == 1 and stats["llm_skipped"]
    assert _meta(dl, p_old)["lifecycle"]["verdict"] == "stale"
    assert "lifecycle" not in _meta(dl, p_tech)


# ---- 幂等与 dry-run ----

def test_idempotent_and_dry_run(dl):
    p_old = _pt(dl, "a", "Django 3.2 的 default_auto_field 设置")
    dry = run_lifecycle(None, dl, dry_run=True, llm=None, today=TODAY)
    assert dry["version_stale"] == 1
    assert "lifecycle" not in _meta(dl, p_old)          # dry-run 零写入
    run_lifecycle(None, dl, llm=None, today=TODAY)
    before = json.dumps(_meta(dl, p_old), sort_keys=True, ensure_ascii=False)
    again = run_lifecycle(None, dl, llm=None, today=TODAY)
    assert again["candidates"] == 0 and again["version_stale"] == 0
    after = json.dumps(_meta(dl, p_old), sort_keys=True, ensure_ascii=False)
    assert before == after
    # 审计留痕
    with dl.transaction() as conn:
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM task_log WHERE target=?", (p_old,)).fetchall()]
    assert "point_lifecycle" in actions


# ---- CLI ----

def test_cli_kaging_lifecycle_flags():
    ns = build_parser().parse_args(["kaging", "--lifecycle"])
    assert ns.lifecycle is True and ns.limit is None      # 默认全库
    ns2 = build_parser().parse_args(["kaging", "--points"])
    assert ns2.lifecycle is False and ns2.points is True
    ns3 = build_parser().parse_args(["kaging", "--lifecycle", "--limit", "5", "--dry-run"])
    assert ns3.limit == 5 and ns3.dry_run is True