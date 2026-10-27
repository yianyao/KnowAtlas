"""老化域闸门与点级隔离测试（工单 2026-10-27 裁决 ④）。

两件事必须钉死：
1. **非社科类才老化**：一级分类命中 `[aging] exclude_categories`（含子树与前缀变体）的
   点不判；没分类的点不因此被挡（黑名单语义）。
2. **点级隔离**：老化 A 点不改同源 B 点、不改条目状态、不动物理行。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from knowatlas.models import Entry
from knowatlas.pipeline.domain_gate import eligible_points, point_domains
from knowatlas.pipeline.lifecycle import run_lifecycle
from knowatlas.pipeline.points import point_hash

TODAY = date(2026, 10, 27)


def _cfg(tmp_path, exclude: tuple[str, ...] = ("文学创作",)) -> SimpleNamespace:
    return SimpleNamespace(db_path=str(tmp_path / "aging.db"),
                           aging_exclude_categories=exclude)


def _entry(dl, key: str, *, category: str | None = None) -> str:
    eid = dl.upsert_entries([Entry.build(
        source_type="manual", source_key=f"ag:{key}", title=f"条目{key}",
        locator=f"https://e.example/ag/{key}", inline_content=f"正文{key}",
        meta={})]).ids[0]
    if category:
        cat = dl.create_category(category, [], "manual")
        dl.attach_category(eid, cat.id, 1.0, "manual", "run-ag")
    return eid


def _point(dl, eid: str, text: str) -> str:
    dl.put_point({"content_hash": point_hash(text), "text": text, "summary": "",
                  "source_type": "manual", "judge": "integral",
                  "meta": {"kind": "hard"}},
                 {"entry_id": eid, "char_offset": 0, "anchor": text[:120]})
    return point_hash(text)[:16]


def _meta(dl, pid: str) -> dict:
    return dl.get_point_meta(pid)["meta"]


EOL_TEXT = "Python 2.7 中 print 是语句，不是函数。"


# ---- 域闸门 ----

def test_blacklist_semantics_and_prefix_match(dl):
    lit = _entry(dl, "lit", category="文学创作")
    lit2 = _entry(dl, "lit2", category="文学创作与评论")
    plain = _entry(dl, "plain")
    p_lit = _point(dl, lit, EOL_TEXT + "（甲）")
    p_lit2 = _point(dl, lit2, EOL_TEXT + "（乙）")
    p_plain = _point(dl, plain, EOL_TEXT + "（丙）")

    allowed = eligible_points(dl, [p_lit, p_lit2, p_plain], ("文学创作",))
    assert allowed[p_lit] is False
    assert allowed[p_lit2] is False       # startswith 变体
    assert allowed[p_plain] is True       # 无分类 → 黑名单不挡
    assert point_domains(dl, [p_lit])[p_lit] == {"文学创作"}
    # 空名单 = 全部放行（缺省保守关闭域闸门时行为不变）
    assert all(eligible_points(dl, [p_lit], ()).values())


def test_lifecycle_skips_social_science_points(tmp_path, dl):
    lit = _entry(dl, "lit", category="文学创作")
    tech = _entry(dl, "tech", category="技术开发")
    p_lit = _point(dl, lit, EOL_TEXT)
    p_tech = _point(dl, tech, EOL_TEXT + "（技术）")

    stats = run_lifecycle(_cfg(tmp_path), dl, llm=None, today=TODAY)
    assert stats["candidates"] == 1
    assert stats["version_stale"] == 1
    # 文学点一条都不写
    assert _meta(dl, p_lit) == {"kind": "hard"}
    # 技术点被判 stale（退出消费面，但行还在）
    assert _meta(dl, p_tech)["lifecycle"]["verdict"] == "stale"


def test_lifecycle_without_categories_still_judges(tmp_path, dl):
    eid = _entry(dl, "plain")
    pid = _point(dl, eid, EOL_TEXT)
    stats = run_lifecycle(_cfg(tmp_path), dl, llm=None, today=TODAY)
    assert stats["candidates"] == 1 and stats["version_stale"] == 1
    assert _meta(dl, pid)["lifecycle"]["verdict"] == "stale"


# ---- 点级隔离 ----

def test_aging_one_point_leaves_sibling_and_entry_intact(tmp_path, dl):
    eid = _entry(dl, "sib", category="技术开发")
    p_old = _point(dl, eid, EOL_TEXT)
    p_keep = _point(dl, eid, "REST 接口应使用幂等动词，GET 不得修改资源。")
    before = _meta(dl, p_keep)

    stats = run_lifecycle(_cfg(tmp_path), dl, llm=None, today=TODAY)
    assert stats["version_stale"] == 1

    assert _meta(dl, p_old)["lifecycle"]["verdict"] == "stale"
    # 同源另一点：一个字都不改
    assert _meta(dl, p_keep) == before
    assert dl.get_point_meta(p_keep)["meta"].get("lifecycle") is None
    # 条目本身不动（老化只标点，不归档/不改状态）
    entry = dl.get_entry(eid)
    assert entry.status == "active"
    assert dl.count_points() == 2         # 只标不删