"""跨源去重测试（0.2.0 第三十八批）：canonical/hash 确定性判据 + 只标不删合并模型。"""

from __future__ import annotations

from knowatlas.ids import content_hash
from knowatlas.models import Entry, FetchResult
from knowatlas.pipeline.dedupe import (
    dedupe_entries, find_master, merge_into, scan_and_merge,
)


def make_entry(**overrides) -> Entry:
    defaults = dict(
        source_type="manual", source_key="https://e.com/a",
        title="示例标题", locator="https://e.com/a",
        locator_canonical="https://e.com/a",
        meta={"source_type": "manual"},
    )
    defaults.update(overrides)
    return Entry.build(**defaults)


def _merge_pair(dl, a: Entry, b: Entry):
    """入库两条并跑判重，返回 (merged 数, 库中 a, 库中 b)。"""
    dl.upsert_entries([a, b])
    merged = dedupe_entries(dl, [a, b])
    return merged, dl.get_entry(a.id), dl.get_entry(b.id)


# ---- canonical 命中：书签+manual 同 URL 合并为一条 ----

def test_canonical_hit_merges_and_keeps_both_locators(dl):
    a = make_entry(source_key="chrome:1", source_type="bookmark",
                   meta={"source_type": "bookmark"},
                   created_at="2026-01-01T00:00:00+08:00")
    b = make_entry(source_key="manual:abc", locator="https://e.com/a?utm_source=x",
                   locator_canonical="https://e.com/a", title="同一篇（manual）")
    merged, ea, eb = _merge_pair(dl, a, b)
    assert merged == 1
    # 主条目 = created_at 更早的书签条目；双 locator 均可反查到主条目
    assert eb.meta["dedupe_master"] == ea.id
    assert eb.meta["dedupe_reason"] == "canonical_hit"
    assert [x.id for x in dl.find_by_locator("https://e.com/a")] == [ea.id]
    assert ea.id in [x.id for x in dl.find_by_locator("https://e.com/a?utm_source=x")]
    # 副条目 locator 已附挂到主条目
    assert dl.find_by_canonical("https://e.com/a").id == ea.id


# ---- content_hash 命中：同正文不同 URL 合并 ----

def test_content_hash_hit_merges(dl):
    text = "同一份文档正文，拷贝到两个目录。" * 20
    h = content_hash(text)
    dl.put_content(FetchResult(text=text, content_hash=h,
                               fetcher="test", fetched_at="2026-10-20T00:00:00"))
    a = make_entry(source_key="docs/a.md", source_type="folder",
                   locator="file://docs/a.md", locator_canonical=None,
                   content_hash=h, meta={"source_type": "folder"},
                   created_at="2026-01-01T00:00:00+08:00")
    b = make_entry(source_key="backup/b.md", source_type="folder",
                   title="备份拷贝", locator="file://backup/b.md",
                   locator_canonical=None, content_hash=h,
                   meta={"source_type": "folder"},
                   created_at="2026-02-01T00:00:00+08:00")
    merged, ea, eb = _merge_pair(dl, a, b)
    assert merged == 1
    assert eb.meta["dedupe_master"] == ea.id
    assert eb.meta["dedupe_reason"] == "content_hit"
    assert dl.find_by_locator("file://backup/b.md")[0].id == ea.id  # 可跳转


# ---- 消费面守卫：副条目从消费读路径消失 ----

def test_merged_duplicate_hidden_from_consumption(dl):
    text = "消费面守卫探针正文" * 10
    h = content_hash(text)
    dl.put_content(FetchResult(text=text, content_hash=h,
                               fetcher="test", fetched_at="2026-10-20T00:00:00"))
    a = make_entry(source_key="keep", created_at="2026-01-01T00:00:00+08:00",
                   content_hash=h)
    b = make_entry(source_key="dup", title="重复条目", content_hash=h,
                   locator_canonical=None)
    dl.upsert_entries([a, b])
    cat = dl.create_category("测试类", [], "manual")
    dl.attach_category(a.id, cat.id, 1.0, "manual", "run0000000000001")
    dl.attach_category(b.id, cat.id, 1.0, "manual", "run0000000000002")
    dedupe_entries(dl, [a, b])

    assert [x.entry_id for x in dl.search_fts("探针")] == [a.id]  # 检索只见主
    g = dl.get_graph_subtree(cat.id)
    assert f"e:{b.id}" not in [n["id"] for n in g["nodes"]]      # 图/树不见副
    assert dl._consumable_count([cat.id]) == 1                   # 树计数只算主
    r = dl.radiate(f"e:{a.id}")
    assert f"e:{b.id}" not in [n["id"] for n in r["nodes"]]      # 放射不见副


