"""数据层契约测试：upsert 覆盖纪律（H3）、多父 DAG（H4）、检索兜底（H2）、删除检测。"""

from __future__ import annotations

import pytest

from knowatlas.errors import ContractError
from knowatlas.ids import content_hash
from knowatlas.models import Entry, FetchResult, SOURCE_TYPES


def make_entry(**overrides) -> Entry:
    defaults = dict(
        source_type="manual", source_key="https://e.com/a",
        title="示例标题", locator="https://e.com/a",
        locator_canonical="https://e.com/a",
        meta={"source_type": "manual"},
    )
    defaults.update(overrides)
    return Entry.build(**defaults)


# ---- upsert 幂等与覆盖纪律（H3） ----

def test_upsert_idempotent(dl):
    e = make_entry()
    r1 = dl.upsert_entries([e])
    assert (r1.created, r1.updated, r1.unchanged) == (1, 0, 0)
    r2 = dl.upsert_entries([e])
    assert (r2.created, r2.updated, r2.unchanged) == (0, 0, 1)


def test_archived_status_not_revived_by_upsert(dl):
    e = make_entry()
    dl.upsert_entries([e])
    dl.set_status([e.id], "archived")
    dl.upsert_entries([e])  # 同字段重导
    assert dl.get_entry(e.id).status == "archived"
    e2 = make_entry(source_key="https://e.com/a", title="改动后的标题",
                    locator="https://e.com/a")
    dl.upsert_entries([e2])
    assert dl.get_entry(e.id).status == "archived"  # 源字段变化也不复活 status


def test_manual_meta_keys_preserved_on_update(dl):
    e = make_entry(meta={"source_type": "manual", "manual_note": "人工批注"})
    dl.upsert_entries([e])
    e2 = make_entry(meta={"source_type": "manual", "fetch_backend": "http_simple"})
    dl.upsert_entries([e2])
    saved = dl.get_entry(e.id).meta
    assert saved["manual_note"] == "人工批注"
    assert saved["fetch_backend"] == "http_simple"


# ---- locator / canonical ----

def test_find_by_canonical_and_attach_locator(dl):
    e = make_entry()
    dl.upsert_entries([e])
    assert dl.find_by_canonical("https://e.com/a").id == e.id
    assert dl.find_by_canonical("https://other.com/") is None
    dl.attach_locator(e.id, "https://mirror.e.com/a")   # 跨源合并落点（H1）
    hits = dl.find_by_locator("https://mirror.e.com/a")
    assert [x.id for x in hits] == [e.id]
    assert len(dl.find_by_locator("https://e.com/a")) == 1  # 主 locator 也命中


# ---- DAG 多父与结构变更（H4） ----

def test_dag_multipath_and_derived_paths(dl):
    a = dl.create_category("A", [], "manual")
    b = dl.create_category("B", [], "manual")
    c = dl.create_category("C", [a.id], "manual")
    dl.attach_parent(c.id, b.id)  # C 挂双父
    assert set(dl.get_category_paths(c.id)) == {"A/C", "B/C"}
    assert dl.get_category_by_path("B/C").id == c.id

    dl.detach_parent(c.id, b.id)
    assert dl.get_category_paths(c.id) == ["A/C"]

    dl.move_category(c.id, [b.id])  # 整棵移动，无级联重写
    assert dl.get_category_paths(c.id) == ["B/C"]


def test_move_category_rejects_cycle(dl):
    a = dl.create_category("A", [], "manual")
    b = dl.create_category("B", [a.id], "manual")
    with pytest.raises(ContractError):
        dl.move_category(a.id, [b.id])


def test_merge_categories_moves_entries_and_children(dl):
    a = dl.create_category("A", [], "manual")
    c = dl.create_category("C", [a.id], "manual")
    d = dl.create_category("D", [c.id], "manual")
    e = make_entry()
    dl.upsert_entries([e])
    dl.attach_category(e.id, c.id, 1.0, "rule", "run0000000000001")

    dl.merge_categories(c.id, a.id)
    assert dl.get_category(c.id) is None
    cats = {x["category_id"] for x in dl.get_entry_categories(e.id)}
    assert a.id in cats
    assert dl.get_category_paths(d.id) == ["A/D"]


