"""万兴脑图适配器（source_type=emmx）：合成 fixture 测试。

真实 .emmx 样本验收探针（解析出中心主题与主分支）待用户提供文件后补测。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from knowatlas.adapters.emmx import collect_emmx
from knowatlas.errors import AdapterError
from knowatlas.pipeline.sync import run_sync

_CONTENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sheet xmlns="http://www.wondershare.com/mindmaster">
  <topic id="1" title="文学创作">
    <children>
      <topics>
        <topic id="2" title="小说">
          <children>
            <topics>
              <topic id="3" title="对话描写技巧"/>
            </topics>
          </children>
        </topic>
        <topic id="4" title="散文"/>
      </topics>
    </children>
  </topic>
</sheet>""".encode("utf-8")


@pytest.fixture
def emmx_tree(tmp_path: Path) -> Path:
    root = tmp_path / "脑图库"
    root.mkdir()
    with zipfile.ZipFile(root / "创作脑图.emmx", "w") as zf:
        zf.writestr("content.xml", _CONTENT_XML)
    (root / "子目录").mkdir()
    with zipfile.ZipFile(root / "子目录" / "坏文件.emmx", "w") as zf:
        zf.writestr("page.bin", b"\x00\x01binary")  # 无 content.xml → 降级
    (root / "坏zip.emmx").write_bytes(b"not a zip")
    return root


def _enable(cfg, root: Path) -> None:
    cfg._data["sources"]["emmx"] = {"enabled": True, "roots": [str(root)]}


def test_collect_topics(cfg, emmx_tree):
    """结构化解析：topic 树 → 条目；mind_path 层级正确；source_key=路径#节点id。"""
    _enable(cfg, emmx_tree)
    out = collect_emmx(cfg)
    by_loc = {e.locator: e for e in out.entries}
    # 4 个 topic 节点 + 2 个降级文件条目
    assert len(out.entries) == 6
    assert out.stats["degraded_files"] == 2
    node = by_loc["emmx://创作脑图.emmx#3"]
    assert node.title == "对话描写技巧"
    assert node.native_path == "脑图库"
    assert node.meta["mind_path"] == "文学创作/小说/对话描写技巧"
    assert node.meta["depth"] == 3
    assert by_loc["emmx://创作脑图.emmx#4"].meta["mind_path"] == "文学创作/散文"


def test_degraded_files(cfg, emmx_tree):
    """无 content.xml / 坏 zip → 标题级单条目，degraded=true。"""
    _enable(cfg, emmx_tree)
    out = collect_emmx(cfg)
    by_loc = {e.locator: e for e in out.entries}
    bad = by_loc["emmx://子目录/坏文件.emmx#file"]
    assert bad.meta["degraded"] is True
    assert bad.title == "坏文件"
    assert bad.native_path == "脑图库/子目录"
    assert by_loc["emmx://坏zip.emmx#file"].meta["degraded"] is True


def test_missing_root_raises(cfg, tmp_path):
    cfg._data["sources"]["emmx"] = {"enabled": True, "roots": [str(tmp_path / "无")]}
    with pytest.raises(AdapterError):
        collect_emmx(cfg)


def test_sync_emmx_end_to_end(cfg, dl, registries, tmp_path, emmx_tree):
    _enable(cfg, emmx_tree)
    locators, semantics = registries
    stats = run_sync(cfg, dl, locators, semantics, full=True)
    src = stats["sources"]["emmx"]
    assert src["entries"] == 6 and src["created"] == 6
    # 二跑幂等
    stats2 = run_sync(cfg, dl, locators, semantics, full=True)
    assert stats2["sources"]["emmx"]["unchanged"] == 6