# ---- 幂等：重复 sync 不重复计数、不重复附挂、标不被源 meta 抹掉 ----

def test_dedupe_idempotent_and_mark_survives_resync(dl):
    a = make_entry(source_key="keep", created_at="2026-01-01T00:00:00+08:00")
    b = make_entry(source_key="dup", title="重复条目")
    dl.upsert_entries([a, b])
    assert dedupe_entries(dl, [a, b]) == 1
    assert dedupe_entries(dl, [a, b]) == 0          # 再跑：已带标，不重复计数
    dup = dl.get_entry(b.id)
    assert dup.meta["dedupe_master"] == a.id
    # 源重推（meta 不含 dedupe 键）→ 合并语义保标不抹
    dl.upsert_entries([b])
    assert dl.get_entry(b.id).meta["dedupe_master"] == a.id


# ---- 死标摘除：主条目失效后副条目回归 ----

def test_dead_mark_cleared_when_master_rejected(dl):
    a = make_entry(source_key="keep", created_at="2026-01-01T00:00:00+08:00")
    b = make_entry(source_key="dup", title="重复条目")
    dl.upsert_entries([a, b])
    dedupe_entries(dl, [a, b])
    dl.set_status([a.id], "rejected")               # 主条目被舍弃
    stats = scan_and_merge(dl, dry_run=True)
    assert stats["dead_marks_cleared"] == 0         # dry_run 零写入
    assert dl.get_entry(b.id).meta.get("dedupe_master") == a.id
    stats = scan_and_merge(dl)
    assert stats["dead_marks_cleared"] == 1
    assert not dl.get_entry(b.id).meta.get("dedupe_master")  # 回归消费面


# ---- scan_and_merge：存量分组、dry_run 零写入、双命中只并一次 ----

def test_scan_and_merge_groups_and_dry_run(dl):
    text = "存量扫描探针正文" * 10
    h = content_hash(text)
    dl.put_content(FetchResult(text=text, content_hash=h,
                               fetcher="test", fetched_at="2026-10-20T00:00:00"))
    a = make_entry(source_key="s1", created_at="2026-01-01T00:00:00+08:00",
                   content_hash=h)
    b = make_entry(source_key="s2", title="拷贝一", locator="https://e.com/copy1",
                   locator_canonical="https://e.com/copy1", content_hash=h)
    c = make_entry(source_key="s3", title="拷贝二", locator="https://e.com/copy2",
                   locator_canonical="https://e.com/copy2", content_hash=h)
    dl.upsert_entries([a, b, c])
    stats = scan_and_merge(dl, dry_run=True)
    assert stats["groups"] == {"content_hit": 1} and stats["merged"] == 0
    assert dl.get_entry(b.id).meta.get("dedupe_master") is None   # dry_run 零写入
    stats = scan_and_merge(dl)
    assert stats["merged"] == 2                                   # b、c 都并进 a
    assert dl.get_entry(b.id).meta["dedupe_master"] == a.id
    assert dl.get_entry(c.id).meta["dedupe_master"] == a.id


def test_find_master_prefers_canonical_over_hash(dl):
    """canonical 与 hash 双命中时 canonical 优先（同 URL 是最强同知识信号）。"""
    text = "双命中探针正文" * 10
    h = content_hash(text)
    a = make_entry(source_key="m1", created_at="2026-01-01T00:00:00+08:00")
    b = make_entry(source_key="m2", title="另一条", created_at="2026-03-01T00:00:00+08:00",
                   content_hash=h)
    dl.upsert_entries([a, b])
    probe = make_entry(source_key="probe", title="探针",
                       locator="https://e.com/a?x=1", content_hash=h)
    dl.upsert_entries([probe])
    master, reason = find_master(dl, dl.get_entry(probe.id))
    assert reason == "canonical_hit" and master.id == a.id