def test_manual_attachment_protected_from_machine_overwrite(dl):
    a = dl.create_category("A", [], "manual")
    e = make_entry()
    dl.upsert_entries([e])
    dl.attach_category(e.id, a.id, 1.0, "manual", "run0000000000001")
    dl.attach_category(e.id, a.id, 0.5, "rule", "run0000000000002")  # 机器来源不得覆盖 manual
    row = [x for x in dl.get_entry_categories(e.id) if x["category_id"] == a.id][0]
    assert row["origin"] == "manual"


# ---- 检索（H2：trigram <3 字符零命中 → LIKE 兜底） ----

def test_two_char_query_finds_content(dl):
    text = "材料入库操作流程：先扫描条码，再确认库位，最后提交单据。"
    h = content_hash(text)
    dl.put_content(FetchResult(text=text, content_hash=h,
                               fetcher="file_reader", fetched_at="2026-10-19T00:00:00"))
    e = make_entry(source_type="folder", source_key="docs/store.md",
                   title="仓库管理制度", locator="file://docs/store.md",
                   content_hash=h)
    dl.upsert_entries([e])
    hits = dl.search_fts("入库")  # 两字词：FTS trigram 零命中，必须由 LIKE 兜底找到
    assert any(hit.entry_id == e.id for hit in hits)


def test_three_char_query_uses_fts(dl):
    e = make_entry(source_key="https://e.com/b", title="PostgreSQL 索引优化实践",
                   locator="https://e.com/b")
    dl.upsert_entries([e])
    hits = dl.search_fts("PostgreSQL")
    assert any(hit.entry_id == e.id for hit in hits)


# ---- 删除检测（H3 §3.6） ----

def test_archive_missing(dl):
    e1 = make_entry(source_key="https://e.com/1", locator="https://e.com/1")
    e2 = make_entry(source_key="https://e.com/2", locator="https://e.com/2")
    dl.upsert_entries([e1, e2])
    missing = dl.archive_missing("manual", {e1.id}, "run0000000000009")
    assert missing == [e2.id]
    assert dl.get_entry(e1.id).status == "active"
    assert dl.get_entry(e2.id).status == "archived"
    logs = dl.get_task_log()
    assert any(x["action"] == "archive" and x["target"] == e2.id
               and x["detail"].get("reason") == "missing_in_source" for x in logs)


# ---- 契约校验 ----

def test_rejects_unknown_source_type(dl):
    e = make_entry(source_type="nope", source_key="x", locator="file://a.md")
    with pytest.raises(ContractError):
        dl.upsert_entries([e])


def test_rejects_oversized_inline_content(dl):
    e = make_entry(inline_content="x" * 5000)
    with pytest.raises(ContractError):
        dl.upsert_entries([e])


def test_source_type_whitelist_shape():
    assert "manual" in SOURCE_TYPES and "bili" in SOURCE_TYPES


# ---- get_tree 的 count（子树 active 条目数；UI 默认隐藏空枝的依据） ----

def test_tree_count_reflects_subtree_active(dl):
    """A（1 active 直挂）→ B（1 active + 1 archived 直挂）：A.count=2, B.count=1。"""
    e_a = make_entry(source_key="https://e.com/ra", locator="https://e.com/ra")
    e_b1 = make_entry(source_key="https://e.com/b1", locator="https://e.com/b1")
    e_b2 = make_entry(source_key="https://e.com/b2", locator="https://e.com/b2")
    dl.upsert_entries([e_a, e_b1, e_b2])
    a = dl.create_category("A", [], "manual")
    b = dl.create_category("B", [a.id], "manual")
    dl.attach_category(e_a.id, a.id, 1.0, "manual", "run")
    dl.attach_category(e_b1.id, b.id, 1.0, "manual", "run")
    dl.attach_category(e_b2.id, b.id, 1.0, "manual", "run")
    dl.set_status([e_b2.id], "rejected")  # 舍弃的不计数
    tree = {n["name"]: n for n in dl.get_tree()}
    assert tree["A"]["count"] == 2
    assert tree["A"]["children"][0]["count"] == 1


