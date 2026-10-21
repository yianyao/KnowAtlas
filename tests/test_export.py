"""导出格式测试（0.2.0 第四十五批，M5）：JSON/Obsidian/OPML 三格式探针 + CLI 冒烟。"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from knowatlas.models import Entry


def _entry(**overrides) -> Entry:
    defaults = dict(
        source_type="bookmark", source_key="https://x.com/a",
        title="示例", locator="https://x.com/a",
        locator_canonical="https://x.com/a",
        meta={"source_type": "bookmark"},
    )
    defaults.update(overrides)
    return Entry.build(**defaults)


def _seed_library(dl):
    """技术 > 消息队列 / 技术 > 分布式（消息队列多父：分布式 > 消息队列）；
    生活（顶层）。条目含 http / file / mail 三类 locator + archived 一条。"""
    tech = dl.create_category("技术", [], "manual")
    dist = dl.create_category("分布式", [tech.id], "manual")
    mq = dl.create_category("消息队列", [tech.id, dist.id], "manual")  # 多父
    life = dl.create_category("生活", [], "manual")
    entries = [
        _entry(source_key="bm:1", title="消息总线入门", locator="https://mq.com/1",
               locator_canonical="https://mq.com/1",
               inline_content="路由与过滤实践。",
               created_at="2020-07-15T10:00:00+08:00"),
        _entry(source_key="bm:2", title="分布式事务", locator="https://dist.com/2",
               locator_canonical="https://dist.com/2",
               inline_content="2PC 与 TCC 对比。",
               created_at="2026-01-02T10:00:00+08:00"),
        _entry(source_key="bm:3", title="本地手册", locator="file:///D:/docs/a.html",
               locator_canonical=None, inline_content="本地文件。"),
        _entry(source_key="mail:1", title="会议纪要", locator="mail://work/abc",
               locator_canonical=None, inline_content="邮件正文。"),
        _entry(source_key="bm:4", title="旧弃页", locator="https://old.com/4",
               locator_canonical="https://old.com/4", status="archived",
               inline_content="已归档。"),
    ]
    dl.upsert_entries(entries)
    for e, cid in ((entries[0], mq.id), (entries[0], dist.id),  # e1 多父挂接
                   (entries[1], dist.id),
                   (entries[2], life.id), (entries[3], life.id),
                   (entries[4], life.id)):
        dl.attach_category(e.id, cid, 0.9, "rule", "t-export")
    dl.attach_locator(entries[0].id, "https://mq.com/1-old", is_primary=False)
    return {"tech": tech, "dist": dist, "mq": mq, "life": life,
            "e1": entries[0], "e2": entries[1], "e3": entries[2],
            "e4": entries[3], "e5": entries[4]}


# ---- JSON ----

def test_export_json_schema_and_counts(dl, tmp_path):
    """探针①：schema_version + counts 对账 + entries 带 locators/categories/meta。"""
    from knowatlas.pipeline.export import EXPORT_SCHEMA_VERSION, export_json

    g = _seed_library(dl)
    out = tmp_path / "full.json"
    stats = export_json(dl, out)
    assert stats["schema_version"] == EXPORT_SCHEMA_VERSION
    assert stats["entries"] == 5 and stats["categories"] == 4
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    by_id = {e["id"]: e for e in payload["entries"]}
    e1 = by_id[g["e1"].id]
    assert e1["locators"] == ["https://mq.com/1-old"]          # 附加 locator 完整
    assert set(e1["categories"]) == {g["mq"].id, g["dist"].id}  # 多父直挂完整
    assert e1["meta"]["source_type"] == "bookmark"              # meta 完整
    assert e1["inline_content"] == "路由与过滤实践。"            # 短摘要内联
    # archived 条目也在全量投影里（防锁定）
    assert by_id[g["e5"].id]["status"] == "archived"
    # 分类 DAG：多父完整（消息队列的 parents = 技术 + 分布式）
    cats = {c["id"]: c for c in payload["categories"]}
    assert set(cats[g["mq"].id]["parents"]) == {g["tech"].id, g["dist"].id}
    assert cats[g["mq"].id]["path"].startswith("技术/")


# ---- Obsidian ----

def test_export_obsidian_vault(dl, tmp_path):
    """探针②：每分类有 MOC；条目笔记有 frontmatter + [[MOC]] 回链；多父全覆盖。"""
    from knowatlas.pipeline.export import export_obsidian

    g = _seed_library(dl)
    out_dir = tmp_path / "vault"
    stats = export_obsidian(dl, out_dir)
    assert stats["notes"] == 4 and stats["mocs"] == 4           # archived 不进 vault
    # MOC 在各分类自身目录（按首条 path，多父顺序不保证——用 glob 定位）
    mq_mocs = list(out_dir.glob("**/消息队列.md"))
    assert mq_mocs and any("[[消息总线入门]]" in p.read_text(encoding="utf-8")
                           for p in mq_mocs)                   # MOC 双链条目
    # 多父条目（e1 挂 mq + dist）：条目笔记回链两个 MOC，两个 MOC 都列它
    dist_moc = out_dir / "技术" / "分布式" / "分布式.md"
    assert "[[消息总线入门]]" in dist_moc.read_text(encoding="utf-8")
    notes = list(out_dir.glob("**/消息总线入门.md"))
    assert notes
    text = notes[0].read_text(encoding="utf-8")
    assert text.startswith("---") and "title: 消息总线入门" in text
    assert "[[消息队列]]" in text and "[[分布式]]" in text      # 回链全部父 MOC
    assert "路由与过滤实践。" in text                            # 正文
    # file/mail 条目也在 vault（active 全量），archived 不在
    assert (out_dir / "生活" / "本地手册.md").exists()
    assert not (out_dir / "生活" / "旧弃页.md").exists()


def test_export_obsidian_filename_safety(dl, tmp_path):
    """文件名安全化：标题含非法字符/重名不炸不覆盖。"""
    from knowatlas.pipeline.export import export_obsidian

    life = dl.create_category("生活", [], "manual")
    entries = [
        _entry(source_key="s:1", title='a/b:c*d?e"f<g>h|i', locator="https://s.com/1",
               locator_canonical="https://s.com/1"),
        _entry(source_key="s:2", title="a_b_c_d_e_f_g_h_i", locator="https://s.com/2",
               locator_canonical="https://s.com/2"),  # 与上一条安全化后同名 → 避撞
    ]
    dl.upsert_entries(entries)
    dl.attach_category(entries[0].id, life.id, 0.9, "rule", "t-export")
    dl.attach_category(entries[1].id, life.id, 0.9, "rule", "t-export")
    export_obsidian(dl, tmp_path / "v2")
    files = sorted(p.name for p in (tmp_path / "v2" / "生活").glob("*.md"))
    assert any("a_b_c_d_e_f_g_h_i.md" in f for f in files)
    assert len([f for f in files if f.startswith("a_b_c")]) == 2  # 两条都在不互覆


# ---- OPML ----

def test_export_opml_roundtrip(dl, tmp_path):
    """探针③：XML 可解析；嵌套=层级；叶子=http 条目；往返重建无损。"""
    from knowatlas.pipeline.export import export_opml

    g = _seed_library(dl)
    out = tmp_path / "bookmarks.opml"
    stats = export_opml(dl, out)
    # http canonical 的 active 条目 = 2（file/mail 天然排除，archived 不算 active）
    assert stats["bookmarks"] == 2
    root = ET.parse(out).getroot()
    assert root.tag == "opml" and root.get("version") == "2.0"
    body = root.find("body")

    def walk(node, path):
        """重建 (分类路径, url) 对——往返保真校验。"""
        pairs = []
        for o in node.findall("outline"):
            if o.get("type") == "link":
                pairs.append((path, o.get("htmlUrl")))
            else:
                pairs.extend(walk(o, path + [o.get("text")]))
        return pairs

    pairs = walk(body, [])
    urls = {u for _, u in pairs}
    assert urls == {"https://mq.com/1", "https://dist.com/2"}
    # 层级：e1 直挂 mq（多父分类）+ dist → 三条路径都出现（多父不丢）
    mq_paths = [p for p, u in pairs if u == "https://mq.com/1"]
    assert len(mq_paths) == 3
    assert ["技术", "消息队列"] in mq_paths
    assert ["技术", "分布式", "消息队列"] in mq_paths
    assert ["技术", "分布式"] in mq_paths
    # XML 合法性已由 ET.parse 保证；标题转义无害
    assert out.read_text(encoding="utf-8").count("<outline") >= 4


# ---- CLI ----

def test_cmd_kexport_cli(dl, tmp_path, monkeypatch, cfg):
    """CLI 冒烟：三格式真跑（load_config 打桩到测试 cfg；_open 复用同库文件）。"""
    from knowatlas import cli
    import knowatlas.config as cfg_mod

    g = _seed_library(dl)
    monkeypatch.setattr(cfg_mod, "load_config", lambda: cfg)
    args = lambda fmt, out: type("A", (), {"format": fmt, "out": str(out)})()
    assert cli._cmd_kexport(args("json", tmp_path / "a.json")) == 0
    assert (tmp_path / "a.json").exists()
    assert cli._cmd_kexport(args("obsidian", tmp_path / "vault")) == 0
    assert (tmp_path / "vault" / "生活").exists()
    assert cli._cmd_kexport(args("opml", tmp_path / "b.opml")) == 0
    assert (tmp_path / "b.opml").exists()
    assert cli._cmd_kexport(args("bogus", tmp_path / "c.txt")) == 1  # EXIT_BUSY
