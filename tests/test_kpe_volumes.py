"""分卷装箱（C1）纯函数与卷目录读写：零网络、零 LLM、零数据库。

判据（工单 2026-10-29《超大书分卷摄取》§4）：
- 卷是 chunks 的**连续区间**：不丢块、不重复、保持顺序，`Σ卷.chars == Σ块.chars`；
- 每卷 ≤ 上限，除非单块本身就超限（独占一卷，不丢）；
- 章边界优先（装满 `min_fill` 才切），同一章超限时按块切；
- 卷目录可被 KPE 直接 `extract`：manifest 的 `book` = 条目标题，块 id 沿用整本。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowatlas.pipeline.kpe_volumes import (
    MIN_FILL_RATIO, Volume, chapter_of, pack_volumes, total_chars,
    volume_complete, volume_stats, write_volumes)


def _chunk(i: int, chars: int = 1000, chapter: str = "第一章") -> dict:
    return {"index": i, "id": f"c{i:03d}", "section_path": f"{chapter} > {i}.1",
            "page_start": 0, "page_end": 0, "chars": chars, "text": "x" * chars}


def _flatten(vols: list[Volume]) -> list[str]:
    return [c["id"] for v in vols for c in v.chunks]


def test_pack_respects_cap_and_keeps_every_chunk():
    chunks = [_chunk(i, 1500, chapter=f"第{i // 3}章") for i in range(1, 11)]
    vols = pack_volumes(chunks, 6000)
    assert len(vols) >= 3
    assert [v.index for v in vols] == list(range(1, len(vols) + 1))
    assert all(v.chars <= 6000 for v in vols)
    assert total_chars(chunks) == sum(v.chars for v in vols)
    assert _flatten(vols) == [c["id"] for c in chunks]        # 顺序不变、无丢无重
    assert [v.dirname for v in vols][:2] == ["v001", "v002"]


def test_pack_prefers_chapter_boundary_after_min_fill():
    """A(3k)+B(5k)=8k ≥ 75% 上限，C 起头 → 在 B/C 之间切，不跨章硬塞到 10k。"""
    chunks = ([_chunk(i, 1000, "A 章") for i in range(1, 4)]
              + [_chunk(i, 1000, "B 章") for i in range(4, 9)]
              + [_chunk(i, 1000, "C 章") for i in range(9, 11)])
    vols = pack_volumes(chunks, 10000, min_fill=0.75)
    assert len(vols) == 2
    assert [chapter_of(v.head) for v in vols] == ["A 章", "C 章"]
    assert [len(v.chunks) for v in vols] == [8, 2]
    assert vols[0].chars == 8000 and vols[1].chars == 2000


def test_pack_does_not_split_small_chapter_early():
    """没装满 min_fill 就不切：A(1k) + B(1k) 必须同卷（cap 10k）。"""
    chunks = [_chunk(1, 1000, "A"), _chunk(2, 1000, "B"),
              _chunk(3, 1000, "C"), _chunk(4, 1000, "D")]
    vols = pack_volumes(chunks, 10000, min_fill=0.75)
    assert len(vols) == 1 and vols[0].chars == 4000


def test_pack_splits_oversized_chapter_by_cap():
    chunks = [_chunk(i, 1000, "大章") for i in range(1, 13)]     # 单章 12k > cap 5k
    vols = pack_volumes(chunks, 5000)
    assert [len(v.chunks) for v in vols] == [5, 5, 2]
    assert all(v.chars <= 5000 for v in vols)
    assert {v.head for v in vols} == {"大章"}


def test_single_chunk_over_cap_gets_own_volume():
    chunks = [_chunk(1, 9000), _chunk(2, 1000), _chunk(3, 1000)]
    vols = pack_volumes(chunks, 5000)
    assert [len(v.chunks) for v in vols] == [1, 2]
    assert vols[0].chars == 9000                    # 单块超限：独占一卷，不丢
    assert _flatten(vols) == ["c001", "c002", "c003"]


def test_pack_uses_text_len_when_chars_missing():
    chunks = [{"index": 1, "id": "a", "section_path": "A", "text": "12345"},
              {"index": 2, "id": "b", "section_path": "A", "text": "67890"}]
    assert total_chars(chunks) == 10
    vols = pack_volumes(chunks, 5)
    assert [len(v.chunks) for v in vols] == [1, 1]


def test_pack_empty_and_invalid_arguments():
    assert pack_volumes([], 600000) == []
    with pytest.raises(ValueError):
        pack_volumes([_chunk(1)], 0)
    with pytest.raises(ValueError):
        pack_volumes([_chunk(1)], 1000, min_fill=1.5)


def test_chapter_of_takes_first_segment():
    assert chapter_of("A > B > C") == "A"
    assert chapter_of("A") == "A"
    assert chapter_of("") == ""
    assert chapter_of(None) == ""


def test_write_volumes_layout_and_index(tmp_path: Path):
    parent = tmp_path / "kpe" / "e1"
    chunks = [_chunk(i, 3000, chapter=f"第{i}章") for i in range(1, 5)]
    vols = pack_volumes(chunks, 6000)
    manifest = {"book": "整本", "source": "C:/x/big.pdf",
                "params": {"target_chars": 6000, "max_chars": 8000},
                "chunk_count": 4}
    dirs = write_volumes(parent, manifest, vols, book="真正的书名", max_chars=6000)
    assert [d.name for d in dirs] == [v.dirname for v in vols]
    vol_manifest = json.loads((dirs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert vol_manifest["book"] == "真正的书名"       # 进 meta.book，不是「卷名」
    assert vol_manifest["volume"] == 1 and vol_manifest["volumes"] == len(vols)
    assert vol_manifest["chunk_count"] == len(vols[0].chunks)
    rows = [json.loads(x) for x in
            (dirs[0] / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in rows] == list(vols[0].chunk_ids)

    index = json.loads((parent / "volumes.json").read_text(encoding="utf-8"))
    assert index["schema"] == 1 and index["max_chars"] == 6000
    assert index["chunk_total"] == 12000
    assert [v["dir"] for v in index["volumes"]] == [v.dirname for v in vols]

    # 幂等重写：内容一致（KPE 的 done/cache 留在卷目录里，不受影响）
    before = (dirs[0] / "chunks.jsonl").read_text(encoding="utf-8")
    write_volumes(parent, manifest, vols, book="真正的书名", max_chars=6000)
    assert (dirs[0] / "chunks.jsonl").read_text(encoding="utf-8") == before


def test_volume_complete_and_stats(tmp_path: Path):
    vdir = tmp_path / "v001"
    vdir.mkdir()
    rows = [_chunk(1), _chunk(2)]
    (vdir / "chunks.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert volume_stats(vdir) == {"chunks": 2, "done": 0, "points": 0,
                                  "chars": 2000, "complete": False}
    assert volume_complete(vdir, ["c001", "c002"]) is False          # 没有 done.jsonl

    (vdir / "done.jsonl").write_text('{"chunk_id": "c001"}\n', encoding="utf-8")
    (vdir / "points.jsonl").write_text('{"text": "点1"}\n', encoding="utf-8")
    assert volume_complete(vdir, ["c001"]) is True                  # 子集也算完成
    assert volume_complete(vdir, ["c001", "c002"]) is False
    assert volume_stats(vdir)["done"] == 1 and volume_stats(vdir)["points"] == 1

    (vdir / "done.jsonl").write_text(
        '{"chunk_id": "c001"}\n{"chunk_id": "c002"}\n', encoding="utf-8")
    assert volume_complete(vdir, ["c001", "c002"]) is True
    assert volume_stats(vdir)["complete"] is True
    assert volume_complete(tmp_path / "missing", ["c001"]) is False
    assert volume_complete(vdir, []) is False                        # 空要求不算完成


def test_min_fill_ratio_is_documented_default():
    assert 0 < MIN_FILL_RATIO <= 1