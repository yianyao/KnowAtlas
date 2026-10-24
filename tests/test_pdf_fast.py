"""批 97b：快速 PDF 分页通道（`fetchers/pdf_fast.py`）单测。

PDF 夹具由本文件手写生成（原始字节 + 自算 xref），不引任何新依赖、不读磁盘上的样本文件。
"""

from __future__ import annotations

import pytest

pytest.importorskip("pypdfium2")
pytest.importorskip("pdfminer")          # 只为确认 markitdown 侧依赖在（非本模块必需）

from knowatlas.errors import DegradedParseError          # noqa: E402
from knowatlas.fetchers.pdf_fast import (                # noqa: E402
    PAGE_BREAK,
    PdfExtract,
    extract_pages,
    is_scanned,
    pdf_gate,
    prefers_fast,
)


def _build_pdf(page_texts: list[str]) -> bytes:
    """生成一个最小可解析 PDF（N 页，每页一行 Helvetica 文本）。"""
    n_pages = len(page_texts)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objs: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode(),
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i, text in enumerate(page_texts):
        page_id, content_id = 3 + 2 * i, 4 + 2 * i
        stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
        objs[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        objs[content_id] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for oid in sorted(objs):
        offsets[oid] = len(out)
        out += b"%d 0 obj\n" % oid + objs[oid] + b"\nendobj\n"
    xref_at = len(out)
    total = font_id + 1
    out += b"xref\n0 %d\n" % total + b"0000000000 65535 f \n"
    for oid in range(1, total):
        out += b"%010d 00000 n \n" % offsets[oid]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (total, xref_at)
    return bytes(out)


def _write(tmp_path, texts: list[str]):
    path = tmp_path / "sample.pdf"
    path.write_bytes(_build_pdf(texts))
    return path


def _long(tag: str) -> str:
    """造一页"有实质正文"的文本（扫描件阈值是 20 字符/页，太短的页会被判扫描件）。"""
    return f"{tag} " + "This paragraph exists so the page has enough characters. " * 6


def test_extract_pages_reads_each_page(tmp_path):
    path = _write(tmp_path, [_long("Alpha page one"), _long("Beta page two"),
                             _long("Gamma page three")])
    found = extract_pages(path)
    assert found.pages_total == 3
    assert found.empty_pages == 0
    assert found.backend == "pdfium"
    assert found.chars > 0
    assert "Alpha" in found.pages[0]
    assert "Gamma" in found.pages[2]


def test_to_text_uses_page_break(tmp_path):
    path = _write(tmp_path, [_long("one"), _long("two"), _long("three")])
    text = extract_pages(path).to_text()
    assert text.count(PAGE_BREAK) == 2
    assert "two" in text.split(PAGE_BREAK)[1]


def test_chars_per_page_property():
    extract = PdfExtract(pages=["abc", "defg"], pages_total=2, empty_pages=0, chars=7)
    assert extract.chars_per_page == 3.5


def test_gate_rejects_oversized(tmp_path):
    path = _write(tmp_path, ["tiny"])
    reason = pdf_gate(path, max_bytes=10)
    assert reason is not None
    assert "too_large" in reason


def test_gate_allows_normal(tmp_path):
    path = _write(tmp_path, ["tiny"])
    assert pdf_gate(path) is None


def test_extract_raises_on_too_many_pages(tmp_path):
    path = _write(tmp_path, ["a", "b", "c"])
    with pytest.raises(DegradedParseError) as excinfo:
        extract_pages(path, max_pages=1)
    assert "too_many_pages" in str(excinfo.value)


def test_extract_raises_on_scanned_pdf(tmp_path):
    path = _write(tmp_path, ["", ""])            # 无文本层 = 图片页
    with pytest.raises(DegradedParseError) as excinfo:
        extract_pages(path)
    assert "scanned_pdf" in str(excinfo.value)


def test_is_scanned_threshold():
    assert is_scanned(0, 10) is True
    assert is_scanned(199, 10) is True          # 19.9 字符/页 < 20
    assert is_scanned(200, 10) is False         # 正好 20 不算
    assert is_scanned(0, 0) is False            # 空文档不判扫描件


def test_prefers_fast_small_file_is_false(tmp_path):
    path = _write(tmp_path, ["a", "b", "c"])
    assert prefers_fast(path) is False


def test_prefers_fast_when_bytes_over_limit(tmp_path):
    path = _write(tmp_path, ["a"])
    assert prefers_fast(path, auto_max_bytes=1) is True


def test_prefers_fast_when_pages_over_limit(tmp_path):
    path = _write(tmp_path, ["a", "b", "c"])
    assert prefers_fast(path, auto_max_pages=2) is True
