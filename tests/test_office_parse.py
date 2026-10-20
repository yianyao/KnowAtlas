"""Office 文档解析测试（0.2.0 第二十八批）。

背景：用户核实待清理候选发现「我能直接打开的 .doc 被打 unparseable」——
根因有二：① markitdown 裸装缺可选依赖（docx/xlsx/xls/pptx 全部
MissingDependencyException）；② markitdown 0.1.8 对旧版二进制 .doc/.ppt
根本没有转换器。修复：补依赖 + office_legacy 后端链（soffice → COM）+
补抓成功后清除过时打标。

测试纪律：不依赖真实 Office/LibreOffice——COM/soffice 后端一律 mock；
真实转换只测 markitdown 路径（fixture 由 openpyxl/python-pptx/手工 OOXML 生成）。
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

from knowatlas.config import Config
from knowatlas.errors import DegradedParseError
from knowatlas.fetchers.file_reader import fetch_file
from knowatlas.fetchers import office_legacy
from knowatlas.ids import entry_id as make_entry_id
from knowatlas.models import Entry
from knowatlas.registry.capability import FetchContext


def _ctx(tmp_path: Path) -> FetchContext:
    cfg = Config({"sources": {"folders": {"roots": [str(tmp_path)]}}},
                 tmp_path / "knowatlas.toml")
    return FetchContext(config=cfg, datalayer=None, http=None, run_id="test")


def _write(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- 真实转换

def test_xlsx_parsed(tmp_path: Path):
    """xlsx：openpyxl 造真实文件 → markitdown 解析出单元格文本。"""
    openpyxl = pytest.importorskip("openpyxl")
    p = _write(tmp_path, "报表.xlsx")
    wb = openpyxl.Workbook()
    wb.active["A1"] = "预算总额标记词"
    wb.save(p)
    text, title = fetch_file("file://报表.xlsx", _ctx(tmp_path))
    assert "预算总额标记词" in text
    assert title == "报表"


def test_pptx_parsed(tmp_path: Path):
    """pptx：python-pptx 造真实文件 → markitdown 解析出幻灯片文本。"""
    pptx_mod = pytest.importorskip("pptx")
    p = _write(tmp_path, "方案.pptx")
    prs = pptx_mod.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(0, 0, 100, 50)
    box.text_frame.text = "嵌入式系统维护标记词"
    prs.save(p)
    text, _ = fetch_file("file://方案.pptx", _ctx(tmp_path))
    assert "嵌入式系统维护标记词" in text


def test_docx_parsed(tmp_path: Path):
    """docx：手工最小 OOXML 包 → mammoth 解析出正文。"""
    pytest.importorskip("mammoth")
    p = _write(tmp_path, "手册.docx")
    NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>")
        zf.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>")
        zf.writestr("word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{NS_W}"><w:body><w:p><w:r>'
            "<w:t>技术手册正文标记词</w:t></w:r></w:p></w:body></w:document>")
    text, title = fetch_file("file://手册.docx", _ctx(tmp_path))
    assert "技术手册正文标记词" in text


# ---------------------------------------------------------------- 路由与降级

def test_doc_routes_to_legacy_chain(tmp_path: Path, monkeypatch):
    """.doc 不进 markitdown，走 office_legacy 后端链。"""
    calls = []

    def fake_convert(path, suffix):
        calls.append(suffix)
        return "COM提取的正文"

    monkeypatch.setattr(office_legacy, "convert_legacy", fake_convert)
    p = _write(tmp_path, "技术手册.doc")
    p.write_bytes(b"\xd0\xcf\x11\xe0fake-ole")
    text, _ = fetch_file("file://技术手册.doc", _ctx(tmp_path))
    assert text == "COM提取的正文"
    assert calls == [".doc"]


def test_legacy_no_backend_actionable_error(tmp_path: Path, monkeypatch):
    """soffice 与 COM 均不可用 → DegradedParseError 且给出可操作指引。"""
    monkeypatch.setattr(office_legacy, "_find_soffice", lambda: None)
    # 令 import win32com.client 失败（sys.modules 存 None 即 ImportError）
    monkeypatch.setitem(sys.modules, "win32com.client", None)
    monkeypatch.setitem(sys.modules, "pythoncom", None)
    p = _write(tmp_path, "手册.doc")
    p.write_bytes(b"\xd0\xcf\x11\xe0fake-ole")
    with pytest.raises(DegradedParseError) as ei:
        office_legacy.convert_legacy(p, ".doc")
    assert "另存" in ei.value.hint  # 报错必须指路


def test_legacy_com_backend_used_when_no_soffice(tmp_path: Path, monkeypatch):
    """无 soffice → COM 后端。"""
    monkeypatch.setattr(office_legacy, "_find_soffice", lambda: None)
    monkeypatch.setattr(office_legacy, "_com_extract",
                        lambda path, suffix: "COM文本")
    p = _write(tmp_path, "手册.doc")
    p.write_bytes(b"fake")
    assert office_legacy.convert_legacy(p, ".doc") == "COM文本"


def test_legacy_soffice_backend_first(tmp_path: Path, monkeypatch):
    """soffice 存在时优先（跨平台首选），COM 不被调用。"""
    monkeypatch.setattr(office_legacy, "_find_soffice", lambda: "soffice")
    monkeypatch.setattr(office_legacy, "_convert_soffice",
                        lambda path, suffix: "SOFFICE文本")
    called = {"com": False}
    def boom(path, suffix):
        called["com"] = True
        return ""
    monkeypatch.setattr(office_legacy, "_com_extract", boom)
    p = _write(tmp_path, "手册.ppt")
    p.write_bytes(b"fake")
    assert office_legacy.convert_legacy(p, ".ppt") == "SOFFICE文本"
    assert called["com"] is False


# ---------------------------------------------------------------- 打标清除

def _insert_entry(dl, meta: dict, key: str = "a") -> str:
    entry_id = make_entry_id("folder", f"file://{key}.doc")
    dl.upsert_entries([Entry(
        id=entry_id, source_type="folder", title="t", locator=f"file://{key}.doc",
        locator_canonical=None, native_path=f"{key}.doc", inline_content=None,
        content_hash=None, meta=meta, created_at="2026-10-20T00:00:00+08:00",
        exported_at="2026-10-20T00:00:00+08:00", status="active")])
    return entry_id


def test_merge_meta_none_deletes_key(dl):
    """merge_meta None = 删键（不是存 null）。"""
    eid = _insert_entry(dl, {"value_flag": "not_knowledge", "keep": 1})
    dl.merge_meta(eid, {"value_flag": None})
    meta = dl.get_entry(eid).meta
    assert "value_flag" not in meta
    assert meta["keep"] == 1  # 其余键不受影响


def test_clear_stale_fetch_flags_removes_candidates(dl):
    """补抓成功后：unparseable/unreachable/garbled 打标被清，条目离开待清理候选。"""
    from knowatlas.pipeline.sync import _clear_stale_fetch_flags
    eid = _insert_entry(dl, {"value_flag": "not_knowledge",
                             "value_flag_reason": "unparseable",
                             "fetch_error": "markitdown 解析失败"})
    _clear_stale_fetch_flags(dl, [eid])
    meta = dl.get_entry(eid).meta
    assert "value_flag" not in meta
    assert "value_flag_reason" not in meta
    assert "fetch_error" not in meta


def test_clear_stale_fetch_flags_keeps_user_veto_and_l0(dl):
    """用户否决（value_flag=ok）与 L0 结构规则打标不清——只清 fetch 三因。"""
    from knowatlas.pipeline.sync import _clear_stale_fetch_flags
    veto_id = _insert_entry(dl, {"value_flag": "ok",
                                 "value_flag_reason": "unparseable"}, key="veto")
    l0_id = _insert_entry(dl, {"value_flag": "not_knowledge",
                               "value_flag_reason": "portal_homepage"}, key="l0")
    _clear_stale_fetch_flags(dl, [veto_id, l0_id])
    assert dl.get_entry(veto_id).meta["value_flag"] == "ok"
    assert dl.get_entry(l0_id).meta["value_flag"] == "not_knowledge"
    assert dl.get_entry(l0_id).meta["value_flag_reason"] == "portal_homepage"
