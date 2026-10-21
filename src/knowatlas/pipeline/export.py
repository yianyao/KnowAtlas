"""数据导出（0.2.0 第四十五批，M5）：JSON / Obsidian / OPML 三种格式。

纪律（SOP-E）：导出是数据层的**投影**——不碰原始源、不调 LLM、不联网。

- JSON：schema 版本化全量投影（含 archived/rejected；inline_content 内联，
  content_store 全量正文不内联——百万字符级，用户按需自行拷贝目录）；
- Obsidian：active 条目笔记 + 每分类 MOC 笔记（双链），防锁定出口；
  条目笔记放主分类目录，所有父分类 MOC 都双链它（短链全局解析，多父不丢）；
- OPML：http canonical 条目（书签类）按分类 DAG 展平为 outline 树，
  往返保真（导出文件可被标准 XML 解析重建无损树）；导入回路后置。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

EXPORT_SCHEMA_VERSION = "1.0"

_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_TITLE_MAX = 80


def _safe_name(name: str, taken: set[str], fallback: str) -> str:
    """文件名安全化：去非法字符、截断、重名避撞（保确定性：同库同导出稳定）。"""
    base = _UNSAFE_FILENAME.sub("_", (name or "").strip())[:_TITLE_MAX].strip()
    if not base:
        base = fallback
    candidate = base
    n = 2
    while candidate.lower() in taken:
        candidate = f"{base}-{n}"
        n += 1
    taken.add(candidate.lower())
    return candidate


def _active_entries(dl: Any) -> list[Any]:
    """active 全量（含被守卫条目——防锁定优先；archived/rejected 不导出）。"""
    return dl.list_entries(status="active", limit=1_000_000)


def _all_entries(dl: Any) -> list[Any]:
    from ..models import STATUSES  # noqa: PLC0415 常量导入，避免循环

    out: list[Any] = []
    for s in STATUSES:
        out.extend(dl.list_entries(status=s, limit=1_000_000))
    return out


# ---- JSON 全量导出 ----

def export_json(dl: Any, out: Path) -> dict[str, Any]:
    """schema 版本化全量投影（探针①：schema_version + counts 对账 + 关联完整）。"""
    cats = dl.all_categories_dag()
    entry_cats = dl.all_entry_categories()
    locators = dl.all_entry_locators()
    entries = _all_entries(dl)
    threads = dl.list_threads(limit=10_000)
    thread_items = []
    for t in threads:
        th = dl.get_thread(t["id"])
        if th is None:
            continue
        thread_items.extend(
            {"id": it.id, "thread_id": it.thread_id, "entry_id": it.entry_id,
             "position": it.position, "relation_type": it.relation_type, "note": it.note}
            for it in th.items)
    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generator": "knowatlas-kexport",
        "exported_at": _now_iso(),
        "counts": {"categories": len(cats), "entries": len(entries),
                   "threads": len(threads), "thread_items": len(thread_items)},
        "categories": cats,
        "entries": [
            {"id": e.id, "source_type": e.source_type, "title": e.title,
             "locator": e.locator, "locator_canonical": e.locator_canonical,
             "native_path": e.native_path, "inline_content": e.inline_content,
             "content_hash": e.content_hash, "meta": e.meta,
             "created_at": e.created_at, "exported_at": e.exported_at,
             "status": e.status,
             "locators": locators.get(e.id, []),
             "categories": entry_cats.get(e.id, [])}
            for e in entries],
        "threads": threads,
        "thread_items": thread_items,
    }
    out = Path(out)
    if out.parent != Path(""):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"format": "json", "out": str(out), **payload["counts"],
            "schema_version": EXPORT_SCHEMA_VERSION}


# ---- Obsidian vault 导出 ----

def export_obsidian(dl: Any, out_dir: Path) -> dict[str, Any]:
    """条目笔记 + 分类 MOC（探针②：每分类有 MOC、条目有回链、多父全覆盖）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cats = dl.all_categories_dag()
    cat_by_id = {c["id"]: c for c in cats}
    entry_cats = dl.all_entry_categories()
    entries = _active_entries(dl)

    # MOC 文件名 = 分类名（安全化、全局避撞）；Obsidian 短链按文件名全局解析
    taken: set[str] = set()
    moc_name: dict[str, str] = {}
    for c in sorted(cats, key=lambda x: x["path"]):
        moc_name[c["id"]] = _safe_name(c["name"], taken, "分类")

    # 分类目录 = path 各段安全化（vault 内子目录天然支持）
    cat_dir: dict[str, Path] = {}
    for c in cats:
        segs = [_UNSAFE_FILENAME.sub("_", s.strip()) or "_" for s in c["path"].split("/")]
        cat_dir[c["id"]] = out_dir.joinpath(*segs)

    # 条目 → 主分类（第一个直挂，决定笔记目录）；MOC 列**全部直挂**（多父不丢）
    entries_by_cat: dict[str, list[Any]] = {}
    primary_of: dict[str, str | None] = {}
    for e in entries:
        cids = entry_cats.get(e.id, [])
        primary_of[e.id] = cids[0] if cids else None
        for cid in cids:
            entries_by_cat.setdefault(cid, []).append(e)

    taken_notes: set[str] = set()
    note_base: dict[str, str] = {}
    for e in entries:
        primary = primary_of[e.id]
        cids = entry_cats.get(e.id, [])
        d = cat_dir.get(primary, out_dir) if primary else out_dir
        d.mkdir(parents=True, exist_ok=True)
        base = _safe_name(e.title, taken_notes, e.id[:8])
        note_base[e.id] = base
        note = d / f"{base}.md"
        parent_links = " ".join(f"[[{moc_name[c]}]]" for c in cids if c in moc_name)
        fm = ["---", f"title: {e.title}", f"source_type: {e.source_type}"]
        if e.created_at:
            fm.append(f"created_at: {e.created_at}")
        if e.locator:
            fm.append(f"locator: {e.locator}")
        if cids:
            fm.append("tags: [" + ", ".join(cat_by_id[c]["path"] for c in cids if c in cat_by_id) + "]")
        fm.append("---")
        body = (e.inline_content or "").strip()
        note.write_text(
            "\n".join(fm) + f"\n\n# {e.title}\n\n" + (body + "\n\n" if body else "")
            + (f"分类：{parent_links}\n" if parent_links else ""),
            encoding="utf-8")

    # MOC：子分类链接 + 条目双链
    children: dict[str, list[str]] = {}
    for c in cats:
        for p in c["parents"]:
            children.setdefault(p, []).append(c["id"])
    for c in cats:
        d = cat_dir[c["id"]]
        d.mkdir(parents=True, exist_ok=True)
        kids = sorted(children.get(c["id"], []),
                      key=lambda k: cat_by_id[k]["name"])
        own = sorted(entries_by_cat.get(c["id"], []), key=lambda e: e.title)
        lines = ["---", f"title: {c['name']}（MOC）", "type: moc", "---",
                 f"\n# {c['name']}\n"]
        if kids:
            lines.append("## 子分类\n" + "\n".join(f"- [[{moc_name[k]}]]" for k in kids))
        lines.append(f"\n## 条目（{len(own)}）\n"
                     + ("\n".join(f"- [[{note_base[e.id]}]]" for e in own)
                        if own else "（空）"))
        (d / f"{moc_name[c['id']]}.md").write_text("\n".join(lines) + "\n",
                                                    encoding="utf-8")

    return {"format": "obsidian", "out": str(out_dir),
            "categories": len(cats), "notes": len(entries), "mocs": len(cats)}


