"""PDF 读取：目录页解析、页偏移、按页取文（依赖 pdfplumber）。"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .chunk import Section

_DOTS = re.compile(r"^(?P<title>.+?)\s*(?:[.·]\s*){3,}(?P<page>\d{1,3})\s*$")
_PLAIN = re.compile(r"^(?P<title>.+?)\s+(?P<page>\d{1,3})\s*$")
_CHAPTER = re.compile(r"^第\s*[0-9一二三四五六七八九十百]+\s*章")
_NUM3 = re.compile(r"^\d+\.\d+\.\d+")
_NUM2 = re.compile(r"^\d+\.\d+")
_TOP = ("引言", "前言", "序言", "序", "致谢", "后记", "附录")


@dataclass
class TocEntry:
    level: int
    title: str
    page: int          # 印刷页码


def read_pages(path: str | Path) -> list[str]:
    """逐页取文（未清洗）。"""
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        pages = []
        for page in pdf.pages:
            text = (page.extract_text() or "").replace("\xa0", " ")
            pages.append("\n".join(ln.rstrip() for ln in text.splitlines()))
    return pages


def _toc_pages(pages: list[str]) -> list[int]:
    """目录页：前 30 页里，含"目录"或命中 ≥6 条目录行的页。"""
    out: list[int] = []
    for i, text in enumerate(pages[:30]):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        hits = sum(1 for ln in lines if _DOTS.match(ln) or _PLAIN.match(ln))
        if hits >= 6 or (hits >= 3 and "目录" in text):
            out.append(i)
    return out


def _level(title: str, prev: int) -> int:
    if _CHAPTER.match(title) or title in _TOP:
        return 1
    if _NUM3.match(title):
        return 3
    if _NUM2.match(title):
        return 2
    return 2 if prev >= 2 else 2


def _parse_line(line: str) -> tuple[str, int] | None:
    line = line.strip()
    if not line or line == "目录":
        return None
    m = _DOTS.match(line) or _PLAIN.match(line)
    if not m:
        return None
    title = m.group("title").strip(" .·")
    page = int(m.group("page"))
    if len(title) < 2 or page <= 0:
        return None
    return title, page


def parse_toc(pages: list[str]) -> tuple[list[TocEntry], int]:
    """解析目录页，返回 (entries, 最后一个目录页的 1-based 页码)。"""
    toc_idx = _toc_pages(pages)
    if not toc_idx:
        return [], 0
    lines: list[str] = []
    for i in toc_idx:
        lines.extend(ln.strip() for ln in pages[i].splitlines()
                     if ln.strip() and ln.strip() != "目录")
    entries: list[TocEntry] = []
    seen: set[tuple[str, int]] = set()
    prev_level = 1
    i = 0
    while i < len(lines):
        cur = lines[i]
        parsed = _parse_line(cur)
        if parsed is None and i + 1 < len(lines):
            nxt = lines[i + 1]
            if nxt and (_DOTS.match(nxt) or _PLAIN.match(nxt)) and len(cur) < 80:
                parsed = _parse_line(cur + " " + nxt)
                if parsed:
                    i += 1
        if parsed:
            title, page = parsed
            key = (title, page)
            if key not in seen and page <= len(pages) + 20:
                seen.add(key)
                level = _level(title, prev_level)
                entries.append(TocEntry(level, title, page))
                prev_level = level
        i += 1
    return entries, (toc_idx[-1] + 1 if toc_idx else 0)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def detect_offset(entries: list[TocEntry], pages: list[str],
                  toc_end: int) -> int:
    """PDF 页 = 印刷页 + offset。用一级标题在正文中的首次出现校验。"""
    if not entries:
        return 0
    candidates: list[int] = []
    for e in entries:
        if e.level != 1:
            continue
        nt = _norm(e.title)
        for p in range(toc_end, min(len(pages), toc_end + 40)):
            if nt in _norm(pages[p]):
                candidates.append((p + 1) - e.page)
                break
    if candidates:
        common, count = Counter(candidates).most_common(1)[0]
        if count >= 2:
            return common
    # 退化：用"引言"的印刷页 1 推
    for e in entries:
        if e.title.startswith("引言"):
            nt = _norm(e.title)
            for p in range(toc_end, min(len(pages), toc_end + 40)):
                if nt in _norm(pages[p]):
                    return (p + 1) - e.page
            break
    return toc_end if toc_end else 0


def clean_pages(pages: list[str], toc_end: int) -> list[str]:
    """去页眉/页脚/孤立页码/"目录"伪头；目录页原样保留给 parse_toc 用。"""
    n = len(pages)
    first = [p.splitlines()[0].strip() if p.splitlines() else "" for p in pages]
    last = [p.splitlines()[-1].strip() if p.splitlines() else "" for p in pages]
    repeated = {ln for ln, c in Counter(first + last).items()
                if ln and c >= max(3, int(n * 0.4)) and len(ln) <= 40}
    out: list[str] = []
    for i, text in enumerate(pages):
        if i < toc_end:
            out.append(text)
            continue
        lines = [ln.strip() for ln in text.splitlines()]
        kept: list[str] = []
        for j, ln in enumerate(lines):
            if not ln:
                continue
            if j == 0 and (ln == "目录" or ln in repeated):
                continue
            if j >= len(lines) - 2 and ln in repeated:
                continue
            if re.fullmatch(r"\d{1,4}", ln):
                continue
            kept.append(ln)
        out.append("\n".join(kept))
    return out


def build_sections(entries: list[TocEntry], pages: list[str],
                   offset: int) -> list[Section]:
    """按目录页码切节；页码越界/重叠时退化为单页。"""
    sections: list[Section] = []
    prev_end = 0
    for i, e in enumerate(entries):
        start = e.page + offset
        if i + 1 < len(entries):
            end = entries[i + 1].page + offset - 1
        else:
            end = len(pages)
        start = max(1, min(start, len(pages)))
        end = max(start, min(end, len(pages)))
        if start <= prev_end:          # 同一页上的多个条目：内容已归前一节
            start = prev_end + 1
            if start > end:
                continue
        text = "\n\n".join(pages[start - 1:end]).strip()
        if len(text) < 50:
            continue
        first_line = text.splitlines()[0].strip()
        if _norm(first_line) == _norm(e.title) and len(text.splitlines()) > 1:
            text = "\n".join(text.splitlines()[1:]).strip()
        sections.append(Section(level=e.level, title=e.title,
                                page_start=start, page_end=end, text=text))
        prev_end = end
    return sections