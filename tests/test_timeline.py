"""时间线视图测试（0.2.0 第四十四批）：scoped timeline 分桶、陈旧分支提醒、
bucket 下钻、消费口径、粒度自适应。"""

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
        source_type="manual", source_key="https://t.com/a",
        title="示例", locator="https://t.com/a",
        locator_canonical="https://t.com/a",
        meta={"source_type": "manual"},
    )
    defaults.update(overrides)
    return Entry.build(**defaults)


def _seed_library(dl):
    """技术 > 消息队列（叶子，2 条 2020/2021 + 1 条待清理）/ 技术 > 数据库
    （叶子，1 条 2026 新）/ 生活（顶层叶子，1 条无 created_at）。"""
    tech = dl.create_category("技术", [], "manual")
    mq = dl.create_category("消息队列", [tech.id], "manual")
    db_ = dl.create_category("数据库", [tech.id], "manual")
    life = dl.create_category("生活", [], "manual")
    entries = [
        _entry(source_key="tl:mq:1", title="消息总线入门", locator="https://mq.com/1",
               locator_canonical="https://mq.com/1",
               created_at="2020-07-15T10:00:00+08:00"),
        _entry(source_key="tl:mq:2", title="消息总线进阶", locator="https://mq.com/2",
               locator_canonical="https://mq.com/2",
               created_at="2021-03-01T10:00:00+08:00"),
        _entry(source_key="tl:mq:3", title="被守卫的旧页", locator="https://mq.com/3",
               locator_canonical="https://mq.com/3",
               created_at="2020-01-01T10:00:00+08:00",
               meta={"source_type": "manual", "value_flag": "not_knowledge"}),
        _entry(source_key="tl:db:1", title="索引原理", locator="https://db.com/1",
               locator_canonical="https://db.com/1",
               created_at="2026-01-02T10:00:00+08:00"),
        _entry(source_key="tl:life:1", title="家常菜谱", locator="https://life.com/1",
               locator_canonical="https://life.com/1"),
    ]
    dl.upsert_entries(entries)
    for e, cid in ((entries[0], mq.id), (entries[1], mq.id), (entries[2], mq.id),
                   (entries[3], db_.id), (entries[4], life.id)):
        dl.attach_category(e.id, cid, 0.9, "rule", "t-timeline")
    return {"tech": tech, "mq": mq, "db": db_, "life": life,
            "e1": entries[0], "e2": entries[1], "e3": entries[2],
            "e4": entries[3], "e5": entries[4]}


# ---- db 层 ----

def test_timeline_scope_isolation_and_buckets(dl):
    """探针①：范围隔离 + 月粒度分桶（mq 子树跨度 8 个月 ≤24 → month）+ 空桶补齐。"""
    g = _seed_library(dl)
    data = dl.timeline_data(g["mq"].id)
    assert data["focus"]["name"] == "消息队列"
    assert data["granularity"] == "month"
    # mq 子树可消费 2 条（待清理的 mq:3 被守卫排除）：2020-07 一条、2021-03 一条，
    # 中间空桶补齐（柱状图轴均匀）
    assert {b["key"]: b["count"] for b in data["buckets"]} == {
        "2020-07": 1, "2020-08": 0, "2020-09": 0, "2020-10": 0, "2020-11": 0,
        "2020-12": 0, "2021-01": 0, "2021-02": 0, "2021-03": 1}
    assert data["unknown_count"] == 0
    assert data["span"] == {"min": "2020-07-15", "max": "2021-03-01"}


def test_timeline_full_library_year_and_unknown_count(dl):
    """全库：跨度 66 个月 > 24 → 年粒度；时间未知条目只计数，不编造时间。"""
    g = _seed_library(dl)
    data = dl.timeline_data(None)
    assert data["granularity"] == "year"
    assert data["unknown_count"] == 1
    counts = {b["key"]: b["count"] for b in data["buckets"]}
    assert counts["2020"] == 1 and counts["2021"] == 1 and counts["2026"] == 1
    # 不存在分类 id → 空范围（不炸）
    empty = dl.timeline_data("0123456789abcdef")
    assert empty["focus"] is None and empty["buckets"] == []


