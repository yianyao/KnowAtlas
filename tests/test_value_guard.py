"""L0 价值守卫测试（2026-10-20 新增：URL 结构判「非知识内容」，零费用不调 LLM）。

探针：
1. judge_value 三类规则正例 + 防误杀反例（PDF/电子书/内容页/仓库页不判）；
2. classify_coarse 对命中条目 L0 短路——不占 L1/L2/L3、**不调 LLM**；
3. value_flag=ok（用户否决）的条目不被规则标记；
4. run_sync(value_scan=True) 端到端：打标 + reason 落库 + dry-run 不写；
5. Web /api/not-knowledge 透出 reason 字段。
"""

from __future__ import annotations

import json

import pytest

from knowatlas.models import Entry
from knowatlas.pipeline.sync import run_sync
from knowatlas.semantic.base import SemanticInput, TaskContext
from knowatlas.semantic.tasks.classify_coarse import run as run_coarse
from knowatlas.semantic.value_guard import judge_value


# ---------- 1. 规则单元 ----------

@pytest.mark.parametrize("url,reason", [
    # portal_homepage：path 为空或 "/"（query/fragment 不影响）
    ("https://example.com/", "portal_homepage"),
    ("https://example.com", "portal_homepage"),
    ("http://foo.bar", "portal_homepage"),
    ("https://jc.pep.com.cn/?filed=x&subject=y", "portal_homepage"),
    ("https://mindmemos.cn/#/workspace/api-docs", "portal_homepage"),
    # index_subdir：path 以 "/" 结尾且非根（列表/导航子页）
    ("https://docs.python.org/zh-cn/3/", "index_subdir"),
    ("https://gitee.com/liu21st/thinkphp/tree/v5.0.24/", "index_subdir"),
    ("https://www.cybermania.ws/post/2/?s=adobe", "index_subdir"),
    # resource_file：资源文件本体（与 scheme 无关；大小写不敏感；query 不影响）
    ("https://x.com/a.zip", "resource_file"),
    ("https://x.com/setup.EXE", "resource_file"),
    ("https://x.com/movie.mp4?token=abc", "resource_file"),
    ("https://x.com/app.apk#frag", "resource_file"),
    ("file:///D:/Data/归档.zip", "resource_file"),
    ("https://x.com/%E4%B8%AD%E6%96%87.7z", "resource_file"),
])
def test_judge_value_positive(url, reason):
    assert judge_value(url) == reason


@pytest.mark.parametrize("url", [
    # 内容页：无尾斜杠、.html、仓库页
    "https://github.com/u/r",
    "https://sqlite.org/docs.html",
    "https://x.com/post/123",
    "https://docs.python.org/zh-cn/3/tutorial/index.html",
    # PDF/电子书：可解析正文的知识资源，不判（fetchers markitdown 路线）
    "https://eloquentjavascript.net/Eloquent_JavaScript.pdf",
    "https://x.com/book.epub",
    # 矢量图标不判（常伴文档出现）
    "https://x.com/diagram.svg",
    # 无扩展名的下载页不判（结构不可判，留给 LLM 语义）
    "https://x.com/download?id=42",
    # 其余 scheme / 空值
    "javascript:alert(1)",
    "chrome://settings/",
    "",
])
def test_judge_value_negative(url):
    assert judge_value(url) is None


def test_judge_value_malformed_never_raises():
    """畸形/异体 netloc：不抛异常；判定结论稳定可预期（IDN 首页结构上就是首页）。"""
    assert judge_value("https://例え.jp/") == "portal_homepage"
    assert judge_value("file:///D:/Data/测试 文件/说明.txt") is None
    for url in ("::", "https://", "file:"):
        assert judge_value(url) is None or judge_value(url) in (
            "resource_file", "portal_homepage", "index_subdir")


# ---------- 2. classify_coarse L0 短路 ----------


class _RecordingLlm:
    """记录收到的条目文本；chat 被调用即视为烧钱——短路条目不应到达这里。"""

    def __init__(self):
        self.calls: list[str] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append(user)
        return '[{"i":1,"path":"人工智能","conf":0.7,"kind":"knowledge"}]'


def _inp(locator: str, title: str = "某页面", value_flag: str | None = None) -> SemanticInput:
    meta = {"source_type": "bookmark", "locator": locator}
    if value_flag:
        meta["value_flag"] = value_flag
    return SemanticInput(entry_id="e1", title=title, body=None,
                         native_path=None, meta=meta)


