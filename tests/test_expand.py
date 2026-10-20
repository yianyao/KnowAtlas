"""书签扩散抓取测试（0.2.0 第四十批）：同目录系列提取、L0 拦截、canonical 去重、上限。"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from knowatlas.models import Entry
from knowatlas.pipeline.expand import expand_seed

PAGES = {
    "/series/01.html": ("<h1>系列文章一：入门</h1>" + "<p>本系列讲消息队列的入门概念与实战，从零搭一个可用队列。" * 10
                        + '<a href="/series/02.html">下一篇</a>'
                        + '<a href="/series/03.html">第三篇</a>'
                        + '<a href="/other/page.html">站内其他目录</a>'
                        + '<a href="https://example.org/out">站外</a>'
                        + '<a href="/series/">系列目录</a>'
                        + '<a href="/series/01.html">本文</a>'),
    "/series/02.html": "<h1>系列文章二：持久化</h1>" + "<p>消息持久化的落盘策略与恢复流程，覆盖刷盘与重放。" * 10,
    "/series/03.html": "<h1>系列文章三：副本</h1>" + "<p>多副本一致性协议简介，主从同步与选主实现要点。" * 10,
    "/other/page.html": "<h1>其他目录文章</h1>" + "<p>不同目录的内容，不应被扩散收录。" * 10,
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802  stdlib 命名
        body = PAGES.get(self.path, "").encode("utf-8")
        status = 200 if body else 404
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _seed(dl, base: str) -> Entry:
    e = Entry.build(source_type="bookmark", source_key="edge:9001",
                    title="系列文章一：入门", locator=f"{base}/series/01.html",
                    locator_canonical=f"{base}/series/01.html",
                    meta={"source_type": "bookmark", "browser": "edge"})
    dl.upsert_entries([e])
    return e


def _expand_entries(dl):
    return [e for e in dl.list_entries(status="active", limit=100)
            if e.source_type == "expand"]


def test_expand_same_dir_series_with_seed_meta(cfg, dl, registries, server):
    """探针①：同目录系列扩散出条目且带 seed_entry_id 与关联解释。"""
    locators, semantics = registries
    seed = _seed(dl, server)
    stats = expand_seed(cfg, dl, locators, semantics, seed.id)
    assert stats["created"] == 2                       # 02、03（other/站外/目录页/自身排除）
    entries = {e.title: e for e in _expand_entries(dl)}
    assert len(entries) == 2
    for e in entries.values():
        assert e.meta["seed_entry_id"] == seed.id      # 探针①：seed 可回溯
        assert e.meta["expand_reason"] == "series_same_dir"
        assert e.content_hash and dl.get_content(e.content_hash)   # 全文进 content_store
    # 分类链路照常（fixture 规则命中"消息队列"等词则归类，否则暂存区——不硬性断言分类）
    ids = {e.id for e in entries.values()}
    assert set(stats["entry_ids"]) == ids


def test_expand_blocks_guard_and_outside_dirs(cfg, dl, registries, server):
    """探针②：L0 拦截 + 不同目录/站外链接不产生条目。"""
    locators, semantics = registries
    seed = _seed(dl, server)
    stats = expand_seed(cfg, dl, locators, semantics, seed.id)
    assert stats["blocked_by_guard"] == 1              # /series/ 尾斜杠列表页（index_subdir）
    titles = {e.title for e in _expand_entries(dl)}
    assert not any("其他目录" in t for t in titles)     # /other/ 不同目录不收
    assert stats["already_known"] == 1                 # 种子自身 canonical 命中


def test_expand_idempotent_canonical_dedupe(cfg, dl, registries, server):
    """探针③：重复扩散不产生重复条目。"""
    locators, semantics = registries
    seed = _seed(dl, server)
    first = expand_seed(cfg, dl, locators, semantics, seed.id)
    assert first["created"] == 2
    second = expand_seed(cfg, dl, locators, semantics, seed.id)
    assert second["created"] == 0 and second["already_known"] == 3  # 02/03 + 种子
    assert len(_expand_entries(dl)) == 2


def test_expand_limit(cfg, dl, registries, server):
    locators, semantics = registries
    seed = _seed(dl, server)
    stats = expand_seed(cfg, dl, locators, semantics, seed.id, limit=1)
    assert stats["created"] == 1
    assert len(_expand_entries(dl)) == 1


def test_expand_rejects_non_http_seed(cfg, dl, registries):
    locators, semantics = registries
    e = Entry.build(source_type="folder", source_key="docs/a.md",
                    title="本地文件", locator="file://docs/a.md",
                    meta={"source_type": "folder"})
    dl.upsert_entries([e])
    with pytest.raises(Exception, match="http"):
        expand_seed(cfg, dl, locators, semantics, e.id)
