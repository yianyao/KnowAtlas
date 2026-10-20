"""书签适配器与 ksync 全量遍历同步（完整方案 §12 步骤 9，TODO Phase 1 探针）。

探针：fixture 书签 JSON → 条目数、native_path 与收藏夹层级一致。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowatlas.adapters.bookmark import collect_bookmarks
from knowatlas.errors import AdapterError
from knowatlas.pipeline.sync import run_sync


@pytest.fixture
def bookmarks_json() -> dict:
    """覆盖：嵌套文件夹、非 http URL、无 id 节点、跨文件夹重复 URL、未知类型。"""
    return {
        "version": 1,
        "roots": {
            "bookmark_bar": {
                "type": "folder", "name": "书签栏", "id": "1",
                "children": [
                    {"type": "url", "id": "10", "name": "SQLite 官方文档",
                     "url": "https://sqlite.org/docs.html", "date_added": "13350000000000000"},
                    {"type": "folder", "id": "2", "name": "技术", "children": [
                        {"type": "folder", "id": "3", "name": "数据库", "children": [
                            {"type": "url", "id": "11", "name": "PostgreSQL 教程",
                             "url": "https://www.postgresql.org/docs/", "date_added": "13350000000000001"},
                            # 无 id 节点：source_key 走「路径+标题」兜底
                            {"type": "url", "name": "Redis 快速上手",
                             "url": "https://redis.io/docs/", "date_added": "bad-ts"},
                            # 非 http URL：跳过并计数
                            {"type": "url", "id": "12", "name": "Chrome 设置",
                             "url": "chrome://settings/", "date_added": "13350000000000002"},
                        ]},
                    ]},
                    # 跨文件夹重复 URL（canonical 与 10 相同）
                    {"type": "url", "id": "13", "name": "SQLite 文档副本",
                     "url": "https://sqlite.org/docs.html#top", "date_added": "13350000000000003"},
                    # 未知类型：计数跳过
                    {"type": "magic", "id": "99", "name": "?"},
                ],
            },
            "other": {"type": "folder", "name": "其他书签", "id": "4", "children": [
                {"type": "url", "id": "14", "name": "另一条",
                 "url": "https://example.org/a?utm_source=x&b=2", "date_added": "13350000000000004"},
            ]},
            "synced": {"type": "folder", "name": "移动设备书签", "id": "5", "children": []},
        },
    }


def _write(tmp_path: Path, data: dict) -> Path:
    file = tmp_path / "Bookmarks"
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    return file


def _enable(cfg, file: Path) -> None:
    cfg._data["sources"]["bookmarks"] = {
        "enabled": True, "browsers": ["edge"], "paths": {"edge": str(file)},
    }


# ---------- 适配器层 ----------

def test_collect_entry_count_and_native_path(cfg, tmp_path, bookmarks_json):
    """TODO 探针：条目数、native_path 与收藏夹层级一致。"""
    _enable(cfg, _write(tmp_path, bookmarks_json))
    out = collect_bookmarks(cfg)
    # 6 个 url 节点 − 1 个 chrome:// = 5 条
    assert len(out.entries) == 5
    by_title = {e.title: e for e in out.entries}
    assert by_title["PostgreSQL 教程"].native_path == "书签栏/技术/数据库"
    assert by_title["SQLite 官方文档"].native_path == "书签栏"
    assert by_title["另一条"].native_path == "其他书签"
    stats = out.stats
    assert stats["skipped_non_http"] == 1
    assert stats["skipped_other"] == 1
    assert stats["duplicate_urls"] == 1
    assert stats["browsers_ok"] == ["edge"]


def test_collect_source_key_and_canonical(cfg, tmp_path, bookmarks_json):
    _enable(cfg, _write(tmp_path, bookmarks_json))
    out = collect_bookmarks(cfg)
    by_title = {e.title: e for e in out.entries}
    # 有 id：source_key = 浏览器名:节点id
    assert by_title["PostgreSQL 教程"].meta["source_type"] == "bookmark"
    assert by_title["SQLite 官方文档"].id  # 存在即可；具体值由 ids.entry_id 决定
    # 无 id 兜底 key 不与有 id 的冲突且含路径
    redis = by_title["Redis 快速上手"]
    assert redis.native_path == "书签栏/技术/数据库"
    # canonical 五步规范化：去 fragment、去跟踪参数
    assert by_title["SQLite 文档副本"].locator_canonical == "https://sqlite.org/docs.html"
    assert by_title["另一条"].locator_canonical == "https://example.org/a?b=2"
    # WebKit 时间戳转换；坏时间戳 → None
    assert by_title["SQLite 官方文档"].created_at is not None
    assert redis.created_at is None


def test_collect_missing_file_raises(cfg, tmp_path):
    cfg._data["sources"]["bookmarks"] = {
        "enabled": True, "browsers": ["edge"],
        "paths": {"edge": str(tmp_path / "nope" / "Bookmarks")},
    }
    with pytest.raises(AdapterError):
        collect_bookmarks(cfg)


def test_collect_corrupt_file_raises(cfg, tmp_path):
    file = tmp_path / "Bookmarks"
    file.write_text("{ not json", encoding="utf-8")
    _enable(cfg, file)
    with pytest.raises(AdapterError):
        collect_bookmarks(cfg)


# ---------- 同步编排层 ----------

def test_sync_bookmarks_end_to_end(cfg, dl, registries, tmp_path, bookmarks_json):
    """首跑：全建 + 分类挂接；二跑：幂等 unchanged；full 删除检测。"""
    _enable(cfg, _write(tmp_path, bookmarks_json))
    locators, semantics = registries

    stats = run_sync(cfg, dl, locators, semantics, full=True)
    src = stats["sources"]["bookmarks"]
    assert src["entries"] == 5 and src["created"] == 5 and src["archived"] == 0
    # 「PostgreSQL 教程」标题命中规则关键词 postgres → 技术开发/数据库
    assert src["classified"] >= 1
    # FTS 消费面守卫（第三十六批）：SQLite 条目（内容页，未打标）可检索；
    # PostgreSQL/Redis 的 /docs/ 尾斜杠目录页被 L0 守卫打 not_knowledge → 不进消费页
    sq = [e for e in dl.search_fts("SQLite") if e.title == "SQLite 官方文档"]
    assert sq, "未打标条目应可被 FTS 检索到"
    assert not [e for e in dl.search_fts("PostgreSQL") if e.title == "PostgreSQL 教程"]
    assert [e for e in dl.list_by_value_flag("not_knowledge") if e.title == "PostgreSQL 教程"]

    # 二跑幂等：无新建、无归档
    stats2 = run_sync(cfg, dl, locators, semantics, full=True)
    src2 = stats2["sources"]["bookmarks"]
    assert src2["created"] == 0 and src2["unchanged"] == 5 and src2["archived"] == 0

    # 删除检测：书签文件里移除一条后 full 同步 → archived
    data = json.loads(json.dumps(bookmarks_json))
    bar_children = data["roots"]["bookmark_bar"]["children"]
    bar_children[:] = [c for c in bar_children if c.get("id") != "13"]
    _enable(cfg, _write(tmp_path, data))
    stats3 = run_sync(cfg, dl, locators, semantics, full=True)
    assert stats3["sources"]["bookmarks"]["archived"] == 1
    # 归档条目不物理删除（被移除的是 id=13 副本；canonical 相同的主条目仍 active）
    removed = dl.find_by_locator("https://sqlite.org/docs.html#top")
    assert removed and removed[0].status == "archived"
    kept = dl.find_by_canonical("https://sqlite.org/docs.html")
    assert kept is not None and kept.status == "active"


def test_sync_dry_run_writes_nothing(cfg, dl, registries, tmp_path, bookmarks_json):
    _enable(cfg, _write(tmp_path, bookmarks_json))
    stats = run_sync(cfg, dl, registries[0], registries[1], dry_run=True)
    assert stats["sources"]["bookmarks"]["reachable"] is True
    assert stats["sources"]["bookmarks"]["entry_count"] == 5
    assert dl.search_fts("SQLite") == []


def test_sync_source_error_isolated(cfg, dl, registries, tmp_path, bookmarks_json):
    """书签文件缺失 → 该源记 error，同步不崩。"""
    cfg._data["sources"]["bookmarks"] = {
        "enabled": True, "browsers": ["edge"],
        "paths": {"edge": str(tmp_path / "missing")},
    }
    stats = run_sync(cfg, dl, registries[0], registries[1])
    assert "error" in stats["sources"]["bookmarks"]


def test_sync_disabled_and_unknown_source(cfg, dl, registries, bookmarks_json, tmp_path):
    """未启用 → note 提示；--source 过滤未知源 → 空统计。"""
    _write(tmp_path, bookmarks_json)
    stats = run_sync(cfg, dl, registries[0], registries[1])
    assert "note" in stats
    stats2 = run_sync(cfg, dl, registries[0], registries[1], source="bilibili")
    assert stats2["sources"] == {}


def test_sync_updated_entry_reclassify(cfg, dl, registries, tmp_path, bookmarks_json):
    """更新闭环：书签移动文件夹 → native_path 变化 → 旧机器分类被替换为新先验分类。"""
    _enable(cfg, _write(tmp_path, bookmarks_json))
    locators, semantics = registries
    run_sync(cfg, dl, locators, semantics)

    # 「SQLite 官方文档」原在书签栏（无先验映射）→ 移入 技术开发/数据库 映射路径并改标题
    data = json.loads(json.dumps(bookmarks_json))
    bar_children = data["roots"]["bookmark_bar"]["children"]
    moved = next(c for c in bar_children if c.get("id") == "10")
    bar_children.remove(moved)
    tech = next(c for c in bar_children if c.get("id") == "2")
    db_folder = next(c for c in tech["children"] if c.get("id") == "3")
    db_folder["children"].append(
        {"type": "url", "id": "10", "name": "PostgreSQL 官方文档",
         "url": "https://sqlite.org/docs.html", "date_added": "13350000000000000"})
    _enable(cfg, _write(tmp_path, data))
    stats = run_sync(cfg, dl, locators, semantics, full=True)
    src = stats["sources"]["bookmarks"]
    assert src["updated"] >= 1 and src["reclassified"] >= 1

    entry = dl.find_by_canonical("https://sqlite.org/docs.html")
    links = dl.get_entry_categories(entry.id)
    assert any(l["path"] == "技术开发/数据库" for l in links), "新 native_path 先验应命中"
    # 旧机器分类不残留（书签栏无映射，本来就没有挂接；若有也已被 detach）


def test_sync_revives_archived_entry(cfg, dl, registries, tmp_path, bookmarks_json):
    """老化后复活：归档条目重新出现在源里 → full 同步恢复 active。"""
    _enable(cfg, _write(tmp_path, bookmarks_json))
    locators, semantics = registries
    run_sync(cfg, dl, locators, semantics)  # 首次入库（含 id=13）
    # 删除 id=13 → archived
    data = json.loads(json.dumps(bookmarks_json))
    bar = data["roots"]["bookmark_bar"]["children"]
    bar[:] = [c for c in bar if c.get("id") != "13"]
    _enable(cfg, _write(tmp_path, data))
    run_sync(cfg, dl, locators, semantics, full=True)
    removed = dl.find_by_locator("https://sqlite.org/docs.html#top")
    assert removed and removed[0].status == "archived"
    # 重新出现 → 恢复 active
    _enable(cfg, _write(tmp_path, bookmarks_json))
    run_sync(cfg, dl, locators, semantics, full=True)
    back = dl.find_by_locator("https://sqlite.org/docs.html#top")
    assert back and back[0].status == "active"
