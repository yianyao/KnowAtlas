"""万兴脑图适配器（source_type=emmx）：基于真实 MindMaster 9.x 格式的 fixture 测试。

fixture 结构按 2026-10-19 解剖的真实样本定稿：
ZIP 内 document.xml（页清单）+ page/page.xml（Shape 主题树，
文本在 Text/TextBlock/Text 的 <tp>，层级为 LevelData/Super 引用）。
形态判定与全删重灌测试对应 CHANGELOG 第六十五批（Phase 7 批次 62，方案 §7.8）。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from knowatlas.adapters.emmx import collect_emmx
from knowatlas.errors import AdapterError
from knowatlas.ids import content_hash
from knowatlas.models import Entry, FetchResult
from knowatlas.pipeline.sync import run_sync
from knowatlas.semantic.llm import LlmClient, LlmError

_DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Document Version="9.2.1" DocVersion="9.1">
    <Properties><Pages V="page"/></Properties>
</Document>"""


def _shape(sid: str, stype: str, title: str, super_id: str = "", sublevel: str = "") -> str:
    tps = "".join(f"<tp CX=\"0\">{part}</tp>" for part in title.split("\n") if part)
    text = f"<Text><TextBlock><Text><pp PX=\"0\">{tps}</pp></Text></TextBlock></Text>" if tps else ""
    level = "<LevelData>"
    if super_id:
        level += f"<Super V=\"{super_id}\"/>"
    if sublevel:
        level += f"<SubLevel V=\"{sublevel}\"/>"
    level += "</LevelData>"
    return f"<Shape ID=\"{sid}\" Type=\"{stype}\">{text}{level}</Shape>"


def _page_xml(shapes: list[str]) -> bytes:
    body = "".join(shapes)
    return f"<?xml version=\"1.0\"?><Page ID=\"1\" Type=\"Page\" Name=\"页面-1\">{body}</Page>".encode("utf-8")


def _write_emmx(path: Path, page: bytes = b"") -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("document.xml", _DOCUMENT_XML)
        if page:
            zf.writestr("page/page.xml", page)


@pytest.fixture
def emmx_tree(tmp_path: Path) -> Path:
    root = tmp_path / "脑图库"
    root.mkdir()
    # 正常脑图：MainIdea → MainTopic → SubTopic，含多段 tp 与 Boundary 装饰容器
    shapes = [
        _shape("101", "MainIdea", "PECOS进度", sublevel="102;104"),
        _shape("102", "MainTopic", "采购", super_id="101", sublevel="108"),
        _shape("108", "SubTopic", "供应商管理\n准入流程", super_id="102"),
        _shape("104", "MainTopic", "编码", super_id="101"),
        _shape("132", "Boundary", ""),  # 装饰容器：SubTopic 挂它 → 断链按顶层
        _shape("200", "SubTopic", "孤立分支", super_id="132"),
    ]
    _write_emmx(root / "创作脑图.emmx", _page_xml(shapes))
    # 降级样本：旧版仅 page.bin；坏 zip；page.xml 无主题节点
    (root / "子目录").mkdir()
    with zipfile.ZipFile(root / "子目录" / "旧版.emmx", "w") as zf:
        zf.writestr("mmpage/page.bin", b"\x00\x01binary")
    (root / "坏zip.emmx").write_bytes(b"not a zip")
    _write_emmx(root / "空图.emmx", _page_xml([_shape("300", "MMConnector", "")]))
    return root


def _enable(cfg, root: Path) -> None:
    cfg._data["sources"]["emmx"] = {"enabled": True, "roots": [str(root)]}


