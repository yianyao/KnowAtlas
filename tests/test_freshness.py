"""时效守卫测试（0.2.0 第四十一批）：纯规则信号 + 只标不删 + 否决不翻转。"""

from __future__ import annotations

from knowatlas.models import Entry
from knowatlas.pipeline.sync import _freshness_scan
from knowatlas.semantic.freshness import extract_latest_year, judge_text, title_key


def make_entry(**overrides) -> Entry:
    defaults = dict(
        source_type="manual", source_key="https://e.com/a",
        title="示例标题", locator="https://e.com/a",
        locator_canonical="https://e.com/a",
        meta={"source_type": "manual"},
    )
    defaults.update(overrides)
    return Entry.build(**defaults)


# ---- 探针①：废弃关键词 → stale/keyword ----

def test_keyword_title_stale():
    assert judge_text("XX 框架 已废弃，请用 YY", "正文") == ("stale", "keyword")
    assert judge_text("Setup Guide (deprecated)", "body") == ("stale", "keyword")


def test_keyword_body_self_declare_stale():
    # 正文自述句式（防误杀：「token 过期时间」这类技术语义不触发）
    assert judge_text("使用指南", "本文已过期，请参考最新版本。") == ("stale", "keyword")
    assert judge_text("使用指南", "This page is outdated and no longer maintained.") == ("stale", "keyword")
    assert judge_text("缓存配置", "设置 token 过期时间为 3600 秒。") is None
    assert judge_text("发布说明", "此版本废弃了旧的 API。") is None  # 正文裸提及不触发


# ---- 探针②：正文日期过旧 → suspect/date_old ----

def test_date_old_suspect():
    body = "教程内容。最后更新于 2021-05-12。"
    assert judge_text("教程", body, stale_years=3, now_year=2026) == ("suspect", "date_old")
    # 近年更新过不算旧
    assert judge_text("教程", "内容。最后更新于 2025-01-01。", stale_years=3, now_year=2026) is None
    # 无日期信息不判
    assert judge_text("教程", "没有日期的正文。", now_year=2026) is None


def test_extract_latest_year():
    assert extract_latest_year("发布于 2019-03-01，最后更新于 2022-07-04。") == 2022
    assert extract_latest_year("© 2018 Acme") == 2018
    assert extract_latest_year("Copyright (c) 2020 Someone") == 2020
    assert extract_latest_year("2021/5/2 记录") == 2021
    assert extract_latest_year("没有日期") is None
    # 版权预检不命中时不提裸四位数字（防误报）
    assert extract_latest_year("开会聊 2020 年规划") is None


def test_title_key_clusters_versions():
    assert title_key("Python 3.6 教程") == title_key("Python 3.12 教程")
    assert title_key("Hello, World!") == title_key("hello world")
    assert title_key("") == ""


# ---- 扫描编排：入库条目打标 + 聚类 + 否决不翻转 ----

def _seed(dl, entries):
    dl.upsert_entries(entries)


def test_scan_marks_keyword_and_date(dl):
    _seed(dl, [
        make_entry(source_key="m:1", title="老工具 已废弃",
                   locator="https://a.com/old", locator_canonical="https://a.com/old"),
        make_entry(source_key="m:2", title="很老的教程",
                   locator="https://b.com/tut", locator_canonical="https://b.com/tut",
                   inline_content="内容。最后更新于 2020-01-01。"),
        make_entry(source_key="m:3", title="新鲜教程",
                   locator="https://c.com/tut", locator_canonical="https://c.com/tut",
                   inline_content="内容。最后更新于 2025-06-01。"),
    ])
    stats = _freshness_scan(dl, dry_run=False)
    e1 = [e for e in dl.list_entries(limit=100) if e.title == "老工具 已废弃"][0]
    e1 = dl.get_entry(e1.id)
    assert e1.meta["freshness_flag"] == "stale"
    assert e1.meta["freshness_reason"] == "keyword"
    e2 = [e for e in dl.list_entries(limit=100) if e.title == "很老的教程"][0]
    assert e2.meta["freshness_flag"] == "suspect"
    assert e2.meta["freshness_reason"] == "date_old"
    e3 = [e for e in dl.list_entries(limit=100) if e.title == "新鲜教程"][0]
    assert "freshness_flag" not in e3.meta


