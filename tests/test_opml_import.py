"""OPML 导入适配器（0.2.0 第五十批）：outline 解析 / 跳过计数 / 错误指路 / 往返回吃。"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowatlas.adapters.opml import collect_opml
from knowatlas.errors import AdapterError


def _enable(cfg, files: list[str]) -> None:
    cfg._data["sources"]["opml"] = {"enabled": True, "files": files}


def _write(tmp_path: Path, name: str, xml: str) -> str:
    file = tmp_path / name
    file.write_text(xml, encoding="utf-8", newline="\n")
    return str(file)


BASIC = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
<head><title>test</title></head>
<body>
  <outline text="技术">
    <outline text="数据库">
      <outline type="link" text="PostgreSQL 教程" htmlUrl="https://www.postgresql.org/docs/"
               created="2020-07-15T10:00:00+08:00"/>
    </outline>
    <outline type="link" htmlUrl="https://sqlite.org/docs.html" created="Tue, 15 Jul 2020 02:00:00 GMT"/>
  </outline>
  <outline text="生活">
    <outline type="link" text="无时间条目" htmlUrl="https://example.org/a?utm_source=x&amp;b=2"/>
  </outline>
</body>
</opml>"""


def test_parse_nested_outline(cfg, tmp_path):
    """TODO 挂账探针：outline 嵌套=native_path；created ISO/RFC822/缺失三态。"""
    _enable(cfg, [_write(tmp_path, "a.opml", BASIC)])
    out = collect_opml(cfg)
    assert len(out.entries) == 3
    # canonical 五步规范化含去尾斜杠/去跟踪参数/去 fragment——key 用规范化后 URL
    by_url = {e.locator_canonical: e for e in out.entries}
    pg = by_url["https://www.postgresql.org/docs"]
    assert pg.native_path == "技术/数据库"
    assert pg.title == "PostgreSQL 教程"
    assert pg.source_type == "opml"
    assert pg.created_at is not None and pg.created_at.startswith("2020-07-15T")
    # 无 text 属性 → title 属性也行；本例无 title → canonical 兜底做标题
    sq = by_url["https://sqlite.org/docs.html"]
    assert sq.native_path == "技术"
    assert sq.created_at is not None  # RFC 822 解析成功（时区换算后日期不变）
    assert sq.created_at.startswith("2020-07-15T")
    # 无 created → NULL 不臆造；canonical 五步规范化去跟踪参数
    ex = by_url["https://example.org/a?b=2"]
    assert ex.created_at is None
    assert ex.native_path == "生活"


def test_skips_non_http_rss_and_counts_duplicates(cfg, tmp_path):
    """非 http 跳过、rss 订阅源跳过、同 URL 两分支各建一条且计数。"""
    xml = """<opml version="2.0"><body>
      <outline text="工具">
        <outline type="link" text="本地文件" htmlUrl="ftp://files.example.com/x"/>
        <outline type="rss" text="某博客" xmlUrl="https://blog.example.com/feed.xml"/>
        <outline type="link" text="文章A" htmlUrl="https://site.com/p/1"/>
        <outline text="备份目录">
          <outline type="link" text="文章A副本" htmlUrl="https://site.com/p/1#top"/>
        </outline>
      </outline>
    </body></opml>"""
    _enable(cfg, [_write(tmp_path, "s.opml", xml)])
    out = collect_opml(cfg)
    assert len(out.entries) == 2                       # 仅两个 http 条目
    assert {e.native_path for e in out.entries} == {"工具", "工具/备份目录"}
    stats = out.stats
    assert stats["skipped_non_http"] == 1
    assert stats["skipped_rss"] == 1
    assert stats["duplicate_urls"] == 1                # canonical 归一后与文章A重复


def test_errors_point_to_config(cfg, tmp_path):
    """路径缺失/坏 XML/缺 body/files 空——AdapterError 且 hint 指路配置项。"""
    _enable(cfg, [str(tmp_path / "nope.opml")])
    with pytest.raises(AdapterError) as ei:
        collect_opml(cfg)
    assert "[sources.opml]" in ei.value.hint

    _enable(cfg, [_write(tmp_path, "bad.opml", "<opml><body><outline>")])
    with pytest.raises(AdapterError):
        collect_opml(cfg)

    _enable(cfg, [_write(tmp_path, "nobody.opml", "<opml version='2.0'><head/></opml>")])
    with pytest.raises(AdapterError) as ei2:
        collect_opml(cfg)
    assert "body" in str(ei2.value)

    cfg._data["sources"]["opml"] = {"enabled": True, "files": []}
    with pytest.raises(AdapterError) as ei3:
        collect_opml(cfg)
    assert "files" in str(ei3.value)


def test_roundtrip_from_export(dl, cfg, tmp_path):
    """往返保真回吃：kexport --format opml 产物 → collect_opml，http 叶子对账。"""
    from knowatlas.models import Entry
    from knowatlas.pipeline.export import export_opml

    tech = dl.create_category("技术", [], "manual")
    db = dl.create_category("数据库", [tech.id], "manual")
    rows = [
        Entry.build(source_type="bookmark", source_key="bm:1", title="消息总线入门",
                    locator="https://mq.com/1", locator_canonical="https://mq.com/1",
                    created_at="2020-07-15T10:00:00+08:00", meta={}),
        Entry.build(source_type="bookmark", source_key="bm:2", title="分布式事务",
                    locator="https://dist.com/2", locator_canonical="https://dist.com/2",
                    meta={}),
        Entry.build(source_type="manual", source_key="m:1", title="未归类页",
                    locator="https://loose.com/3", locator_canonical="https://loose.com/3",
                    meta={}),
    ]
    dl.upsert_entries(rows)
    dl.attach_category(rows[0].id, db.id, 0.9, "rule", "t-opml")
    dl.attach_category(rows[1].id, tech.id, 0.9, "rule", "t-opml")
    # rows[2] 故意不挂分类 → 导出落「（未分类）」根

    out_file = tmp_path / "roundtrip.opml"
    export_opml(dl, out_file)
    _enable(cfg, [str(out_file)])
    back = collect_opml(cfg)
    assert back.stats["skipped_non_http"] == 0
    # http canonical 叶子集合与库内一致（三分类路径 + 未分类根各条目）
    urls = {e.locator_canonical for e in back.entries}
    assert urls == {"https://mq.com/1", "https://dist.com/2", "https://loose.com/3"}
    by_url = {e.locator_canonical: e for e in back.entries}
    assert by_url["https://mq.com/1"].native_path == "技术/数据库"
    assert by_url["https://mq.com/1"].created_at is not None  # 导出 created 属性回吃
    assert by_url["https://dist.com/2"].native_path == "技术"
    # 未分类落「（未分类）」根（导出契约），回吃后进 native_path
    assert by_url["https://loose.com/3"].native_path == "（未分类）"
