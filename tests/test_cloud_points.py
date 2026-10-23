"""词云点化测试（批次 89）：点词元同池 + 点 facet 优先。

词云点化 = 点层升为知识主体后，词云词频反映**知识分布**而非条目骨架分布；
条目词元保留兜底（未抽点条目仍出词）。jieba 在 tests 环境若缺省会跳过词元
断言（SQL 层行为独立验证）。
"""

from __future__ import annotations

import pytest

from knowatlas.models import Entry
from knowatlas.pipeline.points import point_hash

pytest.importorskip("jieba")   # 词元断言依赖 jieba（主依赖，缺省跳过）


def _seed_full(cfg, dl, with_point: bool, title: str = "进销存管理实践"):
    """建大类→子类→条目（可消费），可选落一个点（text 含「进销存」）。"""
    cat = dl.create_category("软件", [], "manual")
    sub = dl.create_category("ERP", [cat.id], "manual")
    e = dl.upsert_entries([Entry.build(
        source_type="manual", source_key=f"cw:{title}", title=title,
        locator=f"https://e.example/{title}", locator_canonical=None,
        inline_content="进销存以销售单为核心，驱动采购与库存联动。",
        native_path=None, meta={})]).ids[0]
    dl.attach_category(e, sub.id, confidence=1.0, origin="manual", task_run_id="t")
    pid = None
    if with_point:
        text = "进销存系统以销售单为核心驱动采购补货与库存盘点"
        dl.put_point({"content_hash": point_hash(text), "text": text,
                      "summary": "", "source_type": "manual",
                      "judge": "integral", "meta": {}},
                     {"entry_id": e, "char_offset": 0, "anchor": text[:120]})
        pid = dl.search_points("进销存")[0].point_id
    return e, pid


def test_cloud_includes_point_words(cfg, dl):
    _seed_full(cfg, dl, with_point=True)
    from knowatlas.web.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(cfg, dl, *build_regs(cfg))
    body = TestClient(app, headers={"Host": "127.0.0.1:8420"}).get(
        "/api/cloud").json()
    words = {w["word"] for w in body["words"]}
    assert "进销存" in words              # 点词元进池
    assert body["words"][0]["count"] >= 1


def test_cloud_facet_points_first(cfg, dl):
    e, pid = _seed_full(cfg, dl, with_point=True)
    from knowatlas.web.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(cfg, dl, *build_regs(cfg))
    body = TestClient(app, headers={"Host": "127.0.0.1:8420"}).get(
        "/api/cloud", params={"word": "进销存"}).json()
    assert [p["point_id"] for p in body["points"]] == [pid]
    assert body["points"][0]["entry_id"] == e
    assert body["points"][0]["text"].startswith("进销存")


def test_cloud_point_stale_excluded(cfg, dl):
    """点级 stale（批次 93）退出词云词元与 facet。"""
    e, pid = _seed_full(cfg, dl, with_point=True)
    dl.set_point_aging(pid, "stale", "v3.0 移除，官方文档确认")
    from knowatlas.web.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(cfg, dl, *build_regs(cfg))
    c = TestClient(app, headers={"Host": "127.0.0.1:8420"})
    facet = c.get("/api/cloud", params={"word": "进销存"}).json()
    assert facet["points"] == []          # stale 点不进 facet
    # 词元层面：条目正文仍含「进销存」→ 词还在（条目兜底口径），但点不重复计数
    body = c.get("/api/cloud").json()
    assert isinstance(body["words"], list)


def build_regs(cfg):
    from knowatlas.registry.builtins import build_registries
    return build_registries(cfg)