def test_l0_short_circuits_without_llm():
    """首页条目：L0 直接短路，零 LLM 调用；tags 与 LLM kind=non 同构。"""
    llm = _RecordingLlm()
    outs = run_coarse([_inp("https://cn.vuejs.org/")],
                      TaskContext(run_id="r", llm=llm))
    assert outs[0].classifications == []
    assert "not_knowledge" in outs[0].tags
    assert "value_reason:portal_homepage" in outs[0].tags
    assert llm.calls == []  # 没花 token


def test_l0_mixed_batch_only_pending_entries_reach_llm():
    """混合批次：仅非短路条目进 L3（L1/L2 未命中才调 LLM）。"""
    llm = _RecordingLlm()
    outs = run_coarse(
        [_inp("https://cn.vuejs.org/"), _inp("https://x.com/plain-page", "无关键词标题")],
        TaskContext(run_id="r", llm=llm))
    assert outs[0].classifications == [] and "not_knowledge" in outs[0].tags
    assert outs[1].classifications and outs[1].classifications[0].origin == "llm"
    assert len(llm.calls) == 1
    assert "vuejs" not in llm.calls[0], "首页条目不应进 LLM 输入"


def test_l0_respects_user_veto():
    """用户已否决（value_flag=ok）的首页条目：不短路，正常走分类（可被 LLM 归并）。"""
    llm = _RecordingLlm()
    outs = run_coarse([_inp("https://cn.vuejs.org/", value_flag="ok")],
                      TaskContext(run_id="r", llm=llm))
    assert "not_knowledge" not in outs[0].tags
    assert outs[0].classifications and outs[0].classifications[0].origin == "llm"
    assert len(llm.calls) == 1


# ---------- 3. value_scan 端到端 ----------


def _entry(title: str, locator: str) -> Entry:
    return Entry.build(source_type="bookmark", source_key=f"edge:{title}",
                       title=title, locator=locator, locator_canonical=locator,
                       native_path="书签栏")


def test_value_scan_end_to_end(cfg, dl, registries):
    """全量打标：三类各一条 + 一条正常页；stats 与 meta 双向可查。"""
    locators, semantics = registries
    dl.upsert_entries([
        _entry("门户", "https://cn.vuejs.org/"),
        _entry("列表", "https://docs.python.org/zh-cn/3/"),
        _entry("资源", "https://x.com/a.zip"),
        _entry("内容", "https://github.com/u/r"),
    ])
    stats = run_sync(cfg, dl, locators, semantics, value_scan=True)["value_scan"]
    assert stats["value_scan_total"] == 4
    assert stats["new_flagged"] == 3
    assert stats["by_reason"] == {"portal_homepage": 1, "index_subdir": 1,
                                  "resource_file": 1}
    assert stats["dry_run"] is False

    flagged = {e.title: e for e in dl.list_by_value_flag("not_knowledge")}
    assert set(flagged) == {"门户", "列表", "资源"}
    assert flagged["门户"].meta["value_flag_reason"] == "portal_homepage"
    assert flagged["列表"].meta["value_flag_reason"] == "index_subdir"
    assert flagged["资源"].meta["value_flag_reason"] == "resource_file"
    # 未被标记的条目无 value_flag
    content = dl.find_by_canonical("https://github.com/u/r")
    assert content is not None and "value_flag" not in content.meta
    # task_log 留痕
    runs = dl.recent_runs(5)
    assert runs


def test_value_scan_dry_run_writes_nothing(cfg, dl, registries):
    locators, semantics = registries
    dl.upsert_entries([_entry("门户", "https://cn.vuejs.org/")])
    stats = run_sync(cfg, dl, locators, semantics, value_scan=True,
                     dry_run=True)["value_scan"]
    assert stats["new_flagged"] == 1 and stats["dry_run"] is True
    assert dl.list_by_value_flag("not_knowledge") == []


def test_value_scan_respects_veto_and_existing(cfg, dl, registries):
    """ok 条目跳过；已标记条目只补 reason 不重复计数。"""
    locators, semantics = registries
    e_ok = _entry("用户要留", "https://keep.example.com/")
    dl.upsert_entries([e_ok])
    dl.merge_meta(e_ok.id, {"value_flag": "ok"})
    e_llm = _entry("LLM 已标", "https://docs.djangoproject.com/zh-hans/3.1/")
    dl.upsert_entries([e_llm])
    dl.merge_meta(e_llm.id, {"value_flag": "not_knowledge"})  # 旧 LLM 标记、无 reason

    stats = run_sync(cfg, dl, locators, semantics, value_scan=True)["value_scan"]
    assert stats["new_flagged"] == 0          # 没有新标记
    assert stats["reasons_filled"] == 1       # 旧标记补齐 reason
    e_new = dl.get_entry(e_llm.id)
    assert e_new.meta["value_flag_reason"] == "index_subdir"
    assert dl.get_entry(e_ok.id).meta["value_flag"] == "ok"