def test_collect_topics(cfg, emmx_tree):
    """llm 未启用 → 整图保全（degraded）：结构化大纲入正文；降级文件条目照旧。"""
    _enable(cfg, emmx_tree)
    out = collect_emmx(cfg)
    by_loc = {e.locator: e for e in out.entries}
    # 整图 1 条（创作脑图#map）+ 3 个解析降级文件条目
    assert len(out.entries) == 4
    assert out.stats["degraded_files"] == 3
    whole = by_loc["emmx://创作脑图.emmx#map"]
    assert whole.title == "PECOS进度"                    # 中心主题为题
    assert whole.meta["judge"] == "degraded"             # llm 未启用整图保全
    assert whole.meta["mind_path"] == "PECOS进度"
    body = whole.inline_content
    assert "供应商管理" in body and "孤立分支" in body    # 大纲含各分支（断链按顶层）
    assert body.index("采购") < body.index("编码")        # 分支顺序保持


def test_degraded_files(cfg, emmx_tree):
    """仅 page.bin / 坏 zip / 无主题节点 → 标题级单条目，degraded=true。"""
    _enable(cfg, emmx_tree)
    out = collect_emmx(cfg)
    by_loc = {e.locator: e for e in out.entries}
    bad = by_loc["emmx://子目录/旧版.emmx#file"]
    assert bad.meta["degraded"] is True
    assert bad.title == "旧版"
    assert bad.native_path == "脑图库/子目录"
    assert by_loc["emmx://坏zip.emmx#file"].meta["degraded"] is True
    assert by_loc["emmx://空图.emmx#file"].meta["degraded"] is True


def test_missing_root_raises(cfg, tmp_path):
    cfg._data["sources"]["emmx"] = {"enabled": True, "roots": [str(tmp_path / "无")]}
    with pytest.raises(AdapterError):
        collect_emmx(cfg)


def test_sync_emmx_end_to_end(cfg, dl, registries, tmp_path, emmx_tree):
    _enable(cfg, emmx_tree)
    locators, semantics = registries
    stats = run_sync(cfg, dl, locators, semantics, full=True)
    src = stats["sources"]["emmx"]
    assert src["entries"] == 4 and src["created"] == 4   # 整图 1 + 解析降级 3
    # 二跑幂等
    stats2 = run_sync(cfg, dl, locators, semantics, full=True)
    assert stats2["sources"]["emmx"]["unchanged"] == 4


# ---- 形态判定与全删重灌（第六十五批，方案 §7.8）----

_INTEGRAL_JUDGE = '{"judge":"integral","reason":"单一方案脑图，分支互相依赖不可拆"}'
_SPLIT_JUDGE = '{"judge":"split","reason":"问题收集，各分支独立成立"}'


class _FakeJudgeLlm:
    """形态判定替身：固定回复；broken=True 抛 LlmError。"""

    def __init__(self, reply: str = "", broken: bool = False):
        self.reply = reply
        self.broken = broken
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        if self.broken:
            raise LlmError("模拟故障")
        return self.reply


@pytest.fixture
def fake_llm(monkeypatch):
    """把 LlmClient.from_config 换成固定替身（collect_emmx 内部构建）。"""
    def _install(llm: _FakeJudgeLlm) -> _FakeJudgeLlm:
        monkeypatch.setattr(LlmClient, "from_config",
                            classmethod(lambda cls, cfg: llm))
        return llm
    return _install


def _emmx_only(out):
    return {e.locator: e for e in out.entries}


def test_judge_integral_whole_map_one_entry(cfg, emmx_tree, fake_llm):
    """integral（方案型）→ 整图一条目：大纲入正文、judge/judge_reason 落 meta。"""
    _enable(cfg, emmx_tree)
    fake_llm(_FakeJudgeLlm(_INTEGRAL_JUDGE))
    out = collect_emmx(cfg)
    assert out.stats["judge"]["integral"] == 1
    assert out.stats["judge"]["calls"] == 1
    # 结构化文件 1 条 + 降级文件 3 条（降级不判定）
    assert len(out.entries) == 4
    plan = _emmx_only(out)["emmx://创作脑图.emmx#map"]
    assert plan.title == "PECOS进度"
    assert plan.meta["judge"] == "integral"
    assert plan.meta["judge_reason"] == "单一方案脑图，分支互相依赖不可拆"
    assert plan.meta["mind_path"] == "PECOS进度"
    assert plan.meta["nodes"] == 5
    # 大纲 = 原文标题的确定性缩进排版（零发明）：根/一级/叶子层级分明
    body = plan.inline_content
    assert "- PECOS进度" in body
    assert "  - 采购" in body
    assert "    - 供应商管理 准入流程" in body
    assert "- 孤立分支" in body  # 断链节点按顶层
    assert plan.inline_content and len(plan.inline_content) > 50