def test_timeline_granularity_auto_and_override(dl):
    """探针②：跨度 ≤24 个月自适应 month；显式 granularity 覆盖。"""
    g = _seed_library(dl)
    # 数据库叶子单条 2026 → 跨度 0 个月 → month
    data = dl.timeline_data(g["db"].id)
    assert data["granularity"] == "month"
    assert [b["key"] for b in data["buckets"]] == ["2026-01"]
    # 显式覆盖：mq 范围强制 month（自适应会是 month 这里同样；年粒度会塌成 2 桶）
    data2 = dl.timeline_data(g["mq"].id, granularity="month")
    assert data2["granularity"] == "month"
    nz = {b["key"]: b["count"] for b in data2["buckets"] if b["count"]}
    assert nz == {"2020-07": 1, "2021-03": 1}
    # 显式覆盖 year：单月范围也按年出桶
    data3 = dl.timeline_data(g["db"].id, granularity="year")
    assert [b["key"] for b in data3["buckets"]] == ["2026"]


def test_timeline_stale_branches(dl):
    """探针③：叶子最新条目超 2 年 → stale_branches；有新条目不命中；
    无 created_at 的分支进 unknown_branches 不判陈旧。"""
    g = _seed_library(dl)
    data = dl.timeline_data(None, stale_years=2)
    stale = {b["name"]: b for b in data["stale_branches"]}
    assert set(stale) == {"消息队列"}              # 最新 2021-03，停滞 >2 年
    assert stale["消息队列"]["count"] == 2         # 只数可消费
    assert stale["消息队列"]["age_years"] >= 2
    assert stale["消息队列"]["latest"].startswith("2021-03-01")
    unknown = {b["name"] for b in data["unknown_branches"]}
    assert "生活" in unknown                        # created_at 全缺 → 不判陈旧
    assert "数据库" not in stale and "数据库" not in unknown  # 有新内容
    # 探针⑤：阈值参数化（10 年）→ 停滞 5 年多的消息队列不再 stale
    data10 = dl.timeline_data(None, stale_years=10)
    assert all(b["name"] != "消息队列" for b in data10["stale_branches"])


def test_timeline_bucket_drill_consumable(dl):
    """探针④：bucket 模式返回该桶可消费条目（待清理不出）。"""
    g = _seed_library(dl)
    entries = dl.timeline_data(g["mq"].id, bucket="2020")["entries"]
    assert [e.id for e in entries] == [g["e1"].id]   # mq:3 待清理被守卫排除
    # 空桶不炸、不出他处条目
    assert dl.timeline_data(g["mq"].id, bucket="2025")["entries"] == []
    assert dl.timeline_data(g["life"].id, bucket="2020")["entries"] == []


# ---- API 层 ----

def test_timeline_api_shape(client, dl):
    g = _seed_library(dl)
    r = client.get("/api/timeline")
    assert r.status_code == 200
    j = r.json()
    assert j["focus"] is None and j["granularity"] == "year"
    assert j["threshold_years"] == 2
    assert j["unknown_count"] == 1
    assert {b["name"] for b in j["stale_branches"]} == {"消息队列"}
    r2 = client.get(f"/api/timeline?category_id={g['mq'].id}&bucket=2020")
    ids = [e["id"] for e in r2.json()["entries"]]
    assert ids == [g["e1"].id]
    # 无鉴权要求（与 /api/cloud 同款只读端点）——上面调用均未带头已通


def test_timeline_api_static_probes():
    """前端静态探针：sidebar 入口 / tab / ECharts 复用 / 下钻与陈旧分支联动。"""
    from knowatlas.web.app import _STATIC_DIR

    index = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="tl-link"' in index                       # 侧栏常驻入口
    assert '"timeline", "📈 时间线"' in index             # 工作台 tab
    assert "renderTimelineTab" in index and "drillBucket" in index
    assert "/vendor/echarts.min.js" in index             # 复用 vendored echarts
    assert "tl-locate" in index                          # 陈旧分支树中定位
    assert "陈旧分支提醒" in index                        # 区块标题（规则明示）
