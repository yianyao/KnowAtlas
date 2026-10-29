"""PDF 快速分页提取（批 97b）：pypdfium2 按页取文本，页间用 `\\f` 分隔。

为什么需要它：`markitdown` 背后的 pdfplumber 是纯 Python 逐字符重建版面，百 MB 级 PDF 会卡死——
实测 `Hello-Agents`（97.9 MB / 720 页）**25 分钟**、`厦门大学…882页`（51 MB / 882 页）跑 8 分钟未完。
PDFium（C++）按页直取文本，同样文件 **2.2 s / 1.2 s**，而且天然带页边界——清洗层据此删页眉页脚
与页码（97a 遗留的"低占比数字行"正是缺页边界才不敢删）。

代价（用户 2026-10-24 裁决 A：小文件保质量、大文件保速度）：表格的 markdown 结构
（`| --- |` 列对齐）会丢，字词不丢——实测 `agentic-design-patterns` 上 markitdown 的 8,604 条长行
中 6,187 条（71%）在 pdfium 文本里逐字命中，未命中的几乎全是表格线与代码列填充。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ..errors import DegradedParseError

# 页分隔符：只在清洗阶段有意义，入 content_store 前会被去掉
PAGE_BREAK = "\f"

MAX_BYTES = 300 * 1024 * 1024     # 闸门：单文件 300 MB
MAX_PAGES = 2000                  # 闸门：单文件 2000 页
MIN_CHARS_PER_PAGE = 20           # 平均每页字符低于此 → 判扫描件（需 OCR，本期不支持）
BUDGET_SECONDS = 120.0            # 单文件解析预算（实测 882 页 1.2 s，留足余量）

# `auto` 策略（工单 §2 方案 A，2026-10-24 实测后收窄）：
# 只有"markitdown 跑不动"的大文件才走快速通道。阈值不能按页数算——
# 实测 `agentic-ai-guide`（8.4 MB）PDFium 只有 markitdown 的 30% 字符、
# `AI-Agents-in-Depth`（11.1 MB）只有 43%，而 markitdown 处理这两个只要 88 s / 40 s，
# 完全等得起。真正跑不动的是百 MB 级：98 MB 要 25 分钟。
# 2026-10-29 复核：那 30%/43% 是**字符口径**差——markitdown 正文 74% 是表格填充（空白/`|`/`---`），
# 去格式后的实字 PDFium 反而是正文的 108%/104%，切块后逐块比对也**没有整段缺失**。
# 阈值「只给百 MB 级走快通道」的结论不变（等的是耗时，不是质量），见
# `docs/design/调研-2026-10-29-PDF取文口径.md`。
AUTO_MAX_BYTES = 30 * 1024 * 1024
AUTO_MAX_PAGES = 1500


@dataclass
class PdfExtract:
    pages: list[str]
    pages_total: int
    empty_pages: int
    chars: int
    backend: str = "pdfium"

    @property
    def chars_per_page(self) -> float:
        return self.chars / self.pages_total if self.pages_total else 0.0

    def to_text(self) -> str:
        """页间用 `\\f` 连接；落库前由 `clean_paged` 负责拆页并去掉分隔符。"""
        return PAGE_BREAK.join(self.pages)


def pdf_gate(path: Path, *, max_bytes: int = MAX_BYTES,
             max_pages: int = MAX_PAGES) -> str | None:
    """闸门判定：返回拒绝原因（None = 可解析）。纯函数，便于单测。"""
    size = path.stat().st_size
    if size > max_bytes:
        return f"pdf_too_large：{size / 1024 / 1024:.0f} MB 超过上限 {max_bytes // 1024 // 1024} MB"
    return None


def is_scanned(chars: int, pages: int,
               *, min_chars_per_page: int = MIN_CHARS_PER_PAGE) -> bool:
    """扫描件判定：平均每页字符太少 = 图片页，没有文本层。"""
    return pages > 0 and chars / pages < min_chars_per_page


def extract_pages(path: Path, *, budget_s: float = BUDGET_SECONDS,
                  max_pages: int = MAX_PAGES,
                  min_chars_per_page: int = MIN_CHARS_PER_PAGE) -> PdfExtract:
    """按页提取文本。超闸门/扫描件/超时一律抛 DegradedParseError（调用方按 degraded 处理）。"""
    reason = pdf_gate(path, max_pages=max_pages)
    if reason is not None:
        raise DegradedParseError(reason, hint="超闸门的 PDF 请先切分，或用 markitdown 单独处理")

    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - 依赖缺失时才走
        raise DegradedParseError(
            "pypdfium2 未安装，无法走快速 PDF 通道",
            hint="pip install pypdfium2（markitdown 的 PDF 依赖里通常已带）",
        ) from exc

    started = time.time()
    pdf = pdfium.PdfDocument(str(path))
    total = len(pdf)
    if total > max_pages:
        raise DegradedParseError(
            f"pdf_too_many_pages：{total} 页超过上限 {max_pages} 页",
            hint="超大 PDF 请切分后再入库",
        )

    pages: list[str] = []
    empty_pages = 0
    chars = 0
    for i in range(total):
        if time.time() - started > budget_s:
            raise DegradedParseError(
                f"pdf_timeout：{budget_s:.0f} s 内只解析了 {i}/{total} 页",
                hint="文件异常庞大或磁盘过慢，已中止以免阻塞同步",
            )
        text = pdf[i].get_textpage().get_text_range()
        if not text.strip():
            empty_pages += 1
        chars += len(text)
        pages.append(text)

    if is_scanned(chars, total, min_chars_per_page=min_chars_per_page):
        raise DegradedParseError(
            f"scanned_pdf：平均每页 {chars / max(total, 1):.1f} 字符（< {min_chars_per_page}），"
            "疑似扫描件/图片版 PDF",
            hint="这类文件需要 OCR，本期不处理；先打好 degraded 标，别让空壳进库",
        )

    return PdfExtract(pages=pages, pages_total=total, empty_pages=empty_pages, chars=chars)


def prefers_fast(path: Path, *, auto_max_bytes: int = AUTO_MAX_BYTES,
                 auto_max_pages: int = AUTO_MAX_PAGES) -> bool:
    """`auto` 策略：大文件走快速通道（小文件继续 markitdown 保表格结构）。"""
    if path.stat().st_size > auto_max_bytes:
        return True
    try:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(str(path))) > auto_max_pages
    except Exception:  # noqa: BLE001 - 读不了页数就交给 markitdown 决定
        return False