def test_sync_ingest_flags_via_l0(cfg, dl, registries, tmp_path):
    """ksync 正常同步路径：新建首页书签即被 L0 打标，不占分类位（不调 LLM 也能生效）。"""
    data = {"roots": {"bookmark_bar": {"type": "folder", "name": "书签栏", "id": "1",
             "children": [{"type": "url", "id": "10", "name": "Vue 官网",
                           "url": "https://cn.vuejs.org/", "date_added": "13350000000000000"}]}},
            "version": 1}
    file = tmp_path / "Bookmarks"
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    cfg._data["sources"]["bookmarks"] = {"enabled": True, "browsers": ["edge"],
                                         "paths": {"edge": str(file)}}
    locators, semantics = registries
    stats = run_sync(cfg, dl, locators, semantics)["sources"]["bookmarks"]
    assert stats["created"] == 1
    assert stats["flagged_not_knowledge"] == 1
    assert stats["classified"] == 0 and stats["staged"] == 1
    e = dl.find_by_canonical("https://cn.vuejs.org/")
    assert e.meta.get("value_flag") == "not_knowledge"
    assert e.meta.get("value_flag_reason") == "portal_homepage"
    assert dl.get_entry_categories(e.id) == []


# ---------- 3.5 回归：机器 meta 不被同步抹掉 + 否决后不重新打标（第十八批 bug） ----------


def _enable_bookmarks(cfg, file) -> None:
    cfg._data["sources"]["bookmarks"] = {"enabled": True, "browsers": ["edge"],
                                         "paths": {"edge": str(file)}}


def _bm_file(tmp_path, url: str, title: str):
    data = {"roots": {"bookmark_bar": {"type": "folder", "name": "书签栏", "id": "1",
             "children": [{"type": "url", "id": "10", "name": title,
                           "url": url, "date_added": "13350000000000000"}]}},
            "version": 1}
    file = tmp_path / "Bookmarks"
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    return file


def test_sync_preserves_flag_and_stays_idempotent(cfg, dl, registries, tmp_path):
    """L0 打标后再同步：value_flag/reason 不被 upsert 抹掉，且 unchanged 不翻转。"""
    _enable_bookmarks(cfg, _bm_file(tmp_path, "https://cn.vuejs.org/", "Vue 官网"))
    locators, semantics = registries
    s1 = run_sync(cfg, dl, locators, semantics)["sources"]["bookmarks"]
    assert s1["created"] == 1 and s1["flagged_not_knowledge"] == 1
    s2 = run_sync(cfg, dl, locators, semantics)["sources"]["bookmarks"]
    assert s2["created"] == 0 and s2["updated"] == 0 and s2["unchanged"] == 1
    e = dl.find_by_canonical("https://cn.vuejs.org/")
    assert e.meta.get("value_flag") == "not_knowledge"
    assert e.meta.get("value_flag_reason") == "portal_homepage"


def test_sync_does_not_reflag_after_user_keeps(cfg, dl, registries, tmp_path):
    """用户在 Web UI 点「是知识，保留」（value_flag=ok）后源发生变化触发重分类：不重新打标。"""
    file = _bm_file(tmp_path, "https://cn.vuejs.org/", "Vue 官网")
    _enable_bookmarks(cfg, file)
    locators, semantics = registries
    run_sync(cfg, dl, locators, semantics)
    e = dl.find_by_canonical("https://cn.vuejs.org/")
    dl.merge_meta(e.id, {"value_flag": "ok"})  # 模拟 UI unflag
    # 源侧变化（改标题）→ updated → 重跑 classify → L0 会再次命中该 URL
    data = json.loads(file.read_text(encoding="utf-8"))
    data["roots"]["bookmark_bar"]["children"][0]["name"] = "Vue 官网（改）"
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    s3 = run_sync(cfg, dl, locators, semantics)["sources"]["bookmarks"]
    assert s3["updated"] == 1
    assert s3["flagged_not_knowledge"] == 0
    assert dl.get_entry(e.id).meta.get("value_flag") == "ok"


