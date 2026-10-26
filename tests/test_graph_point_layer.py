"""P4 点级图测试（2026-10-26）：radiate 点焦点 + /api/graph/subtree layer=points。

工单：docs/design/变更工单-2026-10-26-P4点级图.md

覆盖：
- 点焦点四通道（attach / same_book / same_section / sim）齐全，每节点 reasons、
  每条边 reason 非空；焦点带 text/path/sources；
- 章节名=书名（整本一块的 kpe 产物）时不出 same_section，避免与同书重复；
- 无向量点 → sim 通道整体缺席（降级纪律）；向量低于阈值不出边；
- per_channel 截断与 truncated 计数；未知点/溯源全不可消费 → None；
- 子树 layer=points：节点全为点（无 e: 节点）、边 kind="point"、point_limit 截断；
- 无点范围自动回退条目层（layer="entries" + note）；
- API 层参数透传与非法 layer=400；前端静态探针（点层开关/切焦点/点卡）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowatlas.models import Entry
from knowatlas.pipeline.embed_index import normalize
from knowatlas.pipeline.points import point_hash
from knowatlas.semantic.embed import vec_to_blob
from knowatlas.web.app import create_app

GRAPH_HTML = Path(__file__).resolve().parent.parent / "src/knowatlas/web/static/graph.html"


def _seed_point(dl, entry_id: str, text: str, meta: dict) -> str:
    """点直落（绕过 LLM）：id = content_hash[:16]，与 put_point 内部口径一致。"""
    dl.put_point({"content_hash": point_hash(text), "text": text, "summary": "",
                  "source_type": "manual", "judge": "integral", "meta": meta},
                 {"entry_id": entry_id, "char_offset": 0, "anchor": text[:120]})
    return point_hash(text)[:16]


def _entry(i: int, title: str = "") -> Entry:
    return Entry.build(source_type="folder", source_key=f"p4:{i}",
                       title=title or f"书稿{i}", locator=f"file:///D/books/{i}.md",
                       locator_canonical=None, inline_content="正文",
                       native_path="D:/books", meta={})


@pytest.fixture
def seeded(dl):
    """两条书稿 → 分类「AI 书 / 智能体」；甲书同章两点（近邻），乙书一点（正交）。"""
    es = [_entry(0, "智能体之路"), _entry(1, "另一本书稿")]
    dl.upsert_entries(es)
    cat = dl.create_category("AI 书", [], "manual")
    sub = dl.create_category("智能体", [cat.id], "manual")
    for e in es:
        dl.attach_category(e.id, sub.id, 1.0, "rule", "p4")
    a = _seed_point(dl, es[0].id, "知识点甲：容器化部署",
                    {"book": "智能体之路", "section_path": "第1章"})
    b = _seed_point(dl, es[0].id, "知识点乙：同章另一条",
                    {"book": "智能体之路", "section_path": "第1章"})
    c = _seed_point(dl, es[1].id, "知识点丙：另一本书",
                    {"book": "另一本书", "section_path": "第2章"})
    v_a = normalize([1.0, 0, 0, 0, 0, 0, 0, 0])
    dl.put_point_vectors([
        {"point_id": a, "dim": 8, "model": "fake:test", "vector": vec_to_blob(v_a)},
        {"point_id": b, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([0.97, 0.1, 0, 0, 0, 0, 0, 0]))},
        {"point_id": c, "dim": 8, "model": "fake:test",
         "vector": vec_to_blob(normalize([0, 1.0, 0, 0, 0, 0, 0, 0]))},
    ])
    return {"es": es, "cat": cat, "sub": sub, "a": a, "b": b, "c": c}


# ---- 数据层：radiate 点焦点 ----

def test_radiate_point_focus_four_channels(dl, seeded):
    r = dl.radiate(f"p:{seeded['a']}")
    assert r is not None
    assert r["focus"]["kind"] == "point" and r["focus"]["id"] == f"p:{seeded['a']}"
    assert r["focus"]["path"] == "《智能体之路》 / 第1章"
    assert r["focus"]["text"] and r["focus"]["sources"][0]["entry_id"] == seeded["es"][0].id

    reasons = {x for n in r["nodes"] for x in n["reasons"]}
    assert any(x.startswith("attach:rule") for x in reasons)
    assert "same_book:智能体之路" in reasons
    assert "same_section:智能体之路/第1章" in reasons
    assert any(x.startswith("sim:") for x in reasons)

    assert all(n["reasons"] for n in r["nodes"])
    assert all(e["reason"] for e in r["edges"])
    # 点焦点自身不重复出现在邻域
    assert f"p:{seeded['a']}" not in {n["id"] for n in r["nodes"]}
    # 每条边都指向邻域节点
    node_ids = {n["id"] for n in r["nodes"]}
    assert all(e["target"] in node_ids for e in r["edges"])


def test_radiate_point_section_equals_book_skips_section(dl, seeded):
    """整本一块（section_path == book）不出同章节通道，避免与同书重复。"""
    first = _seed_point(dl, seeded["es"][0].id, "整本大书第一块",
                        {"book": "整本大书", "section_path": "整本大书"})
    _seed_point(dl, seeded["es"][0].id, "整本大书第二块",
                {"book": "整本大书", "section_path": "整本大书"})
    r = dl.radiate(f"p:{first}")
    assert r is not None
    assert r["focus"]["path"] == "《整本大书》"
    reasons = {x for n in r["nodes"] for x in n["reasons"]}
    assert "same_book:整本大书" in reasons
    assert not any(x.startswith("same_section:") for x in reasons)


def test_radiate_point_sim_threshold_and_degrade(dl, seeded):
    """向量正交（余弦 0 < 0.5）不出 sim 边；无向量的点整条 sim 通道缺席。"""
    ra = dl.radiate(f"p:{seeded['a']}")
    assert f"p:{seeded['c']}" not in {n["id"] for n in ra["nodes"]}
    no_vec = _seed_point(dl, seeded["es"][0].id, "没有向量的孤立点",
                         {"book": "无向量书", "section_path": "x"})
    r = dl.radiate(f"p:{no_vec}")
    assert r is not None
    reasons = {x for n in r["nodes"] for x in n["reasons"]}
    assert not any(x.startswith("sim:") for x in reasons)


def test_radiate_point_per_channel_truncation(dl, seeded):
    """同书 4 点、per_channel=1：只出 1 个同书邻点，truncated 记剩余 3。"""
    for i in range(3):
        _seed_point(dl, seeded["es"][0].id, f"密集同书知识点{i}",
                    {"book": "密集书", "section_path": "第1章"})
    focus = _seed_point(dl, seeded["es"][0].id, "密集同书焦点",
                        {"book": "密集书", "section_path": "第1章"})
    tight = dl.radiate(f"p:{focus}", per_channel=1)
    assert tight["truncated"]["same_book"] == 2   # 3 个同书邻点只出 1
    book_nodes = [n for n in tight["nodes"]
                  if any(x.startswith("same_book:") for x in n["reasons"])]
    assert len(book_nodes) == 1


def test_radiate_point_unknown_and_unconsumable(dl, seeded):
    assert dl.radiate("p:nope") is None
    assert dl.radiate("p:") is None
    # 溯源条目归档 → 点退出消费面 → 焦点不存在
    d = _seed_point(dl, seeded["es"][1].id, "只能靠归档条目溯源的孤立点",
                    {"book": "归档书", "section_path": "x"})
    dl.set_status([seeded["es"][1].id], "archived")
    assert dl.radiate(f"p:{d}") is None


# ---- 数据层：subtree 点层 ----

def test_subtree_point_layer_nodes_and_links(dl, seeded):
    d = dl.get_graph_subtree(seeded["sub"].id, layer="points")
    assert d["layer"] == "points"
    assert not any(n["kind"] == "entry" for n in d["nodes"])
    assert not any(n["id"].startswith("e:") for n in d["nodes"])
    points = [n for n in d["nodes"] if n["kind"] == "point"]
    # 子类下挂了甲乙两本书稿：甲书 a/b、乙书 c 都可消费，全部应上点层
    assert {n["id"] for n in points} == {f"p:{seeded['a']}", f"p:{seeded['b']}",
                                         f"p:{seeded['c']}"}
    assert all(n["text"] for n in points)
    assert all(n["path"].startswith("《") for n in points)
    assert d["links"] and all(l["kind"] == "point" for l in d["links"])
    assert all(l["source"].startswith("p:") and l["target"].startswith("c:")
               for l in d["links"])


def test_subtree_point_layer_limit_truncated(dl, seeded):
    d = dl.get_graph_subtree(seeded["sub"].id, layer="points", point_limit=1)
    assert d["layer"] == "points"
    assert len([n for n in d["nodes"] if n["kind"] == "point"]) == 1
    assert d["truncated"]["points"] == 2


def test_subtree_point_layer_fallback_without_points(dl, seeded):
    """无点范围：自动回退条目层并带 note（新条目/未抽点不空图）。"""
    bare = _entry(9, "还没抽点的书稿")
    dl.upsert_entries([bare])
    empty = dl.create_category("未抽点类", [], "manual")
    dl.attach_category(bare.id, empty.id, 1.0, "manual", "p4")
    d = dl.get_graph_subtree(empty.id, layer="points")
    assert d["layer"] == "entries"
    assert "note" in d
    assert any(n["kind"] == "entry" for n in d["nodes"])


def test_subtree_default_layer_unchanged(dl, seeded):
    """不带 layer 时行为与旧版一致：不返回 layer 键、照旧出条目节点。"""
    d = dl.get_graph_subtree(seeded["sub"].id)
    assert "layer" not in d
    assert any(n["kind"] == "entry" for n in d["nodes"])


# ---- Web API ----

@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")),
                       "test-token-123")
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def test_api_radiate_point(client, seeded):
    r = client.get(f"/api/graph/radiate?node_id=p:{seeded['a']}")
    assert r.status_code == 200
    body = r.json()
    assert body["focus"]["kind"] == "point"
    assert all(n["reasons"] for n in body["nodes"])
    assert client.get("/api/graph/radiate?node_id=p:nope").status_code == 404


def test_api_subtree_point_layer(client, seeded):
    r = client.get(f"/api/graph/subtree?category_id={seeded['sub'].id}&layer=points")
    assert r.status_code == 200
    body = r.json()
    assert body["layer"] == "points"
    assert all(n["kind"] in ("category", "point") for n in body["nodes"])


def test_api_subtree_bad_layer_400(client, seeded):
    r = client.get(f"/api/graph/subtree?category_id={seeded['sub'].id}&layer=bogus")
    assert r.status_code == 400


# ---- 前端静态探针（无浏览器，锁关键接线） ----

def test_graph_html_point_layer_wiring():
    html = GRAPH_HTML.read_text(encoding="utf-8")
    assert 'id="pointLayer"' in html
    assert "knowatlas.graphPointLayer" in html
    assert "&layer=points" in html
    assert 'kind === "point"' in html
    assert 'startsWith("p:")' in html          # 点节点点击切焦点
    assert "PAL.point" in html
    assert "same_section" in html              # 通道标签齐全
    assert "溯源：" in html                     # 点卡溯源入口