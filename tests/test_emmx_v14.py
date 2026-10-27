"""EMMX v14（MindMaster 14.x）二进制页解析：合成 fixture 单测。

真实格式取证见 `docs/design/变更工单-2026-10-27-EMMX-v14二进制页解析.md`：
节点头尾是固定标记串，文本段以 `7B 04` / `01 04` / `14 ? 3F` 开头，
段间 BRK 前导 = 作者换行，否则是排版折行（要拼回同一行）。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from knowatlas.adapters.emmx import (
    _block_lines,
    _bin_page_names,
    _split_blocks,
    collect_emmx,
    parse_tree,
)

_END = bytes.fromhex("0000000A7F0000000B7F00000000")
_BRK = bytes.fromhex("000000017C027B0401027B04")


def _t(s: str) -> bytes:
    return s.encode("utf-8")


def _page_bin(blocks: list[bytes]) -> bytes:
    return b"".join(b + _END for b in blocks)


def _root_block(title: str, lines: list[str]) -> bytes:
    """根节点块：`14 ? 3F` 开头，其后每条 line 用 BRK 前导换行。"""
    out = b"\x14\x08\x3f" + _t(title) + b"\x00"
    for line in lines:
        out += _BRK + _t(line) + b"\x00"
    return out


def _node_block(title: str, lines: list[str] | None = None) -> bytes:
    out = b"\x7b\x04" + _t(title) + b"\x00"
    for line in lines or []:
        out += _BRK + _t(line) + b"\x00"
    return out


def _document(pages: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Document Version="14.0.3" DocVersion="13.1"><Properties>'
        f'<Pages V="{pages}"/></Properties></Document>'
    ).encode("utf-8")


def _write_v14(path: Path, pages: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("document.xml", _document(";".join(pages)))
        for name, data in pages.items():
            zf.writestr(f"mmpage/{name}.bin", data)


def _enable(cfg, root: Path) -> None:
    cfg._data["sources"]["emmx"] = {"enabled": True, "roots": [str(root)]}


# —— 解析层 ——

def test_split_blocks_and_lines():
    """块结束标记切块；BRK 前导=换行；无 BRK 的相邻段=折行拼接。"""
    wrap = (b"\x7b\x04" + _t("前半句") + b"\x00"
            + b"\x7b\x04" + _t("后半句") + b"\x00")
    bin_bytes = _page_bin([_root_block("根主题", ["第一行"]), wrap])
    blocks = _split_blocks(bin_bytes)
    assert len(blocks) == 2
    assert _block_lines(blocks[0]) == ["根主题", "第一行"]
    assert _block_lines(blocks[1]) == ["前半句后半句"]


def test_empty_and_binary_blocks_dropped():
    """只有二进制/无文本的块不产出行（图片、边界框）。"""
    junk = b"\x08\x01\x02\x03\x00\x00"
    bin_bytes = _page_bin([_node_block("有效", ["正文"]), junk])
    lines = [_block_lines(b) for b in _split_blocks(bin_bytes)]
    assert lines[0] == ["有效", "正文"]
    assert lines[1] == []


def test_bin_page_names_follow_document_order(tmp_path):
    """页序取 document.xml 的 Pages（page;page-1;page-2），而非文件名排序。"""
    path = tmp_path / "顺序.emmx"
    _write_v14(path, {"page": _page_bin([_node_block("page")]),
                      "page-1": _page_bin([_node_block("page-1")]),
                      "page-2": _page_bin([_node_block("page-2")])})
    with zipfile.ZipFile(path) as zf:
        assert [p for p, _ in _bin_page_names(zf)] == ["page", "page-1", "page-2"]


# —— 适配器层 ——

def test_collect_v14_one_entry_per_page(cfg, tmp_path):
    """每页一条目：标题=首块首行，meta 标 v14/flat，正文含各块。"""
    root = tmp_path / "脑图库"
    root.mkdir()
    _write_v14(root / "JS笔记.emmx", {
        "page": _page_bin([_root_block("原型", ["原型链"]),
                           _node_block("对象", ["函数也是对象"])]),
        "page-1": _page_bin([_root_block("作用域", ["执行上下文"])]),
    })
    _enable(cfg, root)
    out = collect_emmx(cfg)
    by_loc = {e.locator: e for e in out.entries}
    assert len(out.entries) == 2
    first = by_loc["emmx://JS笔记.emmx#page"]
    assert first.title == "原型"
    assert first.meta["emmx_format"] == "v14"
    assert first.meta["hierarchy"] == "flat"
    assert first.meta["blocks"] == 2
    assert "原型链" in first.inline_content and "函数也是对象" in first.inline_content
    second = by_loc["emmx://JS笔记.emmx#page-1"]
    assert second.title == "作用域"
    assert out.stats["v14_pages"] == 2
    assert out.stats["v14_blocks"] == 3


def test_v14_without_text_still_degrades(cfg, tmp_path):
    """14.x 分支无可用正文 → 仍走标题级降级（不产空条目）。"""
    root = tmp_path / "脑图库"
    root.mkdir()
    with zipfile.ZipFile(root / "空页.emmx", "w") as zf:
        zf.writestr("document.xml", _document("page"))
        zf.writestr("mmpage/page.bin", b"\x01\x02\x03")
    _enable(cfg, root)
    out = collect_emmx(cfg)
    assert len(out.entries) == 1
    assert out.entries[0].meta["degraded"] is True
    assert out.stats["degraded_files"] == 1


def test_parse_tree_v14_flat(tmp_path):
    """树形浏览：v14 返回一页一层扁平树（hierarchy=flat，不渲染假层级）。"""
    path = tmp_path / "图.emmx"
    _write_v14(path, {"page": _page_bin([_root_block("原型", []),
                                         _node_block("对象", [])])})
    out = parse_tree(path)
    page = out["pages"][0]
    assert page["hierarchy"] == "flat"
    assert page["tree"]["title"] == "原型"
    assert [c["title"] for c in page["tree"]["children"]] == ["对象"]
    assert out["node_count"] == 2