def test_judge_split_nodes_keep_mind_path(cfg, emmx_tree, fake_llm):
    """split（讨论型）→ 节点照旧切条目，meta 附 judge + mind_path 保留。"""
    _enable(cfg, emmx_tree)
    fake_llm(_FakeJudgeLlm(_SPLIT_JUDGE))
    out = collect_emmx(cfg)
    assert out.stats["judge"]["split"] == 1
    assert len(out.entries) == 8
    node = _emmx_only(out)["emmx://创作脑图.emmx#page/108"]
    assert node.meta["judge"] == "split"
    assert node.meta["judge_reason"] == "问题收集，各分支独立成立"
    assert node.meta["mind_path"] == "PECOS进度/采购/供应商管理 准入流程"


def test_judge_llm_broken_keeps_whole_map_degraded(cfg, emmx_tree, fake_llm):
    """LLM 故障 → 整图保全（宁整勿碎，2026-10-22）：degraded 标记，不再碎切。"""
    _enable(cfg, emmx_tree)
    fake_llm(_FakeJudgeLlm(broken=True))
    out = collect_emmx(cfg)
    assert out.stats["judge"]["errors"] == 1
    assert out.stats["judge"]["calls"] == 0
    assert out.stats["judge"]["split"] == 0
    assert out.stats["judge"]["degraded"] == 1
    by_loc = _emmx_only(out)
    assert "emmx://创作脑图.emmx#page/108" not in by_loc   # 节点碎切不再发生
    whole = by_loc["emmx://创作脑图.emmx#map"]             # 整图单条目
    assert whole.meta["judge"] == "degraded"
    assert "整图保全" in whole.meta["judge_reason"]
    assert whole.inline_content and len(whole.inline_content) > 50


def test_judge_invalid_reply_keeps_whole_map(cfg, emmx_tree, fake_llm):
    """LLM 输出非法判定 → 同样整图保全 degraded。"""
    _enable(cfg, emmx_tree)
    fake_llm(_FakeJudgeLlm('{"judge":"maybe","reason":"???"}'))
    out = collect_emmx(cfg)
    assert out.stats["judge"]["errors"] == 1
    whole = _emmx_only(out)["emmx://创作脑图.emmx#map"]
    assert whole.meta["judge"] == "degraded"


def test_no_llm_keeps_whole_map_degraded(cfg, emmx_tree):
    """[llm] 未启用 → 整图保全（脑图默认方案，永不碎切，2026-10-22）。"""
    _enable(cfg, emmx_tree)
    out = collect_emmx(cfg)
    whole = _emmx_only(out)["emmx://创作脑图.emmx#map"]
    assert whole.meta["judge"] == "degraded"
    assert "LLM 未启用" in whole.meta["judge_reason"]
    assert "emmx://创作脑图.emmx#page/108" not in _emmx_only(out)


def test_judge_cache_survives_rerun(cfg, emmx_tree, fake_llm, tmp_path, monkeypatch):
    """判定缓存（KNOWATLAS_HOME/emmx_judge_cache.json）：二跑命中不重判。"""
    monkeypatch.setenv("KNOWATLAS_HOME", str(tmp_path))
    _enable(cfg, emmx_tree)
    llm = fake_llm(_FakeJudgeLlm(_INTEGRAL_JUDGE))
    out1 = collect_emmx(cfg)
    assert out1.stats["judge"]["calls"] == 1 and out1.stats["judge"]["cache_hits"] == 0
    out2 = collect_emmx(cfg)
    assert out2.stats["judge"]["cache_hits"] == 1
    assert out2.stats["judge"]["calls"] == 0  # 不重判不重扣费
    assert llm.calls == 1


