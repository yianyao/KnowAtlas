"""词云视图测试（0.2.0 第四十三批）：scoped cloud 聚合、facet、三态词元探针。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knowatlas.models import Entry
from knowatlas.web.app import create_app


@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")), "test-token-123")
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def _entry(**overrides) -> Entry:
    defaults = dict(
        source_type="manual", source_key="https://m.com/a",
        title="示例", locator="https://m.com/a",
        locator_canonical="https://m.com/a",
        meta={"source_type": "manual"},
    )
    defaults.update(overrides)
    return Entry.build(**defaults)


MQ_BODY = "消息队列的路由与过滤，消息投递的可靠性保障，顺序消息与延迟消息的实践。" * 5
LIFE_BODY = "家常烹饪技巧与火候掌握，调味搭配与快手做法的合集。" * 5


def _seed_library(dl):
    """技术 > 消息队列（2 条 + 1 条待清理）/ 技术 > 数据库；生活（1 条）。"""
    tech = dl.create_category("技术", [], "manual")
    mq = dl.create_category("消息队列", [tech.id], "manual")
    db_ = dl.create_category("数据库", [tech.id], "manual")
    life = dl.create_category("生活", [], "manual")
    entries = [
        _entry(source_key="mq:1", title="消息总线入门", locator="https://mq.com/1",
               locator_canonical="https://mq.com/1", inline_content=MQ_BODY),
        _entry(source_key="mq:2", title="消息总线进阶", locator="https://mq.com/2",
               locator_canonical="https://mq.com/2", inline_content=MQ_BODY,
               created_at="2026-01-02T00:00:00+08:00"),
        _entry(source_key="mq:3", title="被守卫的页", locator="https://mq.com/3",
               locator_canonical="https://mq.com/3", inline_content=MQ_BODY,
               meta={"source_type": "manual", "value_flag": "not_knowledge"}),
        _entry(source_key="life:1", title="家常菜谱", locator="https://life.com/1",
               locator_canonical="https://life.com/1", inline_content=LIFE_BODY),
    ]
    dl.upsert_entries(entries)
    for e, cid in ((entries[0], mq.id), (entries[1], mq.id), (entries[2], mq.id),
                   (entries[3], life.id)):
        dl.attach_category(e.id, cid, 0.9, "rule", "t-cloud")
    return {"tech": tech, "mq": mq, "db": db_, "life": life,
            "e1": entries[0], "e2": entries[1], "e3": entries[2], "e4": entries[3]}


# ---- db 层：范围、分类词元、消费口径、顶层根 ----

def test_cloud_data_scope_and_consumable(dl):
    g = _seed_library(dl)
    data = dl.cloud_data(g["mq"].id)
    assert data["focus"]["name"] == "消息队列"
    # 分类词元：消息队列无子分类 → 空；全库视图才有顶层词元
    assert data["categories"] == []
    # 样本只含子树内可消费条目：2 条 mq（待清理的 mq:3 被守卫排除）
    assert {e[0] for e in data["entries"]} == {g["e1"].id, g["e2"].id}
    # 顶层根 = 技术（消息队列的父）
    assert all(e[3] == g["tech"].id for e in data["entries"])
    # 不存在分类 id → 空范围（不炸）
    empty = dl.cloud_data("0123456789abcdef")
    assert empty["focus"] is None and empty["entries"] == []


def test_cloud_data_empty_db_uses_categories_key(dl):
    """空库（无任何分类）走早退分支：键名必须与正常路径一致（/api/cloud 读 categories，
    批次 60 曾因早退分支写 children 导致空库词云 500）。"""
    data = dl.cloud_data(None)
    assert data["focus"] is None
    assert data["categories"] == [] and data["entries"] == []


def test_cloud_data_children_pruned(dl):
    g = _seed_library(dl)
    data = dl.cloud_data(None)  # 全库 → 顶层大类词元
    names = {c["name"]: c["count"] for c in data["categories"]}
    assert names == {"技术": 2, "生活": 1}          # mq:3 待清理不计
    assert data["focus"] is None


# ---- api 层：内容词元聚合 + facet ----

def test_cloud_api_words_and_facet(client, dl):
    g = _seed_library(dl)
    r = client.get("/api/cloud")
    assert r.status_code == 200
    j = r.json()
    words = {w["word"]: w for w in j["words"]}
    # jieba tf-idf 从重复正文里提出主题词（词典词，版本锁定 0.42.1 下稳定）
    assert "消息" in words and words["消息"]["count"] == 2
    assert any(w["top"] and w["top"]["name"] == "生活" for w in j["words"])
    # 主导顶层分类 + 配色（12 色板十六进制）
    assert words["消息"]["top"]["name"] == "技术"
    assert all(w["color"].startswith("#") for w in j["words"])
    # 空分类剪枝后的顶层词元
    assert {c["name"] for c in j["categories"]} == {"技术", "生活"}


def test_cloud_api_scope_isolation(client, dl):
    g = _seed_library(dl)
    r = client.get(f"/api/cloud?category_id={g['mq'].id}")
    j = r.json()
    assert j["focus"]["name"] == "消息队列"
    # 探针①：切到消息队列，词云只反映该子树——生活的词元不出现
    assert all(not (w["top"] and w["top"]["name"] == "生活") for w in j["words"])
    # 探针③：内容词元 facet = 当前范围按该词过滤（mq 的 2 条，不含待清理与生活）
    r2 = client.get(f"/api/cloud?category_id={g['mq'].id}&word=消息")
    ids = {e["id"] for e in r2.json()["entries"]}
    assert ids == {g["e1"].id, g["e2"].id}


def test_cloud_facet_empty_scope(client, dl):
    g = _seed_library(dl)
    r = client.get(f"/api/cloud?category_id={g['db'].id}&word=消息")
    assert r.json()["entries"] == []      # 空子树不炸、不出他处条目


def test_cloud_filters_noise_tokens(client, dl):
    """真实库冒烟暴露的噪音词元（markdown 残片/导出占位符）必须被滤掉。"""
    g = _seed_library(dl)
    noisy = _entry(source_key="mq:9", title="报表导出", locator="https://mq.com/9",
                   locator_canonical="https://mq.com/9",
                   inline_content="## --- NaN PASS Unnamed 数据导出报表模板整理。" * 5)
    dl.upsert_entries([noisy])
    dl.attach_category(noisy.id, g["mq"].id, 0.9, "rule", "t-cloud")
    r = client.get(f"/api/cloud?category_id={g['mq'].id}")
    words = {w["word"] for w in r.json()["words"]}
    for bad in ("##", "---", "NaN", "PASS", "Unnamed", "数据导出报表模板整理"):
        assert bad not in words, bad


# ---- 前端静态探针（探针②④） ----

def test_cloud_frontend_probes():
    from knowatlas.web.app import _STATIC_DIR
    index = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-view="cloud"' in index                  # 顶层页签入口（第五十九批页签化）
    assert "showView" in index                           # 页签分发
    assert "renderCloudTab" in index
    # 探针②：分类词元点击 → currentCat 同步 + 树定位高亮 + 词云刷新
    cloud = index[index.index("async function renderCloudTab"):]
    assert "cloud-cat" in cloud and "highlightInTree(b.dataset.id)" in cloud
    assert "currentCat = b.dataset.id" in cloud
    # 探针④：字号 ∝ √权重
    assert "Math.sqrt(w.count / max)" in cloud
    # 回归探针（2026-10-26 19:25 报障）：词云点卡必须用独立 .pt-card，不得冒充
    # .entry[data-id] —— 条目的通用钩子（点聚合/🆔/分类徽标/多选拖拽）都按
    # .entry[data-id] 扫描，N 个点同属一个条目时会各自展开该条目全部 N 个点。
    assert 'class="pt-card"' in cloud
    assert '<div class="entry" data-id="${p.entry_id}">' not in cloud