def test_tree_count_zero_for_emptied_category(dl):
    """条目被全部舍弃/归档后 count=0（节点仍在，UI 默认隐藏、勾选可见）。"""
    e = make_entry()
    dl.upsert_entries([e])
    a = dl.create_category("A", [], "manual")
    dl.attach_category(e.id, a.id, 1.0, "manual", "run")
    assert dl.get_tree()[0]["count"] == 1
    dl.set_status([e.id], "archived")
    assert dl.get_tree()[0]["count"] == 0


def test_tree_count_multi_parent_counts_entry_under_each_parent(dl):
    """多父 DAG：同一 active 条目挂在两个父下，两边 count 都含它。"""
    e = make_entry()
    dl.upsert_entries([e])
    x = dl.create_category("X", [], "manual")
    y = dl.create_category("Y", [], "manual")
    dl.attach_category(e.id, x.id, 1.0, "manual", "run")
    dl.attach_category(e.id, y.id, 1.0, "manual", "run")
    tree = {n["name"]: n for n in dl.get_tree()}
    assert tree["X"]["count"] == 1 and tree["Y"]["count"] == 1


# ---- get_tree 的 count（子树 active 条目数；UI 默认隐藏空枝的依据） ----

def test_tree_count_reflects_subtree_active(dl):
    """A（1 active 直挂）→ B（1 active + 1 archived 直挂）：A.count=2, B.count=1。"""
    e_a = make_entry(source_key="https://e.com/ra", locator="https://e.com/ra")
    e_b1 = make_entry(source_key="https://e.com/b1", locator="https://e.com/b1")
    e_b2 = make_entry(source_key="https://e.com/b2", locator="https://e.com/b2")
    dl.upsert_entries([e_a, e_b1, e_b2])
    a = dl.create_category("A", [], "manual")
    b = dl.create_category("B", [a.id], "manual")
    dl.attach_category(e_a.id, a.id, 1.0, "manual", "run")
    dl.attach_category(e_b1.id, b.id, 1.0, "manual", "run")
    dl.attach_category(e_b2.id, b.id, 1.0, "manual", "run")
    dl.set_status([e_b2.id], "rejected")  # 舍弃的不计数
    tree = {n["name"]: n for n in dl.get_tree()}
    assert tree["A"]["count"] == 2
    assert tree["A"]["children"][0]["count"] == 1


def test_tree_count_zero_for_emptied_category(dl):
    """条目被全部舍弃/归档后 count=0（节点仍在，UI 默认隐藏、勾选可见）。"""
    e = make_entry()
    dl.upsert_entries([e])
    a = dl.create_category("A", [], "manual")
    dl.attach_category(e.id, a.id, 1.0, "manual", "run")
    assert dl.get_tree()[0]["count"] == 1
    dl.set_status([e.id], "archived")
    assert dl.get_tree()[0]["count"] == 0


def test_tree_count_multi_parent_counts_entry_under_each_parent(dl):
    """多父 DAG：同一 active 条目挂在两个父下，两边 count 都含它。"""
    e = make_entry()
    dl.upsert_entries([e])
    x = dl.create_category("X", [], "manual")
    y = dl.create_category("Y", [], "manual")
    dl.attach_category(e.id, x.id, 1.0, "manual", "run")
    dl.attach_category(e.id, y.id, 1.0, "manual", "run")
    tree = {n["name"]: n for n in dl.get_tree()}
    assert tree["X"]["count"] == 1 and tree["Y"]["count"] == 1