def test_purge_source_cascade_and_recycle(cfg, dl):
    """purge_source：全状态物理删除 + FK 级联 + content_store 引用计数回收 + 留痕。"""
    shared = content_hash("共享正文块")
    dl.put_content(FetchResult(text="共享正文块", content_hash=shared,
                               fetcher="t", fetched_at="2026-10-22T00:00:00+08:00"))
    emmx_only = content_hash("emmx 独享正文")
    dl.put_content(FetchResult(text="emmx 独享正文", content_hash=emmx_only,
                               fetcher="t", fetched_at="2026-10-22T00:00:00+08:00"))
    es = [
        Entry.build(source_type="emmx", source_key="a", title="脑图甲",
                    locator="emmx://a#page/1", meta={"source_type": "emmx"}),
        Entry.build(source_type="emmx", source_key="b", title="脑图乙",
                    locator="emmx://b#map", inline_content="共享正文块",
                    content_hash=shared, meta={"source_type": "emmx"}),
        Entry.build(source_type="emmx", source_key="c", title="脑图丙",
                    locator="emmx://c#map", inline_content="emmx 独享正文",
                    content_hash=emmx_only, meta={"source_type": "emmx"}),
        Entry.build(source_type="manual", source_key="m", title="手记",
                    locator="https://example.com/m", inline_content="共享正文块",
                    content_hash=shared, meta={"source_type": "manual"}),
    ]
    dl.upsert_entries(es)
    dl.set_status([es[0].id], "rejected")  # rejected 的 emmx 也属「全删存量」
    dl.attach_category(es[0].id, dl.create_category("暂存", [], "rule").id,
                       0.9, "rule", "r1")
    stats = dl.purge_source("emmx", reason="emmx_rebuild")
    assert stats["purged"] == 3 and stats["content_recycled"] == 1
    # emmx 条目全状态清零；manual 条目与其共享正文块保留
    left = dl._conn.execute("SELECT source_type, COUNT(*) n FROM entries"
                            " GROUP BY source_type").fetchall()
    assert {r["source_type"]: r["n"] for r in left} == {"manual": 1}
    assert dl.get_content(shared) == "共享正文块"
    assert dl.get_content(emmx_only) is None  # 引用归零 → 正文回收
    # FTS 同步（触发器）：搜不到已删条目
    assert dl.search_fts("脑图丙") == []
    # task_log 批次留痕
    log = dl._conn.execute(
        "SELECT detail FROM task_log WHERE action='purge_source'"
        " AND target='emmx' ORDER BY rowid DESC LIMIT 1").fetchone()
    assert '"reason": "emmx_rebuild"' in log["detail"] \
        or '"reason":"emmx_rebuild"' in log["detail"]


def test_sync_purge_then_reingest(cfg, dl, registries, emmx_tree):
    """ksync --purge-source emmx 全链路：先全删（含 rejected）后按判定重灌。"""
    _enable(cfg, emmx_tree)
    locators, semantics = registries
    run_sync(cfg, dl, locators, semantics, full=True)  # 首灌 4 条（整图 1 + 降级 3）
    dl.set_status([e.id for e in dl.list_entries(limit=100)[:1]], "rejected")
    stats = run_sync(cfg, dl, locators, semantics, full=True,
                     purge_source="emmx", purge_reason="emmx_rebuild")
    # 全删含 rejected（全删存量不分状态）；重灌后 rejected 不复活（行已物理删除，
    # 重新入库即全新 active 条目——与「rejected 永不复活」语义不冲突）
    assert stats["purge"]["purged"] == 4
    assert stats["purge"]["reason"] == "emmx_rebuild"
    assert stats["sources"]["emmx"]["created"] == 4  # 重灌回来
    n = dl._conn.execute("SELECT COUNT(*) n FROM entries WHERE source_type='emmx'"
                         ).fetchone()["n"]
    assert n == 4
    # 重灌后二跑幂等
    stats2 = run_sync(cfg, dl, locators, semantics, full=True)
    assert stats2["sources"]["emmx"]["unchanged"] == 4


