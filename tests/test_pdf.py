from kpe.pdf import build_sections, detect_offset, parse_toc

PAGES = [
    # 0: 目录页
    "目录\n引言 1\n全书结构 . . . 3\n第 1 章 入门 7\n1.1 基础 . . . 8\n1.2 进阶 . . . 9",
    "填充", "填充", "填充",
    "引言\n" + "引言正文" * 20,          # 4 -> 1-based 5
    "填充", "填充", "填充", "填充", "填充",
    "第 1 章 入门\n" + "章正文" * 20,     # 10 -> 1-based 11
    "1.1 基础\n" + "节正文" * 20,        # 11 -> 12
    "1.2 进阶\n" + "节正文" * 20,        # 12 -> 13
]


def test_parse_toc_levels() -> None:
    entries, toc_end = parse_toc(PAGES)
    assert toc_end == 1
    titles = [(e.level, e.title, e.page) for e in entries]
    assert (1, "引言", 1) in titles
    assert (1, "第 1 章 入门", 7) in titles
    assert (2, "1.1 基础", 8) in titles


def test_detect_offset() -> None:
    entries, toc_end = parse_toc(PAGES)
    assert detect_offset(entries, PAGES, toc_end) == 4


def test_build_sections_pages() -> None:
    entries, toc_end = parse_toc(PAGES)
    offset = detect_offset(entries, PAGES, toc_end)
    secs = build_sections(entries, PAGES, offset)
    ch1 = next(s for s in secs if s.title.startswith("第 1 章"))
    assert ch1.page_start == 11
    assert "章正文" in ch1.text
    intro = next(s for s in secs if s.title == "引言")
    assert "引言正文" in intro.text