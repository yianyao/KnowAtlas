"""入库分流路由测试（工单 2026-10-27《入库即抽点与自动老化》§2.2）。

纯函数 `plan()` 的判定表：零 IO、零 LLM，所以每条规则都能直接断言。
"""

from __future__ import annotations

import pytest

from knowatlas.pipeline.ingest_router import MIN_BODY_CHARS, Route, is_repo_root, plan


def test_repo_page_skipped_but_blob_is_page():
    assert plan("https://github.com/yianyao/KnowAtlas", body_chars=None).reason == "repo_page"
    assert plan("https://github.com/yianyao", body_chars=None).reason == "repo_page"
    assert is_repo_root("https://gitee.com/u/r/")
    # 具体文件/issue/wiki 当普通网页（正文有内容，值得抽）
    r = plan("https://github.com/yianyao/KnowAtlas/blob/main/README.md",
             body_chars=4000)
    assert r.tool == "pipeline"
    assert plan("https://github.com/u/r/issues/12", body_chars=4000).tool == "pipeline"


def test_video_site_needs_capability():
    for url in ("https://www.bilibili.com/video/BV1xx",
                "https://youtu.be/abc", "https://m.youtube.com/watch?v=1"):
        r = plan(url, body_chars=None)
        assert (r.tool, r.reason) == ("skip", "needs_capability")


def test_pdf_goes_kpe_even_without_body():
    r = plan("file:///D:/books/x.pdf", body_chars=None)
    assert (r.tool, r.reason) == ("kpe", "pdf_book")
    # 非 PDF 文档不等同：没有正文先抓
    assert plan("file:///D:/docs/x.docx", body_chars=None).reason == "no_body"


def test_pdf_root_relative_locator_also_routes_kpe():
    """真数据形态：folder 适配器产出 `file://<根相对路径>`，裸文件名落在 netloc。

    2026-10-28 前只取 urlsplit().path，`file://书.pdf` 的 path 为空 → 后缀判不出 →
    12 本真 PDF 全部按字数分流（`pdf_book` 成死代码）。这里钉死两种写法都要走 KPE。
    """
    for locator in ("file://labuladong的算法秘籍V2.7.pdf",      # 裸文件名（netloc）
                    "file://books/Hello-Agents.pdf",             # 子目录
                    "file:///D:/books/x.pdf"):                   # 绝对 URL
        r = plan(locator, body_chars=None)
        assert (r.tool, r.reason) == ("kpe", "pdf_book"), locator
    # 嵌套的相对路径后缀照旧能判，且非书类不受影响
    assert plan("file://repo-main/chapters/Chapter 1.md",
                body_chars=60001).reason == "too_large"


def test_body_size_decides_pipeline_vs_kpe():
    assert plan("https://a.example/x", body_chars=1000).reason == "short"
    assert plan("https://a.example/x", body_chars=6000).reason == "short"
    r = plan("https://a.example/x", body_chars=6001)
    assert (r.tool, r.reason) == ("pipeline", "chunked")
    r2 = plan("https://a.example/x", body_chars=60001)
    assert (r2.tool, r2.reason) == ("kpe", "too_large")
    # 关掉 KPE：超长只能跳过（不静默截断）
    r3 = plan("https://a.example/x", body_chars=60001, allow_kpe=False)
    assert (r3.tool, r3.reason) == ("skip", "too_large")
    # 阈值可配
    assert plan("https://a.example/x", body_chars=1500,
                chunk_chars=1000).reason == "chunked"


def test_too_short_and_other_scheme():
    assert plan("https://a.example/x", body_chars=MIN_BODY_CHARS - 1).reason == "too_short"
    assert plan("maildir://inbox/1.eml", body_chars=None).reason == "other_scheme"
    assert plan("", body_chars=None).reason == "other_scheme"


def test_route_is_immutable_value():
    r = plan("https://a.example/x", body_chars=100)
    with pytest.raises(Exception):
        r.tool = "kpe"  # type: ignore[misc]
    assert isinstance(r, Route) and not r.skippable