def test_sync_purge_dry_run_keeps_data(cfg, dl, registries, emmx_tree):
    """--purge-source + --dry-run：只探测，不删除。"""
    _enable(cfg, emmx_tree)
    locators, semantics = registries
    run_sync(cfg, dl, locators, semantics, full=True)
    stats = run_sync(cfg, dl, locators, semantics, full=True,
                     purge_source="emmx", dry_run=True)
    assert stats["purge"] == {"source_type": "emmx", "dry_run": True}
    n = dl._conn.execute("SELECT COUNT(*) n FROM entries WHERE source_type='emmx'"
                         ).fetchone()["n"]
    assert n == 4


def test_integral_long_outline_into_content_store(cfg, dl, registries, tmp_path,
                                                  fake_llm):
    """大纲超 4096 契约上限：inline 截断摘要 + 全文入 content_store（sync 钩子）。"""
    root = tmp_path / "大图库"
    root.mkdir()
    shapes = [_shape("1", "MainIdea", "巨型方案图")]
    for i in range(120):  # 120 × ~50 字标题 → 大纲远超 4096
        shapes.append(_shape(f"n{i}", "MainTopic",
                             f"分支{i}：" + "很长的分支标题内容" * 5, super_id="1"))
    with zipfile.ZipFile(root / "大图.emmx", "w") as zf:
        zf.writestr("document.xml", _DOCUMENT_XML)
        zf.writestr("page/page.xml", _page_xml(shapes))
    cfg._data["sources"]["emmx"] = {"enabled": True, "roots": [str(root)]}
    fake_llm(_FakeJudgeLlm(_INTEGRAL_JUDGE))
    locators, semantics = registries
    stats = run_sync(cfg, dl, locators, semantics, full=True)
    src = stats["sources"]["emmx"]
    assert src["created"] == 1 and src["contents_stored"] == 1
    entry = dl.list_entries(limit=10)[0]
    assert entry.content_hash is not None
    assert "…[截断，全文在 content_store]" in (entry.inline_content or "")
    assert len(entry.inline_content) <= 4096
    full = dl.get_content(entry.content_hash)
    assert full is not None and len(full) > 4096 and "分支0：" in full
    # 二跑幂等：同一 content_hash 不重复落库
    stats2 = run_sync(cfg, dl, locators, semantics, full=True)
    assert stats2["sources"]["emmx"]["unchanged"] == 1
    assert stats2["sources"]["emmx"]["contents_stored"] == 0


def test_sync_purge_aborts_when_backup_fails(cfg, dl, registries, emmx_tree,
                                             monkeypatch):
    """快照失败 → aborted，purge 不动手（没快照不动手纪律）。"""
    _enable(cfg, emmx_tree)
    locators, semantics = registries
    run_sync(cfg, dl, locators, semantics, full=True)
    import knowatlas.pipeline.backup as backup_mod

    def _boom(*a, **k):
        raise RuntimeError("磁盘满")
    # run_sync 内部函数级 from-import 每次调用重绑 → 打补丁即生效
    monkeypatch.setattr(backup_mod, "snapshot", _boom)
    stats = run_sync(cfg, dl, locators, semantics, full=True, purge_source="emmx")
    assert stats.get("aborted") == "backup_failed"
    assert "purge" not in stats
    n = dl._conn.execute("SELECT COUNT(*) n FROM entries WHERE source_type='emmx'"
                         ).fetchone()["n"]
    assert n == 4  # 数据未动
