"""文件夹适配器与 folders 源同步（完整方案 §12 步骤 10，TODO Phase 1 探针）。

探针：嵌套目录路径正确进入 native_path。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowatlas.adapters.folder import collect_folders
from knowatlas.errors import AdapterError
from knowatlas.pipeline.sync import run_sync


@pytest.fixture
def folder_tree(tmp_path: Path) -> Path:
    """嵌套目录：多级子目录 + 多类型文件 + 隐藏/临时/无后缀。"""
    root = tmp_path / "办公文档"
    (root / "ERP").mkdir(parents=True)
    (root / "ERP" / "报表").mkdir()
    (root / "笔记.txt").write_text("hello", encoding="utf-8", newline="\n")
    (root / "ERP" / "进销存.xlsx").write_bytes(b"fake xlsx")
    (root / "ERP" / "报表" / "2026年报.pdf").write_bytes(b"fake pdf")
    (root / "ERP" / "报表" / "README.md").write_text("# md", encoding="utf-8", newline="\n")
    (root / "无后缀文件").write_bytes(b"?")
    (root / ".隐藏文件").write_text("hide", encoding="utf-8")
    (root / "~$临时.docx").write_bytes(b"tmp")
    return root


def _enable(cfg, root: Path) -> None:
    cfg._data["sources"]["folders"] = {"enabled": True, "roots": [str(root)]}


def test_collect_native_path_and_kind(cfg, folder_tree):
    """TODO 探针：嵌套目录路径正确进入 native_path；文档/PDF/其他分类标记。"""
    _enable(cfg, folder_tree)
    out = collect_folders(cfg)
    by_key = {e.locator: e for e in out.entries}
    # 5 个真实文件（隐藏 + Office 临时跳过）
    assert len(out.entries) == 5
    assert by_key["file://笔记.txt"].native_path == "办公文档"
    assert by_key["file://ERP/进销存.xlsx"].native_path == "办公文档/ERP"
    assert by_key["file://ERP/报表/2026年报.pdf"].native_path == "办公文档/ERP/报表"
    # 分类标记
    assert by_key["file://笔记.txt"].meta["file_kind"] == "document"
    assert by_key["file://ERP/进销存.xlsx"].meta["file_kind"] == "office"
    assert by_key["file://ERP/报表/2026年报.pdf"].meta["file_kind"] == "pdf"
    assert by_key["file://无后缀文件"].meta["file_kind"] == "other"
    # locator 规范
    assert by_key["file://笔记.txt"].locator_canonical is None
    assert by_key["file://ERP/进销存.xlsx"].meta["source_type"] == "folder"
    # 跳过计数
    assert out.stats["skipped_hidden"] == 2
    assert out.stats["roots_ok"] == ["办公文档"]


def test_collect_missing_root_raises(cfg, tmp_path):
    cfg._data["sources"]["folders"] = {"enabled": True,
                                       "roots": [str(tmp_path / "不存在")]}
    with pytest.raises(AdapterError):
        collect_folders(cfg)


def test_collect_filters(cfg, folder_tree, tmp_path):
    """过滤规则：exclude_globs 黑名单 + include_exts 白名单；被排除文件不进删除检测。"""
    (folder_tree / "cj_session1abc").write_bytes(b"junk")      # 无扩展名会话数据
    _enable(cfg, folder_tree)
    cfg._data["sources"]["folders"].update({
        "exclude_globs": ["cj_session*", "README*"],
        "include_exts": [".txt", ".pdf", ".xlsx"],
    })
    out = collect_folders(cfg)
    keys = {e.locator.removeprefix("file://") for e in out.entries}    # include_exts 白名单：txt/pdf/xlsx 保留，md 被排除
    assert keys == {"笔记.txt", "ERP/进销存.xlsx", "ERP/报表/2026年报.pdf"}
    assert out.stats["skipped_excluded"] == 2   # cj_session1abc + README.md
    assert out.stats["skipped_ext"] == 1        # 无后缀文件


def test_sync_folders_end_to_end(cfg, dl, registries, tmp_path, folder_tree):
    """首跑入库 + 分类；二跑幂等；full 删除检测（文件删除 → archived）。"""
    _enable(cfg, folder_tree)
    locators, semantics = registries
    stats = run_sync(cfg, dl, locators, semantics, full=True)
    src = stats["sources"]["folders"]
    assert src["entries"] == 5 and src["created"] == 5 and src["archived"] == 0
    # 二跑幂等
    stats2 = run_sync(cfg, dl, locators, semantics, full=True)
    assert stats2["sources"]["folders"]["unchanged"] == 5
    # 删除一个文件 → full 同步归档
    (folder_tree / "ERP" / "进销存.xlsx").unlink()
    stats3 = run_sync(cfg, dl, locators, semantics, full=True)
    assert stats3["sources"]["folders"]["archived"] == 1
    gone = dl.find_by_locator("file://ERP/进销存.xlsx")
    assert gone and gone[0].status == "archived"


def test_fetch_limit_reads_file_content(cfg, dl, registries, tmp_path, folder_tree):
    """--fetch-limit 对 file:// 条目生效：txt 直读正文入 content_store 并参与分类。"""
    _enable(cfg, folder_tree)
    locators, semantics = registries
    run_sync(cfg, dl, locators, semantics)
    stats = run_sync(cfg, dl, locators, semantics, fetch_limit=5)
    src = stats["sources"]["folders"]
    assert src.get("fetched", 0) >= 1
    # txt/md 正文已入 content_store（xlsx/pdf 假文件解析失败计 fetch_failed）
    e = dl.get_entry(dl.find_by_locator("file://笔记.txt")[0].id)
    assert e.content_hash and dl.get_content(e.content_hash) == "hello"


