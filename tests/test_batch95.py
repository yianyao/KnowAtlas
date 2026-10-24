"""批次 95 测试：GitHub 仓库页 canonical 归一、GitHub 页面模板骨架信号、
scan_and_merge 现算 canonical 合并存量变体书签。"""

from __future__ import annotations

from knowatlas.fetchers.base import is_skeleton_body
from knowatlas.ids import canonical_url
from knowatlas.models import Entry
from knowatlas.pipeline.dedupe import scan_and_merge
from knowatlas.pipeline.expand import _gh_file_blocked


# ---- ① canonical：GitHub 仓库页归一 ----

def test_canonical_github_repo_page_normalized():
    can = canonical_url
    # 根页与 /tree/{分支} 变体归一到仓库根（真库教训：bojieli/ai-agent-book 双书签）
    assert can("https://github.com/u/r") == "https://github.com/u/r"
    assert can("https://github.com/u/r/") == "https://github.com/u/r"
    assert can("https://github.com/u/r/tree/main") == "https://github.com/u/r"
    assert can("https://github.com/u/r/tree/2nd-ed") == "https://github.com/u/r"
    # tab= 仅切视图非内容差异
    assert can("https://github.com/u/r?tab=readme-ov-file") == "https://github.com/u/r"
    # 子目录树种子 / blob 深链 / 非 repo 路径不动
    assert can("https://github.com/u/r/tree/main/cn-book") == \
        "https://github.com/u/r/tree/main/cn-book"
    assert can("https://github.com/u/r/blob/main/README.md") == \
        "https://github.com/u/r/blob/main/README.md"
    assert can("https://github.com/u/r/issues/1") == \
        "https://github.com/u/r/issues/1"
    assert can("https://github.com/u") == "https://github.com/u"
    # 非 GitHub 不受影响
    assert can("https://example.com/a/tree/main") == \
        "https://example.com/a/tree/main"


# ---- ② 骨架第五路信号：GitHub 页面模板标记 ----

def test_skeleton_github_chrome_markers():
    # 真库案例：226 字符纯 GitHub 模板（短骨架，四路信号全漏网）
    body = ("Skip to content\n\n\\#\\# Navigation Menu\n\n\\{\\{ message \\}\\}\n\n"
            "\\#\\# Repository navigation\n\n\\# README\\.md\n\n\\# README\\.md\n\n"
            "\\#\\# File metadata and controls\n\n16 lines \\(13 loc\\) · 445 Bytes\n\n"
            "You can't perform that action at this time.")
    assert is_skeleton_body(body)
    # 正文提到 1-2 个标记不误伤
    doc = ("# GitHub 页面结构解析\n\nGitHub 页面顶部有 Skip to content 链接，"
           "侧栏是 Navigation Menu。\n\n" + "正文讲解页面各区域的功能与 DOM 结构。" * 20)
    assert not is_skeleton_body(doc)
    # 讲抓取的教程在围栏代码块里引用全套模板 → 豁免不误伤
    tutorial = ("# 抓取 GitHub 页面\n```text\nSkip to content\nNavigation Menu\n"
                "Repository navigation\nFile metadata and controls\n```\n"
                + "教程正文讲解如何绕过这些模板区块拿到正文。" * 20)
    assert not is_skeleton_body(tutorial)


# ---- ③ docsify 家具黑名单 ----

def test_gh_furniture_blacklist():
    b = _gh_file_blocked
    assert b("https://github.com/u/r/blob/main/coverpage.md") is not None
    assert b("https://github.com/u/r/blob/main/navbar.md") is not None
    assert b("https://github.com/u/r/blob/main/sidebar.md") is not None
    assert b("https://github.com/u/r/blob/main/_sidebar.md") is not None
    assert b("https://github.com/u/r/blob/main/cn-book/_sidebar.md") is not None
    assert b("https://github.com/u/r/blob/main/cn-book/ch1.md") is None


# ---- ④ scan_and_merge 现算 canonical：存量变体书签合并 ----

def _bm(dl, key: str, locator: str, title: str, canon: str) -> Entry:
    e = Entry.build(source_type="bookmark", source_key=key,
                    title=title, locator=locator, locator_canonical=canon,
                    inline_content=f"{title} 的正文内容", meta={"source_type": "bookmark"})
    dl.upsert_entries([e])
    return e


def test_scan_merges_stale_canonical_variants(cfg, dl):
    """落库 canonical 已过时（规则演进前入库）→ scan 现算归一后合并：
    副条目标 dedupe_master + locator 附挂主条目（可逆，删标即恢复）。"""
    master = _bm(dl, "b95:a", "https://github.com/u/r", "仓库根书签",
                 "https://github.com/u/r")
    dup = _bm(dl, "b95:b", "https://github.com/u/r/tree/main", "变体书签",
              "https://github.com/u/r/tree/main")  # 落库值过时
    stats = scan_and_merge(dl)
    assert stats["merged"] >= 1
    # 主方向由 (created_at, id) 决定（同批插入 id 随机）——断言一对恰好一方被标
    a, b = dl.get_entry(master.id), dl.get_entry(dup.id)
    marks = [(a, a.meta.get("dedupe_master")), (b, b.meta.get("dedupe_master"))]
    assert sorted(m is None for _, m in marks) == [False, True]
    dup_e = a if a.meta.get("dedupe_master") else b
    master_e = dl.get_entry(dup_e.meta["dedupe_master"])
    assert dup_e.meta["dedupe_reason"] == "canonical_hit"
    assert dup_e.locator != master_e.locator  # 变体 URL 附挂主条目（可逆）
    # 幂等：重跑零新增
    assert scan_and_merge(dl)["merged"] == 0
