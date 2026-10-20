"""旧版二进制 Office（.doc/.ppt）解析——markitdown 无对应转换器，走可选后端链。

背景（0.2.0 第二十八批）：用户核实待清理候选时发现「我能直接打开的 .doc 被打了
unparseable」——文件本身是好的，是 markitdown 0.1.8 根本没有 Word 97-2003 /
PowerPoint 97-2003 的转换器（报 "No converter attempted a conversion"）。

后端顺序（均可用才用，逐级降级）：
1. LibreOffice（soffice）headless 转 docx/pptx 后交 markitdown——跨平台首选，
   路径来源：环境变量 KNOWATLAS_SOFFICE_PATH 覆盖 → PATH 查找。
2. Windows COM（MS Office Word/PowerPoint；依赖 pywin32，可选依赖）——
   本机装了 Office 即可用，直接提取文本，不落临时文件。
3. 均不可用 → DegradedParseError，报错信息给出可操作指引（另存 docx/pptx、
   装 LibreOffice、Windows 装 pywin32+Office）。

可迁移性：不硬编码机器路径；两个后端都是可选能力，缺失时优雅降级并指路。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..errors import DegradedParseError

# soffice 常见安装位置（标准目录，非机器绑定；env 可覆盖）
_SOFFICE_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/opt/libreoffice/program/soffice",
)

# soffice 转换目标：.doc→docx、.ppt→pptx（转出后交 markitdown）
_SOFFICE_TARGET = {".doc": "docx", ".ppt": "pptx"}


def _find_soffice() -> str | None:
    """定位 soffice 可执行文件；环境变量 KNOWATLAS_SOFFICE_PATH 优先。"""
    env = os.environ.get("KNOWATLAS_SOFFICE_PATH", "").strip()
    if env and Path(env).is_file():
        return env
    found = shutil.which("soffice")
    if found:
        return found
    for cand in _SOFFICE_CANDIDATES:
        if Path(cand).is_file():
            return cand
    return None


def _convert_soffice(path: Path, suffix: str) -> str:
    """soffice headless 转成 docx/pptx 后交 markitdown 解析。"""
    target = _SOFFICE_TARGET[suffix]
    outdir = tempfile.mkdtemp(prefix="knowatlas_conv_")
    try:
        proc = subprocess.run(
            [_find_soffice(), "--headless", "--convert-to", target,
             "--outdir", outdir, str(path)],
            capture_output=True, timeout=120,
        )
        converted = Path(outdir) / (path.stem + "." + target)
        if proc.returncode != 0 or not converted.is_file():
            raise DegradedParseError(
                f"LibreOffice 转换失败（{path.name}）："
                f"{proc.stderr.decode(errors='replace')[:120] or '未产出目标文件'}")
        from markitdown import MarkItDown
        return MarkItDown().convert(str(converted)).text_content
    except DegradedParseError:
        raise
    except Exception as exc:
        raise DegradedParseError(f"LibreOffice 转换异常：{exc}") from exc
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


def _clean_com_text(text: str) -> str:
    """COM 提取的文本：段内换行/单元格分隔符归一为可检索文本。"""
    # \x07 = Word 表格单元格结束符；\r = 段落；\x0b = 软换行
    return (text.replace("\x07", "\t").replace("\r", "\n")
                .replace("\x0b", "\n"))


def _com_extract(path: Path, suffix: str) -> str:
    """Windows COM 提取文本（MS Office；pywin32 可选依赖）。"""
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise _com_unavailable(path, suffix) from exc
    pythoncom.CoInitialize()
    try:
        if suffix == ".doc":
            return _com_extract_word(win32com.client, path)
        return _com_extract_powerpoint(win32com.client, path)
    finally:
        pythoncom.CoUninitialize()


def _com_unavailable(path: Path, suffix: str) -> DegradedParseError:
    return DegradedParseError(
        f"旧版 {suffix} 文件无法解析：{path.name}",
        hint="任选其一：① 用 Word/PowerPoint 另存为 docx/pptx；"
             "② 安装 LibreOffice（KNOWATLAS_SOFFICE_PATH 可指定路径）；"
             "③ Windows 安装 pywin32 且本机装有 MS Office",
    )


def _com_extract_word(winc, path: Path) -> str:
    word = winc.Dispatch("Word.Application")
    word.Visible = False
    doc = None
    try:
        doc = word.Documents.Open(str(path), ReadOnly=True,
                                  AddToRecentFiles=False)
        return _clean_com_text(doc.Content.Text or "")
    finally:
        if doc is not None:
            doc.Close(SaveChanges=0)
        word.Quit()


def _com_extract_powerpoint(winc, path: Path) -> str:
    app = winc.Dispatch("PowerPoint.Application")
    pres = None
    try:
        # WithWindow:=False —— 不弹窗口
        pres = app.Presentations.Open(str(path), ReadOnly=True, Untitled=False,
                                      WithWindow=False)
        parts: list[str] = []
        for slide in pres.Slides:
            for shape in slide.Shapes:
                if shape.HasTextFrame and shape.TextFrame.HasText:
                    parts.append(shape.TextFrame.TextRange.Text or "")
        return _clean_com_text("\n".join(parts))
    finally:
        if pres is not None:
            pres.Close()
        app.Quit()


def convert_legacy(path: Path, suffix: str) -> str:
    """旧版 .doc/.ppt → 文本。后端链：soffice → COM → 指路报错。"""
    if _find_soffice() is not None:
        try:
            return _convert_soffice(path, suffix)
        except DegradedParseError:
            raise
        except Exception:  # soffice 存在但单次转换失败 → 试 COM
            pass
    if suffix in (".doc", ".ppt"):
        try:
            return _com_extract(path, suffix)
        except DegradedParseError:
            raise
        except Exception as exc:
            raise DegradedParseError(
                f"COM 解析 {suffix} 失败（{path.name}）：{exc}",
                hint="文件可能加密/损坏，或 Office 自动化被策略禁用；"
                     "可改用 Word/PowerPoint 另存为 docx/pptx",
            ) from exc
    raise DegradedParseError(f"旧版格式 {suffix} 暂无解析后端：{path.name}")
