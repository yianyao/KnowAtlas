from kpe.chunk import (Section, markdown_sections, merge_split, should_skip,
                       split_text)


def test_split_text_overlap_and_size() -> None:
    text = "\n\n".join(f"第{i}段" + "内容" * 80 for i in range(10))
    parts = split_text(text, 600, 60)
    assert len(parts) > 1
    assert all(len(p) <= 700 for p in parts)
    assert parts[1].startswith(parts[0][-60:])


def test_merge_chapter_boundary_and_skip() -> None:
    secs = [
        Section(1, "第 1 章", 1, 2, "甲" * 100),
        Section(2, "1.1", 3, 3, "乙" * 100),
        Section(2, "思考题", 4, 4, "题目" * 50),
        Section(1, "第 2 章", 5, 6, "丙" * 100),
    ]
    chunks = merge_split(secs, target=500, overlap=50, max_section=800)
    assert len(chunks) == 2
    assert chunks[0].section_path.startswith("第 1 章")
    assert "思考题" not in chunks[0].text
    assert chunks[1].section_path.startswith("第 2 章")


def test_merge_long_section_splits() -> None:
    secs = [Section(1, "第 1 章", 1, 10, "\n\n".join(["段" * 200] * 20))]
    chunks = merge_split(secs, target=600, overlap=60, max_section=1000)
    assert len(chunks) > 1
    assert all(c.chars <= 700 for c in chunks)


def test_markdown_fence_ignored() -> None:
    md = "# 标题\n\n正文\n\n```bash\n# 这不是标题\nls\n```\n\n## 小节\n\n内容"
    secs = markdown_sections(md)
    titles = [s.title for s in secs]
    assert "标题" in titles and "小节" in titles
    assert "这不是标题" not in titles


def test_should_skip() -> None:
    assert should_skip("思考题")
    assert should_skip("本章小结")
    assert should_skip("本章总结")
    assert should_skip("前言")
    assert should_skip("全书结构")
    assert should_skip("关于作者")
    assert should_skip("Contents 免责声明")
    assert not should_skip("2.4 提示工程")