# ---- OPML 导出 ----

def export_opml(dl: Any, out: Path) -> dict[str, Any]:
    """http canonical 条目按分类 DAG 展平（探针③：XML 可解析、嵌套=层级、
    叶子数=书签条目数、往返保真）。"""
    cats = dl.all_categories_dag()
    cat_by_id = {c["id"]: c for c in cats}
    entry_cats = dl.all_entry_categories()
    entries = _active_entries(dl)
    bookmarks = [e for e in entries
                 if (e.locator_canonical or "").startswith("http")]

    children: dict[str, list[str]] = {}
    has_parent: set[str] = set()
    for c in cats:
        for p in c["parents"]:
            children.setdefault(p, []).append(c["id"])
            has_parent.add(c["id"])
    entries_by_cat: dict[str, list[Any]] = {}
    for e in bookmarks:
        for cid in entry_cats.get(e.id, []):
            entries_by_cat.setdefault(cid, []).append(e)
    uncategorized = [e for e in bookmarks if not entry_cats.get(e.id)]

    def render(cid: str) -> str:
        c = cat_by_id[cid]
        inner = "".join(render(k) for k in sorted(children.get(cid, []),
                                                  key=lambda k: cat_by_id[k]["name"]))
        inner += "".join(
            f'<outline type="link" text="{_xml_attr(e.title)}"'
            f' htmlUrl="{_xml_attr(e.locator_canonical or e.locator)}"'
            + (f' created="{_xml_attr(e.created_at)}"' if e.created_at else "")
            + "/>"
            for e in sorted(entries_by_cat.get(cid, []), key=lambda x: x.title))
        return f'<outline text="{_xml_attr(c["name"])}">{inner}</outline>'

    roots = sorted((cid for cid in cat_by_id if cid not in has_parent),
                   key=lambda cid: cat_by_id[cid]["name"])
    body = "".join(render(cid) for cid in roots)
    if uncategorized:
        body += ('<outline text="（未分类）">'
                 + "".join(
                     f'<outline type="link" text="{_xml_attr(e.title)}"'
                     f' htmlUrl="{_xml_attr(e.locator_canonical or e.locator)}"/>'
                     for e in sorted(uncategorized, key=lambda x: x.title))
                 + "</outline>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<opml version="2.0">\n<head>\n'
           f"<title>KnowAtlas 导出（schema {EXPORT_SCHEMA_VERSION}）</title>\n"
           f"<dateCreated>{_now_iso()}</dateCreated>\n"
           "</head>\n<body>\n" + body + "\n</body>\n</opml>\n")
    out = Path(out)
    if out.parent != Path(""):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    return {"format": "opml", "out": str(out),
            "bookmarks": len(bookmarks), "categories": len(cats),
            "uncategorized": len(uncategorized)}


def _xml_attr(s: str | None) -> str:
    return _xml_escape(s or "", {'"': "&quot;", "'": "&apos;"})


def _now_iso() -> str:
    from datetime import datetime, timezone  # noqa: PLC0415 热路径外沿

    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
