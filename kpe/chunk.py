"""分块：TOC 节合并/切分、Markdown 标题、纯文本窗口。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .store import sha1

HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
PARA_RE = re.compile(r"\n\s*\n")
SKIP_EXACT = {"目录", "前言", "序言", "序", "引言", "致谢", "思考题",
              "本章小结", "本章总结", "本章内容", "参考文献", "后记",
              "封面", "版权", "全书结构", "如何阅读本书", "前置知识",
              "本书约定", "本书结构", "关于作者", "免责声明",
              "版权信息", "出版信息"}
SKIP_PREFIX = ("Contents", "推荐序", "译者序", "作者序", "出版说明")


@dataclass
class Section:
    level: int
    title: str
    page_start: int
    page_end: int
    text: str


@dataclass
class Chunk:
    index: int
    id: str
    section_path: str
    page_start: int
    page_end: int
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)

    def to_dict(self) -> dict:
        return {"index": self.index, "id": self.id,
                "section_path": self.section_path,
                "page_start": self.page_start, "page_end": self.page_end,
                "chars": self.chars, "text": self.text}


def should_skip(title: str) -> bool:
    t = (title or "").strip()
    return (t in SKIP_EXACT
            or any(t.startswith(p) for p in SKIP_PREFIX)
            or t.startswith("思考题")
            or t.startswith("本章小结"))


def split_text(text: str, target: int, overlap: int) -> list[str]:
    """按空行分段累积到 target；超长段硬切；相邻块留 overlap 尾巴。"""
    if len(text) <= target:
        return [text]
    paras = [p for p in PARA_RE.split(text) if p.strip()]
    out: list[str] = []
    cur: list[str] = []
    for p in paras:
        while len(p) > target:
            if cur:
                out.append("\n\n".join(cur))
                cur = []
            out.append(p[:target])
            p = p[target - overlap:]
        if cur and sum(len(x) + 2 for x in cur) + len(p) > target:
            out.append("\n\n".join(cur))
            tail = out[-1][-overlap:]
            cur = [tail] if tail else []
        cur.append(p)
    if cur:
        out.append("\n\n".join(cur))
    return out


def merge_split(sections: list[Section], target: int, overlap: int,
                max_section: int, keep_front: bool = False) -> list[Chunk]:
    chunks: list[Chunk] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_path = ""
    buf_chapter = ""
    buf_start = buf_end = 0
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_path, buf_chapter, buf_start, buf_end, buf_len
        if buf:
            chunks.append(Chunk(0, "", buf_path, buf_start, buf_end,
                                "\n\n".join(buf)))
        buf, buf_path, buf_chapter, buf_len = [], "", "", 0
        buf_start = buf_end = 0

    for sec in sections:
        while stack and stack[-1][0] >= sec.level:
            stack.pop()
        # 仅按自身标题判定是否跳过；不再级联祖先。
        # 否则被 SKIP_EXACT 命中的 L1 顶层章节（如"引言"）一旦入栈且不弹出，
        # 会让其下所有正文（L2/L3）被误判为"后代"而整本被跳过。
        skip = should_skip(sec.title)
        stack.append((sec.level, sec.title))
        if skip and not keep_front:
            continue
        # path 与 chapter 都排除被跳过的祖先（如 L1 顶层"引言"），
        # 避免全书被归到其名下、review 分组失真。
        path = " > ".join(t for _, t in stack if not should_skip(t))
        chapter = path.split(" > ")[0] if path else ""
        piece = f"## {sec.title}\n{sec.text.strip()}" if sec.title else sec.text.strip()
        if not piece:
            continue
        if len(piece) > max_section:
            flush()
            for part in split_text(piece, target, overlap):
                chunks.append(Chunk(0, "", path, sec.page_start, sec.page_end, part))
            continue
        if buf and (chapter != buf_chapter
                    or buf_len + len(piece) + 2 > target):
            flush()
        if not buf:
            buf_path, buf_chapter = path, chapter
            buf_start = sec.page_start
        buf.append(piece)
        buf_len += len(piece) + 2
        buf_end = sec.page_end
    flush()
    return finalize(chunks)


def finalize(chunks: list[Chunk]) -> list[Chunk]:
    for i, c in enumerate(chunks):
        c.index = i + 1
        c.id = sha1(f"{c.section_path}|{i}|{c.text[:80]}")
    return chunks


def markdown_sections(text: str) -> list[Section]:
    sections: list[Section] = []
    title, level = "", 1
    buf: list[str] = []
    fence = False

    def flush() -> None:
        nonlocal buf
        body = "\n".join(buf).strip()
        if body or title:
            sections.append(Section(level, title, 0, 0, body))
        buf = []

    for line in text.splitlines():
        if FENCE_RE.match(line):
            fence = not fence
        m = None if fence else HEAD_RE.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            continue
        buf.append(line)
    flush()
    return [s for s in sections if s.text.strip()]


def window_sections(text: str, title: str) -> list[Section]:
    return [Section(1, title, 0, 0, text)]