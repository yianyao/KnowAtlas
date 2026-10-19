"""万兴脑图适配器（source_type=emmx）：基于真实 MindMaster 9.x 格式的 fixture 测试。

fixture 结构按 2026-10-19 解剖的真实样本定稿：
ZIP 内 document.xml（页清单）+ page/page.xml（Shape 主题树，
文本在 Text/TextBlock/Text 的 <tp>，层级为 LevelData/Super 引用）。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from knowatlas.adapters.emmx import collect_emmx
from knowatlas.errors import AdapterError
from knowatlas.pipeline.sync import run_sync

_DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Document Version="9.2.1" DocVersion="9.1">
    <Properties><Pages V="page"/></Properties>
</Document>"""


def _shape(sid: str, stype: str, title: str, super_id: str = "", sublevel: str = "") -> str:
    tps = "".join(f"<tp CX=\"0\">{part}</tp>" for part in title.split("\n") if part)
    text = f"<Text><TextBlock><Text><pp PX=\"0\">{tps}</pp></Text></TextBlock></Text>" if tps else ""
    level = "<LevelData>"
    if super_id:
        level += f"<Super V=\"{super_id}\"/>"
    if sublevel:
        level += f"<SubLevel V=\"{sublevel}\"/>"
    level += "</LevelData>"
    return f"<Shape ID=\"{sid}\" Type=\"{stype}\">{text}{level}</Shape>"


def _page_xml(shapes: list[str]) -> bytes:
    body = "".join(shapes)
    return f"<?xml version=\"1.0\"?><Page ID=\"1\" Type=\"Page\" Name=\"页面-1\">{body}</Page>".encode("utf-8")


def _write_emmx(path: Path, page: bytes = b"") -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("document.xml", _DOCUMENT_XML)
        if page:
            zf.writestr("page/page.xml", page)


@pytest.fixture
def emmx_tree(tmp_path: Path) -> Path:
    root = tmp_path / "脑图库"
    root.mkdir()
    # 正常脑图：MainIdea → MainTopic → SubTopic，含多段 tp 与 Boundary 装饰容器
    shapes = [
        _shape("101", "MainIdea", "PECOS进度", sublevel="102;104"),
        _shape("102", "MainTopic", "采购", super_id="101", sublevel="108"),
        _shape("108", "SubTopic", "供应商管理\n准入流程", super_id="102"),
        _shape("104", "MainTopic", "编码", super_id="101"),
        _shape("132", "Boundary", ""),  # 装饰容器：SubTopic 挂它 → 断链按顶层
        _shape("200", "SubTopic", "孤立分支", super_id="132"),
    ]
    _write_emmx(root / "创作脑图.emmx", _page_xml(shapes))
    # 降级样本：旧版仅 page.bin；坏 zip；page.xml 无主题节点
    (root / "子目录").mkdir()
    with zipfile.ZipFile(root / "子目录" / "旧版.emmx", "w") as zf:
        zf.writestr("mmpage/page.bin", b"\x00\x01binary")
    (root / "坏zip.emmx").write_bytes(b"not a zip")
    _write_emmx(root / "空图.emmx", _page_xml([_shape("300", "MMConnector", "")]))
    return root


def _enable(cfg, root: Path) -> None:
    cfg._data["sources"]["emmx"] = {"enabled": True, "roots": [str(root)]}


def test_collect_topics(cfg, emmx_tree):
    """结构化解析：Shape 主题树 → 条目；mind_path 沿 Super 引用构建；页名进节点 id。"""
    _enable(cfg, emmx_tree)
    out = collect_emmx(cfg)
    by_loc = {e.locator: e for e in out.entries}
    # 5 个主题节点（101/102/108/104/200，MMConnector 不算）+ 3 个降级文件条目
    assert len(out.entries) == 8
    assert out.stats["degraded_files"] == 3
    node = by_loc["emmx://创作脑图.emmx#page/108"]
    assert node.title == "供应商管理 准入流程"
    assert node.native_path == "脑图库"
    assert node.meta["mind_path"] == "PECOS进度/采购/供应商管理 准入流程"
    assert node.meta["depth"] == 3
    assert by_loc["emmx://创作脑图.emmx#page/104"].meta["mind_path"] == "PECOS进度/编码"
    # Super 指向 Boundary（非主题）→ 断链按顶层分支
    orphan = by_loc["emmx://创作脑图.emmx#page/200"]
    assert orphan.meta["mind_path"] == "孤立分支"
    assert orphan.meta["depth"] == 1


def test_degraded_files(cfg, emmx_tree):
    """仅 page.bin / 坏 zip / 无主题节点 → 标题级单条目，degraded=true。"""
    _enable(cfg, emmx_tree)
    out = collect_emmx(cfg)
    by_loc = {e.locator: e for e in out.entries}
    bad = by_loc["emmx://子目录/旧版.emmx#file"]
    assert bad.meta["degraded"] is True
    assert bad.title == "旧版"
    assert bad.native_path == "脑图库/子目录"
    assert by_loc["emmx://坏zip.emmx#file"].meta["degraded"] is True
    assert by_loc["emmx://空图.emmx#file"].meta["degraded"] is True


def test_missing_root_raises(cfg, tmp_path):
    cfg._data["sources"]["emmx"] = {"enabled": True, "roots": [str(tmp_path / "无")]}
    with pytest.raises(AdapterError):
        collect_emmx(cfg)


def test_sync_emmx_end_to_end(cfg, dl, registries, tmp_path, emmx_tree):
    _enable(cfg, emmx_tree)
    locators, semantics = registries
    stats = run_sync(cfg, dl, locators, semantics, full=True)
    src = stats["sources"]["emmx"]
    assert src["entries"] == 8 and src["created"] == 8
    # 二跑幂等
    stats2 = run_sync(cfg, dl, locators, semantics, full=True)
    assert stats2["sources"]["emmx"]["unchanged"] == 8
