from kpe.review import render_review

MANIFEST = {"book": "测试书", "chunk_count": 2, "source": "x.pdf"}
POINTS = [
    {"chunk_index": 1, "section_path": "第 1 章 入门 > 1.1 开始",
     "page_start": 3, "page_end": 4, "text": "甲点", "quote": "甲引",
     "quote_ok": True},
    {"chunk_index": 2, "section_path": "第 1 章 入门 > 1.2 继续",
     "page_start": 5, "page_end": 5, "text": "乙点", "quote": "乙引",
     "quote_ok": False},
]


def test_review_default_has_no_section_headings() -> None:
    text = render_review(MANIFEST, POINTS)
    assert "###" not in text
    assert "第 1 章 入门 >" not in text
    assert "## 第 1 章 入门" in text
    assert "1. 甲点" in text and "2. 乙点" in text
    assert "⚠️quote未命中" in text


def test_review_with_sections_keeps_path_and_pages() -> None:
    text = render_review(MANIFEST, POINTS, with_sections=True)
    assert "### 第 1 章 入门 > 1.1 开始（p3-4）" in text
    assert "### 第 1 章 入门 > 1.2 继续（p5）" in text