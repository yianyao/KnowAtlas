"""超大书分卷装箱（工单 2026-10-29《超大书分卷摄取》C1）。

一句话：一本书的 chunks 一次切好，按「章 + 字符上限」装箱成 `v001..` 多卷，逐卷抽取、
逐卷导入；**卷是 chunks 列表的连续区间**——不重排、不丢块、不并块。

边界（沿用 `kpe_import` / `kpe_runner` 的纪律）：
- 不 import `tools/kpe`：只按 JSON / JSONL 文件格式读写（KnowAtlas 保持可独立分发）；
- 不碰数据库：卷目录只是缓存，写库仍由 `kpe_import.import_kpe_dir` 负责；
- 装箱是**纯函数**（同一 chunks + 同一上限 → 同一卷划分），断点续跑才可靠：
  卷内靠 KPE 自己的 `done.jsonl` / `cache/`，卷间靠 `volume_complete()` 跳过。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

VOLUME_DIR_PREFIX = "v"
VOLUME_INDEX_NAME = "volumes.json"
#: 章边界切卷的「已装满」比例：没装到 75% 上限就继续装下一章，避免碎卷。
MIN_FILL_RATIO = 0.75


def chapter_of(section_path: str) -> str:
    """章 = section_path 的第一段（`A > B > C` → `A`）；空路径 → 空串。"""
    return str(section_path or "").split(" > ")[0].strip()


def total_chars(chunks: Iterable[dict[str, Any]]) -> int:
    """整本 chunks 的实际字符数（上限判定用它，不用正文字数）。"""
    return sum(_chars(c) for c in chunks)


def _chars(chunk: dict[str, Any]) -> int:
    """块字符数：KPE 的 chunks.jsonl 带 `chars`；缺了就按 text 长度算。"""
    n = chunk.get("chars")
    if n is None:
        n = len(str(chunk.get("text") or ""))
    return int(n)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="\n")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path.write_text(text, encoding="utf-8", newline="\n")


@dataclass(frozen=True)
class Volume:
    """一卷 = chunks.jsonl 里一段连续区间。"""

    index: int                       # 1 起
    chunks: tuple[dict[str, Any], ...]
    chars: int
    head: str                        # 首块 section_path 的章名（日志/审计用）

    @property
    def dirname(self) -> str:
        return f"{VOLUME_DIR_PREFIX}{self.index:03d}"

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        return tuple(str(c.get("id") or "") for c in self.chunks)

    def summary(self) -> dict[str, Any]:
        idx = [int(c.get("index") or 0) for c in self.chunks]
        return {"volume": self.index, "dir": self.dirname,
                "chunks": len(self.chunks), "chars": self.chars, "head": self.head,
                "first_index": min(idx) if idx else 0,
                "last_index": max(idx) if idx else 0}


def pack_volumes(chunks: Iterable[dict[str, Any]], max_chars: int, *,
                 min_fill: float = MIN_FILL_RATIO) -> list[Volume]:
    """把整本 chunks 装箱成 ≤ `max_chars` 的多卷（保持原顺序）。

    切割规则（确定性）：
    1. `当前卷字符 + 本块 > max_chars` → 必须切；
    2. 章变了且当前卷已装上 `min_fill` 比例 → 优先在章边界切；
    3. 单块本身超过上限 → 独占一卷（不丢块；KPE 的块受 `--max-chars` 约束，正常到不了）。
    """
    if int(max_chars) <= 0:
        raise ValueError(f"max_chars 必须为正：{max_chars}")
    if not 0 <= float(min_fill) <= 1:
        raise ValueError(f"min_fill 必须在 0..1：{min_fill}")

    rows = list(chunks)
    volumes: list[Volume] = []
    cur: list[dict[str, Any]] = []
    cur_chars = 0
    last_chapter = ""
    threshold = int(max_chars) * float(min_fill)

    def close() -> None:
        nonlocal cur, cur_chars
        if cur:
            volumes.append(Volume(len(volumes) + 1, tuple(cur), cur_chars,
                                  chapter_of(str(cur[0].get("section_path") or ""))))
        cur, cur_chars = [], 0

    for chunk in rows:
        n = _chars(chunk)
        chapter = chapter_of(str(chunk.get("section_path") or ""))
        if cur and (cur_chars + n > max_chars
                    or (chapter != last_chapter and cur_chars >= threshold)):
            close()
        cur.append(chunk)
        cur_chars += n
        last_chapter = chapter
    close()
    return volumes


def write_volumes(parent: Path, manifest: dict[str, Any], volumes: list[Volume], *,
                  book: str, max_chars: int) -> list[Path]:
    """把每卷写成 `<parent>/vNNN/{manifest.json,chunks.jsonl}` + 卷索引；返回卷目录。

    幂等：同名卷重写同样的内容（KPE 的 done/cache 留在卷目录里，不受影响）。
    每卷 manifest 的 `book` 改写为条目标题 —— 导入时进 `meta.book`，不是「卷名」。
    """
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    dirs: list[Path] = []
    for vol in volumes:
        vdir = parent / vol.dirname
        vdir.mkdir(parents=True, exist_ok=True)
        vol_manifest = {**manifest, "book": str(book),
                        "volume": vol.index, "volumes": len(volumes),
                        "volume_chars": vol.chars,
                        "chunk_count": len(vol.chunks),
                        "chunks_chars": vol.chars}
        _write_json(vdir / "manifest.json", vol_manifest)
        _write_jsonl(vdir / "chunks.jsonl", vol.chunks)
        dirs.append(vdir)
    _write_json(parent / VOLUME_INDEX_NAME, {
        "schema": 1, "book": str(book), "max_chars": int(max_chars),
        "chunk_total": sum(v.chars for v in volumes),
        "volumes": [v.summary() for v in volumes],
        "created_at": _now(),
    })
    return dirs


def volume_complete(out_dir: Path, chunk_ids: Iterable[str]) -> bool:
    """该卷所有块都进了 done.jsonl → 已完成（不需要 LLM key 也能收尾导入）。"""
    wanted = {str(i) for i in chunk_ids if i}
    if not wanted:
        return False
    done = {str(r.get("chunk_id") or "")
            for r in _read_jsonl(Path(out_dir) / "done.jsonl")}
    return wanted <= done


def volume_stats(out_dir: Path) -> dict[str, Any]:
    """卷目录现场：块数 / 已完成块数 / 已产点数 / 是否完成 / 字符数。"""
    out = Path(out_dir)
    chunks = _read_jsonl(out / "chunks.jsonl")
    ids = {str(c.get("id") or "") for c in chunks} - {""}
    done = {str(r.get("chunk_id") or "")
            for r in _read_jsonl(out / "done.jsonl")}
    points = _read_jsonl(out / "points.jsonl")
    return {"chunks": len(chunks), "done": len(ids & done),
            "points": len(points), "chars": total_chars(chunks),
            "complete": bool(ids) and ids <= done}


__all__ = ["MIN_FILL_RATIO", "VOLUME_INDEX_NAME", "Volume", "chapter_of",
           "pack_volumes", "total_chars", "volume_complete", "volume_stats",
           "write_volumes"]