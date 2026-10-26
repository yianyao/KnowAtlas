"""条目原文站内代理（2026-10-26 P4 后置项 B）：GET /api/entries/{id}/file。

背景：`file://` 存的是「配置根相对路径」，浏览器既把它首段当主机名、又禁止 http 页跳
`file://` → 反查/列表里「打开原文」全是假链接（用户报障「反查可溯源，但打不开」）。
本端点按 `[sources.folders].roots` 解析成绝对路径后流式返回：PDF/图片/文本内联，
HTML/SVG/Office 一律附件下载（防同源脚本读走写令牌）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowatlas.models import Entry
from knowatlas.web.app import create_app


def _client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_TEST_TOKEN")), "t")
    locators, semantics = registries
    return TestClient(create_app(cfg, dl, locators, semantics),
                      headers={"Host": "127.0.0.1:8420"})


def _folder_entry(rel: str, title: str = "") -> Entry:
    return Entry.build(
        source_type="folder", source_key=rel, title=title or rel,
        locator=f"file://{rel}", locator_canonical=None, native_path="资料库",
        meta={"source_type": "folder"}, created_at=None)


@pytest.fixture
def docs_root(cfg, tmp_path: Path) -> Path:
    root = tmp_path / "资料库"
    (root / "子目录").mkdir(parents=True)
    (root / "报告.pdf").write_bytes(b"%PDF-1.4\n%fake pdf body\n")
    # write_bytes：避免 Windows 文本模式把 \n 翻成 \r\n（本测断言逐字节一致）
    (root / "笔记.md").write_bytes("第一行\n第二行\n".encode("utf-8"))
    (root / "页面.html").write_bytes(b"<html><script>alert(1)</script></html>")
    (root / "子目录" / "嵌套.txt").write_bytes("嵌套正文".encode("utf-8"))
    cfg._data.setdefault("sources", {})["folders"] = {
        "enabled": True, "roots": [str(root)]}
    return root


def test_file_pdf_inline(cfg, dl, registries, monkeypatch, docs_root):
    """根内 PDF → 200、application/pdf、inline、nosniff（浏览器自带阅读器能翻页）。"""
    e = dl.upsert_entries([_folder_entry("报告.pdf", "报告")]).ids[0]
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get(f"/api/entries/{e}/file")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.content.startswith(b"%PDF-1.4")


def test_file_markdown_text(cfg, dl, registries, monkeypatch, docs_root):
    """markdown → text/plain; charset=utf-8，正文逐字节一致（中文不乱码）。"""
    e = dl.upsert_entries([_folder_entry("笔记.md")]).ids[0]
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get(f"/api/entries/{e}/file")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "charset=utf-8" in r.headers["content-type"]
    assert r.content.decode("utf-8") == "第一行\n第二行\n"


def test_file_html_forced_download(cfg, dl, registries, monkeypatch, docs_root):
    """HTML 若 inline 会以本服务同源执行（能读 localStorage 写令牌）→ 必须附件下载。"""
    e = dl.upsert_entries([_folder_entry("页面.html")]).ids[0]
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get(f"/api/entries/{e}/file")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_file_nested_relative_path(cfg, dl, registries, monkeypatch, docs_root):
    """子目录相对路径照常解析（roots 下任意深度）。"""
    e = dl.upsert_entries([_folder_entry("子目录/嵌套.txt")]).ids[0]
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get(f"/api/entries/{e}/file")
    assert r.status_code == 200
    assert r.content.decode("utf-8") == "嵌套正文"


def test_file_missing(cfg, dl, registries, monkeypatch, docs_root):
    e = dl.upsert_entries([_folder_entry("不存在.pdf")]).ids[0]
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get(f"/api/entries/{e}/file")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "FILE_MISSING"


@pytest.mark.parametrize("locator", ["file://../secret.txt", "file://D:/windows/win.ini"])
def test_file_traversal_rejected(cfg, dl, registries, monkeypatch, docs_root, locator):
    """`..` 与盘符绝对路径在解析前就拒（403），不试读文件。"""
    e = dl.upsert_entries([Entry.build(
        source_type="folder", source_key=locator, title="越界",
        locator=locator, locator_canonical=None, native_path="",
        meta={"source_type": "folder"}, created_at=None)]).ids[0]
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get(f"/api/entries/{e}/file")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "OUT_OF_ROOT"


@pytest.mark.parametrize("source_type,locator", [
    ("emmx", "emmx://重要概念.emmx#file"),
    ("bookmark", "https://example.com/文章"),
])
def test_file_not_supported(cfg, dl, registries, monkeypatch, docs_root,
                            source_type, locator):
    """非 file:// 条目（脑图/网页）不装能开：404 NOT_SUPPORTED，前端退化纯文本。"""
    e = dl.upsert_entries([Entry.build(
        source_type=source_type, source_key=locator, title="别源",
        locator=locator, locator_canonical=None, native_path="",
        meta={"source_type": source_type}, created_at=None)]).ids[0]
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get(f"/api/entries/{e}/file")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_SUPPORTED"


def test_file_unknown_entry(cfg, dl, registries, monkeypatch, docs_root):
    c = _client(cfg, dl, registries, monkeypatch)
    r = c.get("/api/entries/nosuchid/file")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"