def test_scan_dry_run_writes_nothing(dl):
    _seed(dl, [make_entry(source_key="m:1", title="已废弃的页面",
                          locator="https://a.com/x", locator_canonical="https://a.com/x")])
    stats = _freshness_scan(dl, dry_run=True)
    assert stats["stale"] == 1 and stats["dry_run"] is True
    e = dl.list_entries(limit=10)[0]
    assert "freshness_flag" not in e.meta


def test_scan_newer_version_marks_older_only(dl):
    # 同 host 同主题（去版本号后同键）新旧并存 → 旧的 suspect/newer_version
    _seed(dl, [
        make_entry(source_key="m:1", title="Python 3.6 入门",
                   locator="https://docs.com/py36", locator_canonical="https://docs.com/py36",
                   inline_content="入门内容。", created_at="2024-01-01T00:00:00+08:00"),
        make_entry(source_key="m:2", title="Python 3.12 入门",
                   locator="https://docs.com/py312", locator_canonical="https://docs.com/py312",
                   inline_content="入门内容（新）。", created_at="2025-06-01T00:00:00+08:00"),
    ])
    stats = _freshness_scan(dl, dry_run=False)
    assert stats["by_reason"].get("newer_version") == 1
    old = [e for e in dl.list_entries(limit=100) if "3.6" in e.title][0]
    new = [e for e in dl.list_entries(limit=100) if "3.12" in e.title][0]
    assert old.meta["freshness_flag"] == "suspect"
    assert old.meta["freshness_reason"] == "newer_version"
    assert "freshness_flag" not in new.meta


def test_veto_survives_rescan(dl):
    # 探针④：freshness_flag=ok（用户否决）后二次扫描不翻转
    _seed(dl, [make_entry(source_key="m:1", title="已过时的手册",
                          locator="https://a.com/m", locator_canonical="https://a.com/m")])
    _freshness_scan(dl, dry_run=False)
    e = dl.list_entries(limit=10)[0]
    assert e.meta["freshness_flag"] == "stale"
    dl.merge_meta(e.id, {"freshness_flag": "ok"})
    stats2 = _freshness_scan(dl, dry_run=False)
    assert stats2["stale"] == 0
    assert dl.get_entry(e.id).meta["freshness_flag"] == "ok"


def test_scan_skips_cleanup_and_dead(dl):
    # 已在待清理候选 / 已死链的条目不重复打标（更优先的清理通道已承接）
    _seed(dl, [
        make_entry(source_key="m:1", title="已废弃门户",
                   locator="https://a.com/", locator_canonical=None,
                   meta={"source_type": "manual", "value_flag": "not_knowledge"}),
        make_entry(source_key="m:2", title="已废弃手册",
                   locator="https://a.com/m", locator_canonical="https://a.com/m",
                   meta={"source_type": "manual", "link_status": "dead"}),
    ])
    stats = _freshness_scan(dl, dry_run=False)
    assert stats["stale"] == 0 and stats["suspect"] == 0


# ---- 消费面：stale 退出、suspect 保留 ----

def test_stale_excluded_from_consumption(dl):
    _seed(dl, [
        make_entry(source_key="m:1", title="已废弃的指南",
                   locator="https://a.com/g", locator_canonical="https://a.com/g",
                   inline_content="指南正文标记词here。"),
        make_entry(source_key="m:2", title="老教程",
                   locator="https://b.com/t", locator_canonical="https://b.com/t",
                   inline_content="老教程正文标记词here。最后更新于 2020-01-01。"),
    ])
    _freshness_scan(dl, dry_run=False)
    stale_e = [e for e in dl.list_entries(limit=100) if e.title == "已废弃的指南"][0]
    suspect_e = [e for e in dl.list_entries(limit=100) if e.title == "老教程"][0]
    assert stale_e.meta["freshness_flag"] == "stale"
    assert suspect_e.meta["freshness_flag"] == "suspect"
    # 消费读路径（search_fts）实测：stale 不可见、suspect 照常可检索
    hits = {h.entry_id: h for h in dl.search_fts("标记词", limit=20)}
    assert stale_e.id not in hits
    assert suspect_e.id in hits
    # 时效候选管理视图照常全量列出（守卫只挡消费，不挡管理）
    assert stale_e.id in [e.id for e in dl.list_by_freshness_flag("stale")]
    assert suspect_e.id in [e.id for e in dl.list_by_freshness_flag("suspect")]
