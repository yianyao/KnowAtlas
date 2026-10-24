"""书签扩散抓取测试（0.2.0 第四十批）：同目录系列提取、L0 拦截、canonical 去重、上限；
第九十二批：GitHub 仓库树扩散（blob 文件页豁免 L0、tree 子目录下钻、raw 直链抓取）。"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from knowatlas.models import Entry
from knowatlas.pipeline import expand as expand_mod
from knowatlas.pipeline.expand import _gh_blob_dir, _gh_in_scope, _github_scope, expand_seed

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


# ---- 批次 92：GitHub 仓库树扩散（裁决补充：链接要探「真正的知识」） ----

def test_github_scope_parsing():
    assert _github_scope("https://github.com/u/ai-agents") == ("u", "ai-agents", "", "")
    assert _github_scope("https://github.com/u/ai-agents/") == ("u", "ai-agents", "", "")
    assert _github_scope("https://github.com/u/ai-agents/tree/main/cn-book") == \
        ("u", "ai-agents", "main", "cn-book")
    assert _github_scope("https://github.com/u/ai-agents/tree/dev/a/b") == \
        ("u", "ai-agents", "dev", "a/b")
    # 非 tree 多段路径（issues/pull）→ None（回落同目录规则）
    assert _github_scope("https://github.com/u/ai-agents/issues/1") is None
    assert _github_scope("https://github.com/u/ai-agents/pull/9") is None
    # 站内特殊段不是仓库名
    assert _github_scope("https://github.com/topics/ai") is None


def test_gh_scope_dir_and_blob_dir():
    assert _gh_in_scope("", "cn-book/README.md")
    assert _gh_in_scope("cn-book", "cn-book/README.md")
    assert _gh_in_scope("cn-book", "cn-book")
    assert not _gh_in_scope("cn-book", "other/x.md")
    assert _gh_blob_dir(
        "https://github.com/u/ai-agents/blob/main/cn-book/ch/1.md") == "u/ai-agents/cn-book/ch"
    assert _gh_blob_dir("https://github.com/u/ai-agents/blob/main/README.md") == "u/ai-agents"


_GH_ROOT = ('<a href="/u/ai-agents/blob/main/cn-book/README.md">说明</a>'
            '<a href="/u/ai-agents/tree/main/cn-book">书稿目录</a>'
            '<a href="/u/ai-agents/blob/main/LICENSE">许可</a>'
            '<a href="/u/ai-agents/issues/1">issue</a>'
            '<a href="/u/ai-agents/blob/dev/other.md">异分支</a>')
_GH_SUBDIR = ('<a href="/u/ai-agents/blob/main/cn-book/ch1.md">第一章</a>'
              '<a href="/u/ai-agents/blob/main/cn-book/ch2.md">第二章</a>')
_GH_RAW = {  # blob → raw 直链内容（≥ min_content_chars）
    "cn-book/README.md": "# AI Agents 实战（中文版）\n\n" + "本书讲解智能体架构设计，覆盖规划、工具调用与记忆机制。" * 12,
    "LICENSE": "MIT License\n\n" + "版权所有，允许自由使用、修改与分发，须保留版权声明。" * 12,
    "cn-book/ch1.md": "# 第一章 智能体基础\n\n" + "智能体是能感知环境并采取行动的系统，核心循环为规划-执行-反思。" * 12,
    "cn-book/ch2.md": "# 第二章 工具调用\n\n" + "工具调用让模型突破纯文本限制，通过函数签名与 JSON 约束完成结构化输出。" * 12,
}


class _FakeGHClient:
    """模拟 github.com（tree 页 HTML）与 raw.githubusercontent.com（纯文本）。"""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, url, **k):
        self.calls.append(url)
        return _FakeResp(url)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeResp:
    def __init__(self, url: str):
        if "raw.githubusercontent.com" in url:
            rel = url.split("main/", 1)[1]
            self.status_code = 200 if rel in _GH_RAW else 404
            self.text = _GH_RAW.get(rel, "")
        elif url.rstrip("/") == "https://github.com/u/ai-agents/tree/main/cn-book":
            self.status_code = 200
            self.text = _GH_SUBDIR
        elif url.rstrip("/") == "https://github.com/u/ai-agents":
            self.status_code = 200
            self.text = _GH_ROOT
        else:
            self.status_code = 404
            self.text = ""


def _gh_seed(dl) -> Entry:
    e = Entry.build(source_type="bookmark", source_key="edge:9002",
                    title="AI Agents 实战（中文版）",
                    locator="https://github.com/u/ai-agents",
                    locator_canonical="https://github.com/u/ai-agents",
                    meta={"source_type": "bookmark", "browser": "edge"})
    dl.upsert_entries([e])
    return e


def test_expand_github_repo_tree(cfg, dl, registries, monkeypatch):
    """仓库根种子：blob 候选跨 tree 子目录下钻（BFS ≤2 层）、异分支/issue 排除、
    blob 豁免 L0、locator 保留 blob 原链、native_path 记仓库目录；
    批次 94：LICENSE 命中文件名黑名单候选层拦截，gh 条目标题=种子名·文件名。"""
    locators, semantics = registries
    monkeypatch.setattr(expand_mod.httpx, "Client", _FakeGHClient)
    seed = _gh_seed(dl)
    stats = expand_seed(cfg, dl, locators, semantics, seed.id)
    entries = {e.locator: e for e in _expand_entries(dl)}
    assert stats["created"] == 3                      # README/ch1/ch2（LICENSE 拦截）
    assert stats["blocked_files"] == 1
    assert len(entries) == 3
    assert all("/blob/" in loc for loc in entries)    # locator=blob 原链（与书签一致）
    assert not any("LICENSE" in loc for loc in entries)  # 批次 94：黑名单不入库
    readme = entries["https://github.com/u/ai-agents/blob/main/cn-book/README.md"]
    assert readme.meta["expand_reason"] == "github_repo_tree"
    assert readme.meta["seed_entry_id"] == seed.id
    assert readme.native_path == "u/ai-agents/cn-book"        # 仓库目录溯源
    ch1 = entries["https://github.com/u/ai-agents/blob/main/cn-book/ch1.md"]
    assert ch1.native_path == "u/ai-agents/cn-book"
    assert ch1.title == "ai-agents · ch1"   # 批次 94：来源 chips 有上下文（仓库名·文件名）
    # raw 直链正文进 content_store（blob→raw 重写链路）
    assert "智能体" in dl.get_content(readme.content_hash)
    # 异分支/issue 不入候选
    assert not any("dev/" in loc or "issues" in loc for loc in entries)


def test_expand_github_idempotent(cfg, dl, registries, monkeypatch):
    """重复扩散：canonical 去重零新建（blob 原链 canonical 命中）。"""
    locators, semantics = registries
    monkeypatch.setattr(expand_mod.httpx, "Client", _FakeGHClient)
    seed = _gh_seed(dl)
    assert expand_seed(cfg, dl, locators, semantics, seed.id)["created"] == 3
    second = expand_seed(cfg, dl, locators, semantics, seed.id)
    assert second["created"] == 0 and second["already_known"] >= 3
    assert len(_expand_entries(dl)) == 3