def test_max_entries_config(cfg, folder_tree):
    """max_entries 上限可配置：截断计数进 stats.truncated；<=0 视为不限。"""
    _enable(cfg, folder_tree)
    cfg._data["sources"]["folders"]["max_entries"] = 2
    out = collect_folders(cfg)
    assert len(out.entries) == 2 and out.stats["truncated"] == 3
    cfg._data["sources"]["folders"]["max_entries"] = 0
    out0 = collect_folders(cfg)
    assert len(out0.entries) == 5 and out0.stats.get("truncated", 0) == 0


def test_exclude_dirs_pruning(cfg, folder_tree):
    """目录级排除：目录名匹配与相对路径模式都命中，被排除目录整棵剪枝不建条目。"""
    (folder_tree / "Fiction").mkdir()
    (folder_tree / "Fiction" / "章节.txt").write_text("f", encoding="utf-8", newline="\n")
    (folder_tree / "项目资料").mkdir()
    (folder_tree / "项目资料" / "旧版_备份").mkdir()
    (folder_tree / "项目资料" / "旧版_备份" / "归档.md").write_text("b", encoding="utf-8", newline="\n")
    _enable(cfg, folder_tree)
    # 目录名匹配 + 相对路径通配，两种写法都支持
    cfg._data["sources"]["exclude_dirs"] = ["Fiction", "项目资料/*_备份"]
    out = collect_folders(cfg)
    locs = {e.locator for e in out.entries}
    assert not any(l.startswith("file://Fiction/") for l in locs)
    assert not any(l.startswith("file://项目资料/旧版_备份/") for l in locs)
    assert "file://笔记.txt" in locs
    assert out.stats["skipped_dir"] == 2
    # 源级追加项也生效
    cfg._data["sources"]["exclude_dirs"] = []
    cfg._data["sources"]["folders"]["exclude_dirs"] = ["ERP/报表"]
    out2 = collect_folders(cfg)
    locs2 = {e.locator for e in out2.entries}
    assert "file://ERP/进销存.xlsx" in locs2
    assert "file://ERP/报表/2026年报.pdf" not in locs2