# ---------- 4. Web API ----------



@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    """与 test_web_api 同构的测试客户端（fixture 模块级隔离，此处自带）。"""
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_TEST_TOKEN")), "test-token-123")
    locators, semantics = registries
    from fastapi.testclient import TestClient

    from knowatlas.web.app import create_app
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def test_not_knowledge_api_includes_reason(client, dl):
    e = _entry("门户", "https://cn.vuejs.org/")
    dl.upsert_entries([e])
    dl.merge_meta(e.id, {"value_flag": "not_knowledge",
                         "value_flag_reason": "portal_homepage"})
    rows = client.get("/api/not-knowledge").json()["entries"]
    hit = [r for r in rows if r["id"] == e.id]
    assert len(hit) == 1 and hit[0]["reason"] == "portal_homepage"


# ---------- 6. 内容质量守卫 + 补抓失败打标（用户铁律 2026-10-20：不可达/乱码 = 没有知识） ----------


def test_is_garbled_thresholds():
    from knowatlas.semantic.value_guard import is_garbled

    assert not is_garbled("正常的中文正文内容，第二行也有文字。")
    assert not is_garbled("")
    assert is_garbled("abc" * 100 + "\ufffd" * 30)          # 替换符 > 5%
    assert is_garbled("abc" * 100 + "\x00\x01\x02" * 40)    # 控制字符 > 10%


def _file_entry(tmp_path, name: str, data: bytes | None, *, missing: bool = False):
    """造一条 folder file:// 条目；missing=True 时不落盘（模拟文件已删除）。"""
    from knowatlas.models import Entry

    locator = f"file://{name}"
    if not missing and data is not None:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    return Entry.build(source_type="folder", source_key=f"d:/Data/{name}",
                       title=name, locator=locator, locator_canonical=None,
                       native_path=f"D:/Data/{name}", meta={"source_type": "folder"})


def test_fetch_missing_flags_unreachable_and_garbled(cfg, dl, registries, tmp_path, monkeypatch):
    """抓取失败（文件缺失）与乱码正文 → 直接进待清理候选，不中断整轮补抓。"""
    from knowatlas.pipeline.sync import _fetch_missing

    cfg._data.setdefault("sources", {})["folders"] = {"roots": [str(tmp_path)]}
    locators, _ = registries
    e_missing = _file_entry(tmp_path, "没了.md", None, missing=True)
    e_garbled = _file_entry(tmp_path, "乱.txt", b"\x00\x01\x02" * 200)
    e_ok = _file_entry(tmp_path, "好.md", ("# 标题\n\n这是足够长的正常正文内容。" * 20).encode("utf-8"))
    dl.upsert_entries([e_missing, e_garbled, e_ok])

    stats = _fetch_missing(cfg, dl, locators, [e_missing, e_garbled, e_ok], limit=10, run_id="r")
    assert stats["fetched"] == 1 and stats["fetch_failed"] == 2

    m_miss = dl.get_entry(e_missing.id).meta
    assert m_miss["value_flag"] == "not_knowledge" and m_miss["value_flag_reason"] == "unreachable"
    m_gar = dl.get_entry(e_garbled.id).meta
    assert m_gar["value_flag"] == "not_knowledge" and m_gar["value_flag_reason"] == "garbled"
    assert not dl.get_entry(e_garbled.id).inline_content  # 乱码正文不入库不进 FTS
    m_ok = dl.get_entry(e_ok.id).meta
    assert m_ok["fetch_status"] == "ok" and dl.get_entry(e_ok.id).inline_content


def test_fetch_missing_respects_user_veto(cfg, dl, registries, tmp_path):
    """用户已点「是知识，保留」（value_flag=ok）→ 抓取失败不再打标（fetch_status 照记）。"""
    from knowatlas.pipeline.sync import _fetch_missing

    cfg._data.setdefault("sources", {})["folders"] = {"roots": [str(tmp_path)]}
    locators, _ = registries
    e = _file_entry(tmp_path, "珍贵.md", None, missing=True)  # 文件没了但用户想保留条目
    dl.upsert_entries([e])
    dl.merge_meta(e.id, {"value_flag": "ok"})
    _fetch_missing(cfg, dl, locators, [e], limit=10, run_id="r")
    meta = dl.get_entry(e.id).meta
    assert meta["value_flag"] == "ok"  # 否决不被覆盖
    assert meta["fetch_status"] == "unreachable"  # 诊断信息照记
