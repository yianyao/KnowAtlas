"""消费面守卫（0.2.0 第三十六批）：非活跃知识不进知识消费页。

判据 = status='active' + 非待清理（value_flag!=not_knowledge）+ 非永久失效
（link_status!=dead）。管理页（list_by_value_flag / list_by_link_status）不受影响。
"""

from __future__ import annotations

import pytest

from knowatlas.datalayer.db import DataLayer
from knowatlas.models import Entry


@pytest.fixture
def seeded(dl: DataLayer) -> dict[str, Entry]:
    """好条目 + 待清理条目 + 永久失效条目，前两者挂同一分类，另有空类子分类。"""
    good = Entry.build(source_type="bookmark", source_key="cg:good", title="量子计算好教程",
                       locator="https://good.example/q", locator_canonical="https://good.example/q")
    flagged = Entry.build(source_type="bookmark", source_key="cg:flag", title="量子计算已废弃页",
                          locator="https://good.example/old", locator_canonical="https://good.example/old")
    dead = Entry.build(source_type="bookmark", source_key="cg:dead", title="量子计算失效链接",
                       locator="https://good.example/404", locator_canonical="https://good.example/404")
    dl.upsert_entries([good, flagged, dead])
    dl.merge_meta(flagged.id, {"value_flag": "not_knowledge"})
    dl.merge_meta(dead.id, {"link_status": "dead"})
    cat = dl.create_category("守卫类", [], "manual")
    sub = dl.create_category("守卫子类", [cat.id], "manual")
    empty_sub = dl.create_category("守卫空子类", [cat.id], "manual")
    for e in (good, flagged, dead):
        dl.attach_category(e.id, sub.id, 1.0, "manual", "r1")
    return {"good": good, "flagged": flagged, "dead": dead,
            "cat": cat, "sub": sub, "empty_sub": empty_sub}


def test_overview_prunes_non_consumable_and_empty_categories(dl, seeded):
    s = seeded
    nodes = {n["id"]: n for n in dl.get_graph_overview()["nodes"]}
    assert f"c:{s['cat'].id}" in nodes
    # value=1：只数好条目，待清理/失效不计
    assert nodes[f"c:{s['cat'].id}"]["value"] == 1


def test_overview_prunes_category_without_consumable_entries(dl, seeded):
    """全是非活跃条目的分类（含空子类链）不进总览。"""
    s = seeded
    only_bad = Entry.build(source_type="bookmark", source_key="cg:bad2", title="纯待清理类目条",
                           locator="https://bad.example/x", locator_canonical="https://bad.example/x")
    dl.upsert_entries([only_bad])
    dl.merge_meta(only_bad.id, {"value_flag": "not_knowledge"})
    lone = dl.create_category("纯脏类", [], "manual")
    dl.attach_category(only_bad.id, lone.id, 1.0, "manual", "r1")
    ids = {n["id"] for n in dl.get_graph_overview()["nodes"]}
    assert f"c:{lone.id}" not in ids
    assert f"c:{s['cat'].id}" in ids


def test_subtree_and_search_graph_filter(dl, seeded):
    s = seeded
    sub_ids = {n["id"] for n in dl.get_graph_subtree(s["cat"].id)["nodes"]}
    assert f"e:{s['good'].id}" in sub_ids
    assert f"e:{s['flagged'].id}" not in sub_ids
    assert f"e:{s['dead'].id}" not in sub_ids
    assert f"c:{s['empty_sub'].id}" not in sub_ids          # 空子类剪枝
    assert f"c:{s['cat'].id}" in sub_ids                    # 焦点根保留
    hits = {n["id"] for n in dl.search_graph("量子计算")["nodes"]}
    assert f"e:{s['good'].id}" in hits
    assert f"e:{s['flagged'].id}" not in hits and f"e:{s['dead'].id}" not in hits


def test_radiate_and_reverse_filter(dl, seeded):
    s = seeded
    r = dl.radiate(f"c:{s['sub'].id}")
    node_ids = {n["id"] for n in r["nodes"]}
    assert f"e:{s['good'].id}" in node_ids
    assert f"e:{s['flagged'].id}" not in node_ids and f"e:{s['dead'].id}" not in node_ids
    # 非活跃条目自身不能当焦点（_entry_row 守卫 → None → API 404）
    assert dl.radiate(f"e:{s['flagged'].id}") is None
    rev = dl.reverse_reach(f"c:{s['sub'].id}")
    assert f"e:{s['flagged'].id}" not in {i["id"] for i in rev["items"]}


def test_search_fts_and_host_and_thread_filter(dl, seeded):
    s = seeded
    fts_ids = {h.entry_id for h in dl.search_fts("量子计算")}
    assert fts_ids == {s["good"].id}
    host_ids = {e.id for e in dl.entries_by_host("good.example")}
    assert host_ids == {s["good"].id}
    t = dl.create_thread("守卫线")
    dl.add_thread_item(t.id, s["good"].id)
    dl.add_thread_item(t.id, s["flagged"].id)
    member_ids = {it.entry_id for it in dl.get_thread(t.id).items}
    assert member_ids == {s["good"].id}          # 线索里自动隐藏非活跃条目


def test_management_pages_unaffected(dl, seeded):
    """管理页（待清理候选 / 失效链接）照常全量列出，不被守卫拦。"""
    s = seeded
    assert s["flagged"].id in {e.id for e in dl.list_by_value_flag("not_knowledge")}
    assert s["dead"].id in {e.id for e in dl.list_by_link_status("dead")}
