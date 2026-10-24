"""file:// 获取器：txt/md 直读；旧版 .doc/.ppt 走 office_legacy 后端链；
PDF 双通道（批 97b：大文件走 PDFium 保速度与页边界，小文件走 markitdown 保表格结构）；
其余 Office 走 markitdown（缺失即降级报错）。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from ..errors import AdapterError, DegradedParseError
from ..registry.capability import FetchContext

_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
# markitdown 0.1.8 无 Word 97-2003 / PPT 97-2003 转换器（0.2.0 第二十八批：
# 用户核实「我能直接打开的 .doc 被打 unparseable」）——这批扩展名走旧版后端链
_LEGACY_SUFFIXES = {".doc", ".ppt"}


def fetch_file(locator: str, ctx: FetchContext) -> tuple[str, str]:
    """locator 形如 file://docs/报告.pdf —— 配置根相对路径，禁绝对机器路径（§5）。"""
    parts = urlparse(locator)
    if parts.scheme != "file":
        raise AdapterError(f"file_reader 收到非 file locator：{locator}")
    rel = unquote(parts.netloc + parts.path).lstrip("/")
    if not rel or rel.startswith("/") or "\\" in rel or ".." in Path(rel).parts:
        raise AdapterError(f"file locator 含非法路径：{locator}",
                           hint="file:// 只允许配置根相对路径（可迁移铁律）")
    if len(rel) >= 2 and rel[1] == ":":
        raise AdapterError(f"file locator 禁止盘符绝对路径：{locator}",
                           hint="路径必须相对 [sources.folders].roots 中的某个根")

    roots = list(ctx.config.get("sources.folders.roots", []) or [])
    for root in roots:
        candidate = Path(root) / rel
        if candidate.is_file():
            break
    else:
        raise AdapterError(
            f"file:// 目标不存在或未配置 roots：{rel}",
            hint="在 config [sources.folders].roots 配置根目录（file:// 相对它们解析）",
        )

    suffix = candidate.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    elif suffix in _LEGACY_SUFFIXES:
        from .office_legacy import convert_legacy
        text = convert_legacy(candidate, suffix)
    elif suffix == ".pdf":
        text = _read_pdf(candidate, ctx)
    else:
        text = _markitdown(candidate)
    return text, candidate.stem


def _markitdown(path: Path) -> str:
    """markitdown 通道：Office 与（小）PDF 的主力，保表格的 markdown 结构。"""
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise DegradedParseError(
            f"markitdown 未安装，无法解析 {path.suffix.lower()}",
            hint="pip install -r requirements-core.txt",
        ) from exc
    try:
        return MarkItDown().convert(str(path)).text_content
    except Exception as exc:
        raise DegradedParseError(f"markitdown 解析失败：{exc}") from exc


def _read_pdf(path: Path, ctx: FetchContext) -> str:
    """PDF 双通道（工单 97b §2 方案 A + §4）：

    - `fetch.pdf_backend = "markitdown"`：老行为，逐字节一致；
    - `"pdfium"`：强制快速通道，失败即降级报错；
    - `"auto"`（默认）：大文件/多页走 PDFium（实测 500–700 倍），小文件走 markitdown 保表格。
      快速通道因"疑似扫描件"失败时**不再回退**——markitdown 对图片页同样无文本，只会白等几分钟。
    """
    from .pdf_fast import extract_pages, prefers_fast

    backend = str(ctx.config.get("fetch.pdf_backend", "auto") or "auto").lower()
    if backend == "markitdown":
        return _markitdown(path)
    if backend == "pdfium" or (backend == "auto" and prefers_fast(path)):
        try:
            return extract_pages(path).to_text()
        except DegradedParseError as exc:
            if backend != "auto" or "scanned_pdf" in str(exc):
                raise
            # 其它失败（坏文件/字体异常）→ 给 markitdown 一次机会
    return _markitdown(path)
