"""脑图大纲树测试（批次 91）：parse_tree 重建节点树 + /api/entries/{id}/emmx_tree。

.emmx fixture 结构与 test_emmx.py 同款（2026-10-19 真实 MindMaster 9.x 解剖格式）：
ZIP 内 document.xml（页清单）+ page/page.xml（Shape 主题树，LevelData/Super 引用）。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowatlas.adapters.emmx import parse_tree
from knowatlas.errors import AdapterError
from knowatlas.models import Entry
from knowatlas.web.app import create_app

_DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Document Version="9.2.1" DocVersion="9.1">
    <Properties><Pages V="page"/></Properties>
</Document>"""


def _shape(sid: str, stype: str, title: str, super_id: str = "") -> str:
    tps = "".join(f"<tp CX=\"0\">{part}</tp>" for part in title.split("\n") if part)
    text = f"<Text><TextBlock><Text><pp PX=\"0\">{tps}</pp></Text></TextBlock></Text>" if tps else ""
    level = f"<LevelData>{f'<Super V=\"{super_id}\"/>' if super_id else ''}</LevelData>"
    return f"<Shape ID=\"{sid}\" Type=\"{stype}\">{text}{level}</Shape>"


def _page_xml(shapes: list[str]) -> bytes:
    body = "".join(shapes)
    return f"<?xml version=\"1.0\"?><Page ID=\"1\" Type=\"Page\" Name=\"页面-1\">{body}</Page>".encode("utf-8")


def _write_emmx(path: Path, page: bytes) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("document.xml", _DOCUMENT_XML)
        zf.writestr("page/page.xml", page)


# ---- parse_tree 纯函数 ----

def test_parse_tree_nested(tmp_path: Path):
    """MainIdea → MainTopic → SubTopic 三层嵌套正确重建。"""
    p = tmp_path / "a.emmx"
    _write_emmx(p, _page_xml([
        _shape("101", "MainIdea", "总务管理"),
        _shape("102", "MainTopic", "报账", "101"),
        _shape("108", "SubTopic", "采购费用", "102"),
        _shape("104", "MainTopic", "采购", "101"),
    ]))
    out = parse_tree(p)
    assert out["node_count"] == 4
    assert len(out["pages"]) == 1
    tree = out["pages"][0]["tree"]
    assert tree["title"] == "总务管理"          # 单顶层直接作根
    assert [c["title"] for c in tree["children"]] == ["报账", "采购"]  # 保持文档序
    assert tree["children"][0]["children"][0]["title"] == "采购费用"


def test_parse_tree_broken_link_top_level(tmp_path: Path):
    """Super 指向非主题 Shape（Boundary 断链）→ 按顶层，多顶层包虚拟根。"""
    p = tmp_path / "b.emmx"
    _write_emmx(p, _page_xml([
        _shape("101", "MainIdea", "主题"),
        _shape("132", "Boundary", ""),          # 装饰容器不建节点
        _shape("200", "SubTopic", "孤立分支", "132"),
    ]))
    out = parse_tree(p)
    tree = out["pages"][0]["tree"]
    assert tree["title"] == ""                  # 虚拟根无标题
    titles = [c["title"] for c in tree["children"]]
    assert titles == ["主题", "孤立分支"]
    assert out["node_count"] == 2               # Boundary 不计


def test_parse_tree_bad_zip(tmp_path: Path):
    p = tmp_path / "c.emmx"
    p.write_bytes(b"not a zip")
    with pytest.raises(AdapterError):
        parse_tree(p)


def test_parse_tree_no_topics(tmp_path: Path):
    """page.xml 无主题节点（旧版/空图）→ AdapterError，不渲染假树。"""
    p = tmp_path / "d.emmx"
    _write_emmx(p, _page_xml([_shape("300", "MMConnector", "")]))
    with pytest.raises(AdapterError):
        parse_tree(p)


# ---- API 端点 ----

def _client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_TEST_TOKEN")), "t")
    locators, semantics = registries
    return TestClient(create_app(cfg, dl, locators, semantics),
                      headers={"Host": "127.0.0.1:8420"})


def _emmx_entry(root: Path, rel: str) -> Entry:
    return Entry.build(
        source_type="emmx", source_key=rel, title="总务管理",
        locator=f"emmx://{rel}#map", locator_canonical=None,
        native_path=root.name, inline_content="- 总务管理",
        meta={"source_type": "emmx", "judge": "integral", "mind_path": "总务管理"},
        created_at=None)


@pytest.fixture
def emmx_home(tmp_path: Path) -> Path:
    root = tmp_path / "脑图库"
    (root / "开发").mkdir(parents=True)
    _write_emmx(root / "开发" / "总务管理.emmx", _page_xml([
        _shape("101", "MainIdea", "总务管理"),
        _shape("102", "MainTopic", "报账", "101"),
    ]))
    return root


def test_api_emmx_tree_ok(cfg, dl, registries, monkeypatch, emmx_home):
    cfg._data.setdefault("sources", {})["emmx"] = {
        "enabled": True, "roots": [str(emmx_home)]}
    e = dl.upsert_entries([_emmx_entry(emmx_home, "开发/总务管理.emmx")]).ids[0]
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get(f"/api/entries/{e}/emmx_tree")
    assert r.status_code == 200
    data = r.json()
    assert data["node_count"] == 2
    assert data["pages"][0]["tree"]["title"] == "总务管理"
    assert data["pages"][0]["tree"]["children"][0]["title"] == "报账"


def test_api_emmx_tree_not_mindmap(cfg, dl, registries, monkeypatch, emmx_home):
    cfg._data.setdefault("sources", {})["emmx"] = {
        "enabled": True, "roots": [str(emmx_home)]}
    e = dl.upsert_entries([Entry.build(
        source_type="emmx", source_key="x.emmx#p/1", title="碎片",
        locator="emmx://x.emmx#p/1", locator_canonical=None, native_path="",
        meta={"source_type": "emmx"}, created_at=None)]).ids[0]
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get(f"/api/entries/{e}/emmx_tree")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_MINDMAP"


def test_api_emmx_tree_file_missing(cfg, dl, registries, monkeypatch, emmx_home):
    cfg._data.setdefault("sources", {})["emmx"] = {
        "enabled": True, "roots": [str(emmx_home)]}
    e = dl.upsert_entries([_emmx_entry(emmx_home, "开发/不存在.emmx")]).ids[0]
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get(f"/api/entries/{e}/emmx_tree")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "FILE_MISSING"
