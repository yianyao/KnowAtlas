"""KPE 长文抽取产物 → 点层（变更工单-2026-10-25-KPE导入适配器）。

工具 `tools/kpe`（独立可安装包）产出 `<out>/manifest.json` + `<out>/points.jsonl`；
本模块负责把它并进 KnowAtlas 点层，替代原来的 `temp/kpe_import.py` 一次性脚本。

纪律与边界：
- **不 import tools/kpe**：只按文件格式读 JSON/JSONL（stdlib）——KnowAtlas 保持可分发，
  与抽取工具解耦；换任何抽取器，只要产物同格式即可复用本模块。
- **一册一条目**：一个 out 目录对应一个条目；定位优先级
  `--entry` > `--match`（通配，必须唯一命中） > `manifest.book` 与条目标题精确相等。
- **幂等**：同（点 hash，条目）已有溯源即跳过；重复跑不产生重复点。
- **前置节点丢弃**：目录/前言/序/致谢/关于作者/Contents…（与 KPE 试跑脚本同名单）。
- **--replace**：先 `purge_entry_points`（只清该条目溯源与孤儿点；一点多溯源时仍被
  别处引用的点保留），再导入新点。
- **写库前快照**：默认 `snapshot(force=True)`（--dry-run / --no-backup 除外）。
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from ..errors import ContractError
from ..models import Entry
from .backup import snapshot
from .points import normalize_point_text, point_hash

# 前置章节：这些 section_path 首段下的点不进点层（不是知识，是书的门面）。
FRONT_SECTIONS = frozenset({
    "目录", "前言", "序言", "序", "引言", "致谢", "关于作者", "关于本书",
    "免责声明", "版权信息", "出版信息", "Contents 免责声明",
})
_ANCHOR_LEN = 40   # 无 quote 时用 text 前 N 字在正文里定位
_SCAN_LIMIT = 50000  # 标题扫描上限（条目量级远小于此；防全表无界）


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


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


def is_front_point(point: dict[str, Any]) -> bool:
    """首段即前置章节（含 Contents 前缀）的点 → 丢。"""
    first = str(point.get("section_path") or "").split(" > ")[0].strip()
    return first in FRONT_SECTIONS or first.startswith("Contents")


def _offset_of(quote: str, text: str, body: str) -> int | None:
    """在条目正文里定位 quote（缺则 text 前 N 字），找不到返回 None。"""
    if not body:
        return None
    if quote:
        idx = body.find(quote)
        if idx >= 0:
            return idx
    idx = body.find(text[:_ANCHOR_LEN])
    return idx if idx >= 0 else None


def _hit(entry: Entry, needle: str) -> bool:
    title = (entry.title or "").lower()
    locator = (entry.locator or "").lower()
    if "*" in needle or "?" in needle:
        return (fnmatch.fnmatchcase(title, needle)
                or fnmatch.fnmatchcase(locator, needle))
    return needle in title or needle in locator


def resolve_entry(dl: Any, manifest_book: str, entry_id: str | None,
                  match: str | None) -> Entry:
    """定位目标条目；0 命中或多命中都抛 ContractError 并列候选（不猜）。"""
    if entry_id:
        entry = dl.get_entry(str(entry_id).strip())
        if entry is None:
            raise ContractError(
                f"条目不存在：{entry_id}",
                hint="先 ksync/kadd 建条目，或用 --match 按标题检索")
        return entry

    if match:
        needle = match.strip().lower()
        hits = [e for e in dl.list_entries(status="active", limit=_SCAN_LIMIT)
                if _hit(e, needle)]
        if not hits:
            raise ContractError(
                f"--match {match!r} 没有命中任何活动条目",
                hint="放宽通配、或改用 --entry 指定条目 id")
        if len(hits) > 1:
            preview = "；".join(f"{e.id}={e.title}" for e in hits[:10])
            raise ContractError(
                f"--match {match!r} 命中 {len(hits)} 个条目，拒绝猜测",
                hint=f"用 --entry 精确指定。候选：{preview}")
        return hits[0]

    book = str(manifest_book or "").strip()
    if not book:
        raise ContractError(
            "manifest 缺 book 字段，且未给 --entry / --match",
            hint="用 --entry <条目id> 显式指定目标条目")
    hits = [e for e in dl.list_entries(status="active", limit=_SCAN_LIMIT)
            if (e.title or "").strip() == book]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ContractError(
            f"没有标题恰好等于 {book!r} 的活动条目",
            hint="用 --match 模糊匹配，或 --entry 精确指定条目 id")
    preview = "；".join(f"{e.id}={e.title}" for e in hits[:10])
    raise ContractError(
        f"标题 {book!r} 命中 {len(hits)} 个条目，拒绝猜测",
        hint=f"用 --entry 精确指定。候选：{preview}")


def import_kpe_dir(cfg: Any, dl: Any, out_dir: str | Path, *,
                   entry_id: str | None = None, match: str | None = None,
                   replace: bool = False, dry_run: bool = False,
                   backup: bool = True, limit: int = 0) -> dict[str, Any]:
    """把一个 kpe 产物目录导入其对应条目；返回统计 dict（不抛业务异常）。"""
    out = Path(out_dir)
    manifest = _read_json(out / "manifest.json")
    if not isinstance(manifest, dict):
        raise ContractError(
            f"找不到或无法解析 {out / 'manifest.json'}",
            hint="确认这是 kpe --out 目录，且已跑过 kpe chunks")
    points = _read_jsonl(out / "points.jsonl")
    if limit > 0:
        points = points[:limit]

    entry = resolve_entry(dl, str(manifest.get("book") or ""), entry_id, match)
    # 与 points._entry_body 同口径：inline_content 优先，缺了从 content_store 取
    body = ((entry.inline_content or "").strip()
            or (dl.get_content(entry.content_hash or "") or "").strip())

    stats: dict[str, Any] = {
        "out": str(out), "entry": entry.id, "title": entry.title,
        "book": manifest.get("book") or "", "points_in": len(points),
        "dropped_front": 0, "empty": 0, "skipped": 0, "created": 0,
        "linked": 0, "offset_ok": 0, "replace": bool(replace),
        "dry_run": bool(dry_run),
    }

    if backup and not dry_run:
        stats["backup"] = snapshot(cfg, dl, force=True)
    if replace and not dry_run:
        stats["purged_sources"] = dl.purge_entry_points(
            entry.id, reason="kpe_replace", task_name="kpeimport")

    existing = {str(p.get("content_hash") or "")
                for p in dl.points_of_entries([entry.id]).get(entry.id, [])}
    if dry_run:
        # 试算要区分 created/linked，需要知道全库已有点 id（id = content_hash[:16]）
        existing_all = set(dl.all_points_text())

    for point in points:
        if is_front_point(point):
            stats["dropped_front"] += 1
            continue
        text = normalize_point_text(str(point.get("text") or ""))
        if not text:
            stats["empty"] += 1
            continue
        ph = point_hash(text)
        if ph in existing:
            stats["skipped"] += 1
            continue
        quote = str(point.get("quote") or "").strip()
        offset = _offset_of(quote, text, body)
        if offset is not None:
            stats["offset_ok"] += 1
        if dry_run:
            stats["created" if ph[:16] not in existing_all else "linked"] += 1
            continue
        status = dl.put_point(
            {
                "content_hash": ph, "text": text, "summary": "",
                "source_type": entry.source_type, "judge": "split",
                "meta": {
                    "judge_reason": "kpe 长文分块抽取（自洽点）",
                    "extractor": "kpe",
                    "book": stats["book"],
                    "section_path": str(point.get("section_path") or ""),
                    "page_start": point.get("page_start"),
                    "page_end": point.get("page_end"),
                    "quote": quote,
                    "model": str(point.get("model") or ""),
                },
            },
            {"entry_id": entry.id, "char_offset": offset,
             "anchor": (quote or text)[:120]},
        )
        stats[status] += 1
        existing.add(ph)

    return stats