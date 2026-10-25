"""KPE 产物导入测试（变更工单-2026-10-25-KPE导入适配器）。

覆盖：按 manifest.book 精确匹配、--match 多命中拒绝、前置节点丢弃、
quote 回填 char_offset、幂等重跑、--replace 清旧点（共享点保留）、--dry-run 不写库。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from knowatlas.errors import ContractError
from knowatlas.models import Entry, FetchResult
from knowatlas.pipeline.kpe_import import import_kpe_dir, is_front_point
from knowatlas.pipeline.points import point_hash


def _seed_entry(dl, title: str, body: str = "正文包含引文锚点：EXPLAIN QUERY PLAN 看计划。"):
    batch = uuid.uuid4().hex[:6]
    chash = f"kpe-{batch}"
    entry = Entry.build(
        source_type="folder", source_key=f"kpe:{batch}", title=title,
        locator=f"file:///tmp/{batch}.md", content_hash=chash,
        meta={"source_type": "folder"},
    )
    dl.upsert_entries([entry])
    dl.put_content(FetchResult(text=body, content_hash=chash,
                               fetcher="test", fetched_at="2026-10-25T00:00:00+08:00"))
    return entry


def _write_kpe_dir(root: Path, book: str, points: list[dict]) -> Path:
    out = root / "kpe-out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps({"book": book, "chunks": len(points)}, ensure_ascii=False),
        encoding="utf-8", newline="\n")
    (out / "points.jsonl").write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in points),
        encoding="utf-8", newline="\n")
    return out


_SAMPLE = [
    {"text": "目录与前言不是知识。", "quote": "", "section_path": "目录 > 1"},
    {"text": "SQLite 慢查询先用 EXPLAIN QUERY PLAN 看执行计划。",
     "quote": "EXPLAIN QUERY PLAN 看计划", "section_path": "第 1 章 > 1.1"},
    {"text": "WAL 模式提升并发读。", "quote": "不存在的引文",
     "section_path": "第 1 章 > 1.2"},
]


def test_is_front_point():
    assert is_front_point({"section_path": "前言 > 1"})
    assert is_front_point({"section_path": "关于本书 > 1"})
    assert is_front_point({"section_path": "Contents 免责声明 > x"})
    assert not is_front_point({"section_path": "第 1 章 > 1.1"})


def test_import_by_book_title_and_backfill_offset(cfg, dl, tmp_path):
    entry = _seed_entry(dl, "1.AI智能体的崛起")
    out = _write_kpe_dir(tmp_path, "1.AI智能体的崛起", _SAMPLE)

    stats = import_kpe_dir(cfg, dl, out, backup=False)

    assert stats["entry"] == entry.id
    assert stats["dropped_front"] == 1
    assert stats["created"] == 2
    assert stats["offset_ok"] == 1          # 只有第 2 条 quote 能在正文里定位
    pts = dl.points_of_entries([entry.id])[entry.id]
    assert {p["judge"] for p in pts} == {"split"}
    assert all(p["content_hash"] == point_hash(p["text"]) for p in pts)


def test_rerun_is_idempotent(cfg, dl, tmp_path):
    entry = _seed_entry(dl, "书A")
    out = _write_kpe_dir(tmp_path, "书A", _SAMPLE)
    import_kpe_dir(cfg, dl, out, backup=False)
    again = import_kpe_dir(cfg, dl, out, backup=False)

    assert again["created"] == 0
    assert again["skipped"] == 2
    assert len(dl.points_of_entries([entry.id])[entry.id]) == 2


def test_replace_purges_old_points_but_keeps_shared(cfg, dl, tmp_path):
    entry = _seed_entry(dl, "书B")
    other = _seed_entry(dl, "书B-同名共享点")
    old_text = "旧点：整篇照抄。"
    dl.put_point({"content_hash": point_hash(old_text), "text": old_text,
                  "summary": "", "source_type": "folder", "judge": "integral",
                  "meta": {}},
                 {"entry_id": entry.id, "char_offset": 0, "anchor": old_text})
    shared_text = "共享点：两个条目都引用。"
    for eid in (entry.id, other.id):
        dl.put_point({"content_hash": point_hash(shared_text), "text": shared_text,
                      "summary": "", "source_type": "folder", "judge": "integral",
                      "meta": {}},
                     {"entry_id": eid, "char_offset": 0, "anchor": shared_text})

    out = _write_kpe_dir(tmp_path, "书B", _SAMPLE)
    stats = import_kpe_dir(cfg, dl, out, replace=True, backup=False)

    assert stats["purged_sources"] == 2
    texts = {p["content_hash"] for p in dl.points_of_entries([entry.id])[entry.id]}
    assert point_hash(old_text) not in texts          # 孤儿点被删
    assert len(texts) == 2                            # 该条目只剩新导入的两点
    # 共享点：本条目溯源已清，但 other 仍引用 → 点本身保留（一点多溯源不连坐）
    assert point_hash(shared_text) in {
        p["content_hash"] for p in dl.points_of_entries([other.id])[other.id]}


def test_match_must_be_unique(cfg, dl, tmp_path):
    _seed_entry(dl, "重复标题")
    _seed_entry(dl, "重复标题")
    out = _write_kpe_dir(tmp_path, "重复标题", _SAMPLE)
    with pytest.raises(ContractError):
        import_kpe_dir(cfg, dl, out, match="重复标题", backup=False)


def test_dry_run_writes_nothing(cfg, dl, tmp_path):
    entry = _seed_entry(dl, "书C")
    out = _write_kpe_dir(tmp_path, "书C", _SAMPLE)
    stats = import_kpe_dir(cfg, dl, out, dry_run=True, backup=False)

    assert stats["created"] == 2
    assert dl.points_of_entries([entry.id])[entry.id] == []