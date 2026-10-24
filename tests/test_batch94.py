"""批次 94 数据质量测试：骨架四路信号（结构标签泄漏/重复行）、gh 扩散黑名单
与空/骨架守门、点级语义去重（dupe_of 可逆标记 + 消费面 SQL 过滤）。"""

from __future__ import annotations

from knowatlas.fetchers.base import is_skeleton_body
from knowatlas.models import Entry
from knowatlas.pipeline import expand as expand_mod
from knowatlas.pipeline.embed_index import dedup_points
from knowatlas.pipeline.expand import _gh_file_blocked, expand_seed
from knowatlas.pipeline.points import point_hash
from knowatlas.semantic.embed import normalize, vec_to_blob


# ---- ① is_skeleton_body 新增两路信号 ----

def test_skeleton_struct_tag_leak():
    """HTML 实体骨架（真库案例「\\xhtml\\r\\n<head>…」）：裸露结构标签 ≥3 判骨架。"""
    junk = ("\\xhtml\r\n<head>\r\n<meta charset=\"utf-8\">\r\n"
            "<title>index</title>\r\n</head>\r\n<body>目录</body>")
    assert is_skeleton_body(junk)
    # 教 HTML 的文档（有围栏代码块）不误伤——标签在代码示例里合法出现
    doc = ("# HTML 入门\n```html\n<html><head><meta charset=\"utf-8\">"
           "<title>t</title></head><body>hi</body></html>\n```\n"
           + "正文讲解文档结构骨架各元素语义。" * 20)
    assert not is_skeleton_body(doc)


def test_skeleton_repeated_lines():
    """目录索引页（真库案例：文件列表同一行重复 20+ 次）：互异行占比过低判骨架。"""
    listing = "\n".join(["ebook-treasure-chest 文件列表"]
                        + ["assets/cover.png  —— 同名文件条目行"] * 20
                        + ["结尾不重复行"])
    assert is_skeleton_body(listing)
    # 代码文件偶有重复行（右括号）但互异占比高 → 不判（防 folder 源误伤）
    code = "\n".join(x
                     for i in range(10)
                     for x in (f"class A{i}:", "    def m(self):", "        pass",
                               "}", "}"))
    assert not is_skeleton_body(code)


# ---- ① gh 扩散文件黑名单 ----

def test_gh_file_blocked_name_and_ext():
    b = _gh_file_blocked
    assert b("https://github.com/u/r/blob/main/.nojekyll") is not None
    assert b("https://github.com/u/r/blob/main/.gitignore") is not None
    assert b("https://github.com/u/r/blob/main/LICENSE") is not None
    assert b("https://github.com/u/r/blob/main/CONTRIBUTING.md") is not None
    assert b("https://github.com/u/r/blob/main/img/logo.png") is not None
    assert b("https://github.com/u/r/blob/main/dist/app.zip") is not None
    assert b("https://github.com/u/r/blob/main/cn-book/ch1.md") is None
    assert b("https://github.com/u/r/blob/main/notes/README.md") is None


# ---- ① expand 守门：黑名单/空正文/骨架不入库 ----

class _Resp:
    def __init__(self, status_code=200, text=""):
        self.status_code, self.text = status_code, text


class _Client:
    """极简 http 替身：raw 直链按相对路径查表，其余按完整 URL 查表。"""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get(self, url, **k):
        if "raw.githubusercontent.com" in url:
            rel = url.split("/main/", 1)[-1]
            t = self.pages.get(rel)
            return _Resp(200, t) if t is not None else _Resp(404, "")
        return _Resp(200, self.pages.get(url, ""))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _bookmark(dl, locator: str, title: str) -> Entry:
    e = Entry.build(source_type="bookmark", source_key="b94",
                    title=title, locator=locator, locator_canonical=locator,
                    meta={"source_type": "bookmark"})
    dl.upsert_entries([e])
    return e


def _expand_entries(dl):
    return [e for e in dl.list_entries(status="active", limit=100)
            if e.source_type == "expand"]


def test_expand_gh_blacklist_and_title(cfg, dl, registries, monkeypatch):
    """黑名单文件候选层拦截不发起抓取；gh 条目标题=「仓库名 · 文件名」。"""
    locators, semantics = registries
    pages = {
        "https://github.com/u/ai-agents":
            '<a href="/u/ai-agents/blob/main/.nojekyll">n</a>'
            '<a href="/u/ai-agents/blob/main/img/x.png">p</a>'
            '<a href="/u/ai-agents/blob/main/cn-book/ch1.md">c1</a>',
        "cn-book/ch1.md": "# 第一章\n" + "智能体是能感知环境并采取行动的系统。" * 12,
    }
    monkeypatch.setattr(expand_mod.httpx, "Client", lambda: _Client(pages))
    seed = _bookmark(dl, "https://github.com/u/ai-agents", "AI Agents 实战")
    stats = expand_seed(cfg, dl, locators, semantics, seed.id)
    assert stats["blocked_files"] == 2
    assert stats["created"] == 1
    entries = _expand_entries(dl)
    assert len(entries) == 1
    assert entries[0].title == "ai-agents · ch1"
    assert not any(".nojekyll" in e.locator or ".png" in e.locator
                   for e in entries)


