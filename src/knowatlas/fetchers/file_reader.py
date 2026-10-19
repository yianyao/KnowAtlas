"""file:// 获取器：txt/md 直读；Office/PDF 走 markitdown（缺失即降级报错）。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from ..errors import AdapterError, DegradedParseError
from ..registry.capability import FetchContext

_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}


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
    else:
        try:
            from markitdown import MarkItDown
        except ImportError as exc:
            raise DegradedParseError(
                f"markitdown 未安装，无法解析 {suffix}",
                hint="pip install -r requirements-core.txt",
            ) from exc
        try:
            text = MarkItDown().convert(str(candidate)).text_content
        except Exception as exc:
            raise DegradedParseError(f"markitdown 解析失败：{exc}") from exc
    return text, candidate.stem