def test_expand_empty_and_skeleton_body_skipped(cfg, dl, registries, monkeypatch):
    """入库前统一守门：空正文/骨架正文不产生条目（升级后端旁路防护）。"""
    locators, semantics = registries
    pages = {"https://example.com/dir/a.html":
             '<a href="/dir/b.html">b</a><a href="/dir/c.html">c</a>'
             '<a href="/dir/d.html">d</a>'}

    def fake_fetch(link, loc, ctx):
        if link.endswith("b.html"):
            return "", "b"                                   # 空正文
        if link.endswith("c.html"):
            return "\n".join(["Sign in"] * 10), "c"          # 骨架
        return "正文内容充实，讲解消息队列持久化与重放机制。" * 20, "d"

    monkeypatch.setattr(expand_mod.httpx, "Client", lambda: _Client(pages))
    monkeypatch.setattr(expand_mod, "fetch_with_fallback", fake_fetch)
    seed = _bookmark(dl, "https://example.com/dir/a.html", "系列页")
    stats = expand_seed(cfg, dl, locators, semantics, seed.id)
    assert stats["empty_body"] == 1
    assert stats["skeleton"] == 1
    assert stats["created"] == 1
    entries = _expand_entries(dl)
    assert len(entries) == 1 and entries[0].title == "d"


# ---- ③ 点级语义去重 + 消费面过滤 ----

_T1 = "Agent = LLM + 上下文 + 工具，三者构成智能体的基本结构。"
_T2 = "智能体的基本结构：Agent 等于大模型加上下文加工具的组合。"
_T3 = "完全不同的知识：消息队列的持久化落盘与重放机制。"


def _put_text_point(dl, text: str, entry_id: str) -> str:
    """落一个点并返回其 id（put_point 返回 created/linked，需反查）。"""
    ch = point_hash(text)
    dl.put_point({"content_hash": ch, "text": text,
                  "summary": text[:20], "source_type": "manual",
                  "judge": "integral", "meta": {}},
                 {"entry_id": entry_id, "char_offset": None, "anchor": ""})
    return next(p["id"] for p in dl.list_points(limit=100)
                if p["content_hash"] == ch)


def _entries(dl, n: int) -> list[Entry]:
    es = [Entry.build(source_type="manual", source_key=f"b94:m{i}",
                      title=f"条目{i}", locator=f"https://example.com/{i}",
                      locator_canonical=None,
                      inline_content=f"第{i}篇正文", meta={"source_type": "manual"})
          for i in range(1, n + 1)]
    dl.upsert_entries(es)
    return es


def test_dedup_points_marks_dupe_and_filters_consumption(cfg, dl):
    """改写措辞绕过 content_hash 的同知识：向量同组留最优（溯源多者），
    副点 dupe_of 退出 search_points/get_point_hit 消费面。"""
    e1, e2, e3, e4 = _entries(dl, 4)
    p1 = _put_text_point(dl, _T1, e1.id)
    _put_text_point(dl, _T1, e4.id)          # p1 第二条溯源 → 溯源数 2
    p2 = _put_text_point(dl, _T2, e2.id)     # 改写同知识，1 条溯源
    p3 = _put_text_point(dl, _T3, e3.id)
    v_same = normalize([1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    v_diff = normalize([0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    dl.put_point_vectors([
        {"point_id": p1, "dim": 8, "vector": vec_to_blob(v_same), "model": "fake"},
        {"point_id": p2, "dim": 8, "vector": vec_to_blob(v_same), "model": "fake"},
        {"point_id": p3, "dim": 8, "vector": vec_to_blob(v_diff), "model": "fake"}])
    stats = dedup_points(dl)
    assert stats["groups"] == 1 and stats["dupes"] == 1
    best, dupe = p1, p2                       # 溯源数 2 > 1 → p1 留，p2 副点
    meta2 = next(p for p in dl.list_points(limit=100) if p["id"] == p2)["meta"]
    assert meta2["dupe_of"] == p1
    meta1 = next(p for p in dl.list_points(limit=100) if p["id"] == p1)["meta"]
    assert "dupe_of" not in meta1
    # 幂等：重跑不再新增标记
    assert dedup_points(dl)["dupes"] == 0
    # 消费面：副点退出（search_points FTS/LIKE、get_point_hit）
    hit_ids = {h.point_id for h in dl.search_points("Agent")}
    assert p1 in hit_ids and p2 not in hit_ids
    assert dl.get_point_hit(p2) is None
    assert dl.get_point_hit(p1) is not None
    assert p3 in {h.point_id for h in dl.search_points("消息队列")}


def test_dedup_points_skip_stale_and_no_vectors(cfg, dl):
    """stale 点与无向量点不参与聚类；向量不足 2 条直接降级返回。"""
    e1, e2 = _entries(dl, 2)
    p1 = _put_text_point(dl, _T1, e1.id)
    p2 = _put_text_point(dl, _T2, e2.id)
    v = normalize([1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    dl.put_point_vectors([
        {"point_id": p1, "dim": 8, "vector": vec_to_blob(v), "model": "fake"},
        {"point_id": p2, "dim": 8, "vector": vec_to_blob(v), "model": "fake"}])
    dl.set_point_aging(p1, "stale", "测试老化")
    stats = dedup_points(dl)
    assert stats["groups"] == 0 and stats["dupes"] == 0  # stale 不参与 → 无组
    assert dedup_points(dl, threshold=0.95)["vectors"] >= 0


def test_dedup_points_insufficient_vectors(cfg, dl):
    e1 = _entries(dl, 1)
    _put_text_point(dl, _T1, e1[0].id)
    stats = dedup_points(dl)
    assert stats["groups"] == 0 and stats["dupes"] == 0
    assert "note" in stats
