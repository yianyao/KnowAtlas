"""知识点抽取测试（0.2.0 第六十二批 61a；第六十六批改规则判定——用户口径；
第九十二批提炼式重写——裁决「入库=知识整理，不是切片」）。

覆盖：规则判定（祖先链含锚词命中）、forced split/integral 提炼 prompt、
integral LLM 整条提炼（零 LLM 降级照抄保真）、骨架守门（body_flag=skeleton
跳过切片）、规范化 hash 去重、一点多溯源、幂等重跑、LLM 未启用（integral
照抄/split 记 error）、故障不阻塞、dry-run、purge_points。
"""

from __future__ import annotations

import uuid

from knowatlas.models import Entry
from knowatlas.pipeline.points import (
    _entry_body, normalize_point_text, point_hash, run_points_extract,
)
from knowatlas.semantic.base import TaskContext
from knowatlas.semantic.llm import LlmError
from knowatlas.semantic.tasks import point_extract


# ---- 测试替身 ----

class FakeLlm:
    """按调用序返回预设响应；broken=True 抛 LlmError。"""

    def __init__(self, replies: list[str] | None = None, broken: bool = False):
        self.replies = replies or []
        self.broken = broken
        self.calls: list[str] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append(system + "\n" + user)
        if self.broken:
            raise LlmError("模拟故障")
        idx = len(self.calls) - 1
        if idx >= len(self.replies):
            raise LlmError(f"多余调用 #{idx + 1}")
        return self.replies[idx]


_INTEGRAL_REPLY = (
    '```json\n{"judge":"integral","reason":"单主题方案文档，整体不可拆",'
    '"summary":"一套 SQLite 慢查询排查方案",'
    '"points":[{"text":"SQLite 慢查询排查：先 EXPLAIN QUERY PLAN 看计划，'
    '再补统计信息 ANALYZE。","summary":"SQLite 慢查询排查两步"}]}\n```'
)
# forced integral 提炼响应（批次 92）：无 judge 字段——形态已规则判定，
# LLM 只做整条提炼（quote=原文逐字引句，供溯源锚点）
_INTEGRAL_REFINE_REPLY = (
    '{"summary":"一套 SQLite 慢查询排查知识",'
    '"points":[{"text":"SQLite 慢查询排查：先用 EXPLAIN QUERY PLAN 看执行计划，'
    '定位全表扫描后 ANALYZE 补统计信息。","summary":"SQLite 慢查询排查两步",'
    '"quote":"先 EXPLAIN QUERY PLAN 看计划"}]}'
)
# forced split 响应：切点-only（无 judge/reason 字段——形态已规则判定）
_SPLIT_ONLY_REPLY = (
    '{"summary":"FTS5 与 WAL 两问",'
    '"points":[{"text":"FTS5 中文检索用 trigram 分词。","summary":"FTS5 分词选型"},'
    '{"text":"WAL 模式提升并发读：PRAGMA journal_mode=WAL。","summary":"WAL 开启方式"}]}'
)
# 全判定路径响应（杂烩目录用——形态未预判，LLM 先判 split 再切点）
_SPLIT_JUDGE_REPLY = (
    '{"judge":"split","reason":"杂烩目录，各文件主题独立",'
    '"summary":"两问各答",'
    '"points":[{"text":"FTS5 中文检索用 trigram 分词。","summary":"FTS5 分词选型"},'
    '{"text":"WAL 模式提升并发读：PRAGMA journal_mode=WAL。","summary":"WAL 开启方式"}]}'
)


def _seed_entries(dl, n: int = 1, *, body: str = "FTS5 中文检索用 trigram 分词。" * 3,
                  source_type: str = "manual") -> list[Entry]:
    # source_key 带随机段：entry_id 确定性生成，跨调用同 key 会撞成同一条目
    batch = uuid.uuid4().hex[:6]
    es = [Entry.build(source_type=source_type, source_key=f"pt:{batch}:{i}",
                      title=f"测试条目 {batch}:{i}",
                      locator=f"https://example.com/pt/{batch}/{i}",
                      inline_content=body,
                      meta={"source_type": source_type})
          for i in range(n)]
    dl.upsert_entries(es)
    return es


def _long_body_entry(dl, chars: int, key: str) -> Entry:
    """正文只存 content_store（inline 为空）：验证「取全文」与「长文转 kpe」（P3）。"""
    from knowatlas.models import FetchResult

    dl.put_content(FetchResult(text="长" * chars, content_hash=key, fetcher="test",
                               fetched_at="2026-10-26T00:00:00+08:00"))
    e = Entry.build(source_type="folder", source_key=f"pt:{key}:0",
                    title=f"长文 {chars}", locator=f"file:///d/{key}.md",
                    inline_content=None, content_hash=key,
                    meta={"source_type": "folder"})
    dl.upsert_entries([e])
    return e


def _attach_lit(dl, entries: list[Entry], *, child: bool = False) -> None:
    """挂「文学创作」分类；child=True 时挂其子分类（验证祖先链命中）。"""
    run_id = "r" + uuid.uuid4().hex[:15]
    lit = dl.create_category("文学创作", [], "manual")
    target = lit
    if child:
        target = dl.create_category("小说写法", [lit.id], "manual")
    for e in entries:
        dl.attach_category(e.id, target.id, 1.0, "manual", run_id)


def _folder(dl, np: str, name: str, suffix: str) -> Entry:
    """建 folder 条目（native_path 目录信号 + locator 带文件后缀）。"""
    e = Entry.build(source_type="folder", source_key=f"dir:{np}/{name}{suffix}",
                    title=name, locator=f"file:///{np}/{name}{suffix}",
                    native_path=np,
                    inline_content="方案正文：先 EXPLAIN QUERY PLAN 看计划，再补统计信息。" * 6,
                    meta={"source_type": "folder"})
    dl.upsert_entries([e])
    return e


# ---- 规范化与去重键 ----

def test_point_hash_ignores_whitespace_case_zerowidth():
    """空白折叠 + casefold + 零宽剔除 → 同观点不同排版同 hash。"""
    a = "Hello　World：FTS5 trigram"
    b = "hello\u200b world：fts5  trigram"          # 零宽 + 连续空白
    c = "  HELLO\n\tWorld：FTS5\tTRIGRAM  \n"       # 大小写 + 制表换行
    assert point_hash(a) == point_hash(b) == point_hash(c)
    assert point_hash("完全不同的另一条观点") != point_hash(a)


def test_normalize_point_text_keeps_punctuation():
    """标点不归一（宁漏勿误：去重键错了会错误合并不同观点）。"""
    assert normalize_point_text("版本 1.2 发布") != normalize_point_text("版本 12 发布")


# ---- 数据层：迁移 007 / 一点多溯源 ----

def test_put_point_creates_and_lists(dl):
    es = _seed_entries(dl, 1)
    ph = point_hash("SQLite 慢查询排查两步。")
    status = dl.put_point(
        {"content_hash": ph, "text": "SQLite 慢查询排查两步。", "summary": "排查",
         "source_type": "manual", "judge": "integral",
         "meta": {"judge_reason": "单主题"}},
        {"entry_id": es[0].id, "char_offset": 0, "anchor": "SQLite"})
    assert status == "created"
    assert dl.count_points() == 1
    pts = dl.list_points()
    assert pts[0]["judge"] == "integral"
    assert pts[0]["source_count"] == 1
    assert pts[0]["meta"]["judge_reason"] == "单主题"


def test_put_point_same_hash_merges_sources(dl):
    """同 hash 不同条目 → 一点多溯源（溯源数=可信度信号）；同条目重复补指针幂等。"""
    es = _seed_entries(dl, 2)
    ph = point_hash("同观点重复文档。")
    point = {"content_hash": ph, "text": "同观点重复文档。", "summary": "",
             "source_type": "manual", "judge": "split", "meta": {}}
    assert dl.put_point(point, {"entry_id": es[0].id, "char_offset": 0,
                                "anchor": "同观点"}) == "created"
    assert dl.put_point(point, {"entry_id": es[1].id, "char_offset": None,
                                "anchor": "同观点"}) == "linked"
    assert dl.count_points() == 1                    # 合并为一点
    assert dl.list_points()[0]["source_count"] == 2  # 两处溯源
    assert dl.put_point(point, {"entry_id": es[1].id, "char_offset": None,
                                "anchor": "同观点"}) == "linked"  # 重放不重计
    assert dl.list_points()[0]["source_count"] == 2
    srcs = dl.point_sources_of(ph[:16])
    assert {s["entry_id"] for s in srcs} == {es[0].id, es[1].id}
    assert srcs[0]["title"].startswith("测试条目")    # JOIN 条目供抽检


def test_point_source_entry_ids_is_cursor(dl):
    es = _seed_entries(dl, 2)
    ph = point_hash("游标验证。")
    dl.put_point({"content_hash": ph, "text": "游标验证。", "summary": "",
                  "source_type": "manual", "judge": "split", "meta": {}},
                 {"entry_id": es[0].id, "char_offset": None, "anchor": ""})
    assert dl.point_source_entry_ids() == {es[0].id}


def test_purge_points_clears_point_layer_only(dl):
    """purge_points 清空点层；条目/content_store 零影响；task_log 留痕。"""
    from knowatlas.models import FetchResult

    es = _seed_entries(dl, 1)
    dl.put_content(FetchResult(text="正文留存", content_hash="pp-keep",
                               fetcher="test", fetched_at="2026-10-22T00:00:00+08:00"))
    ph = point_hash("将被清空的点。")
    dl.put_point({"content_hash": ph, "text": "将被清空的点。", "summary": "",
                  "source_type": "manual", "judge": "integral", "meta": {}},
                 {"entry_id": es[0].id, "char_offset": 0, "anchor": ""})
    assert dl.count_points() == 1
    n = dl.purge_points(reason="口径变更")
    assert n == 1
    assert dl.count_points() == 0 and dl.point_source_entry_ids() == set()
    assert dl.get_content("pp-keep") == "正文留存"        # 原文无恙
    assert dl.get_entry(es[0].id).title.startswith("测试条目")  # 条目无恙
    logs = dl.get_task_log(limit=20)
    assert any(l["action"] == "purge_points" and l["task_name"] == "kpoints"
               for l in logs)


# ---- 任务级：point_extract ----

def test_point_extract_degrades_without_llm_and_body():
    res = point_extract.run({"body": "x"}, TaskContext(run_id="r1"))
    assert res["llm_used"] is False and res["points"] == []
    res2 = point_extract.run({"body": ""}, TaskContext(run_id="r1", llm=FakeLlm()))
    assert res2["llm_used"] is False


def test_point_extract_integral_judge_path():
    """未 forced（杂烩目录用）：判定+提炼合一——integral 归一为单元素 points。"""
    llm = FakeLlm([_INTEGRAL_REPLY])
    res = point_extract.run({"source_type": "emmx", "title": "方案", "body": "正文"
                             * 30}, TaskContext(run_id="r1", llm=llm))
    assert res["llm_used"] is True and res["judge"] == "integral"
    assert len(res["points"]) == 1
    assert "SQLite" in res["points"][0]["text"]
    assert res["reason"] == "单主题方案文档，整体不可拆"
    assert "方案" in llm.calls[0]  # 标题进提示词


def test_point_extract_forced_integral_refines():
    """forced integral（批次 92）：跳过判定直接整条提炼——judge 固定 integral、
    quote 透传（溯源锚点=原文逐字引句）。"""
    llm = FakeLlm([_INTEGRAL_REFINE_REPLY])
    res = point_extract.run({"body": "方案正文先 EXPLAIN QUERY PLAN 看计划。" * 10,
                             "forced_judge": "integral"},
                            TaskContext(run_id="r1", llm=llm))
    assert res["llm_used"] is True
    assert res["judge"] == "integral"
    assert "整条即点" in res["reason"]
    assert len(res["points"]) == 1
    assert res["points"][0]["quote"] == "先 EXPLAIN QUERY PLAN 看计划"
    assert "形态判定" not in llm.calls[0]   # 提炼-only prompt（无判定指令）


def test_point_extract_forced_split_skips_judgment():
    """forced split（用户口径）：LLM 只切点——judge 固定 split、理由固定口径、
    prompt 是切点-only 版（无形态判定指令）。"""
    llm = FakeLlm([_SPLIT_ONLY_REPLY])
    res = point_extract.run({"body": "a" * 60, "forced_judge": "split"},
                            TaskContext(run_id="r1", llm=llm))
    assert res["llm_used"] is True
    assert res["judge"] == "split"
    assert "用户口径" in res["reason"] and "文学创作" in res["reason"]
    assert len(res["points"]) == 2
    assert "形态判定" not in llm.calls[0]   # 切点-only prompt


def test_point_extract_split_and_garbage_and_broken():
    llm = FakeLlm([_INTEGRAL_REPLY.replace('"integral"', '"split"')])
    res = point_extract.run({"body": "a" * 60}, TaskContext(run_id="r1", llm=llm))
    assert res["judge"] == "split" and len(res["points"]) == 1

    bad = point_extract.run({"body": "a" * 60},
                            TaskContext(run_id="r1",
                                        llm=FakeLlm(['{"judge":"错误","points":[]}'])))
    assert bad["llm_used"] is False and "非法" in bad["error"]

    res3 = point_extract.run({"body": "a" * 60},
                             TaskContext(run_id="r1", llm=FakeLlm(broken=True)))
    assert res3["llm_used"] is False and res3["error"] == "模拟故障"


# ---- 流水线：规则判定（用户口径）----

def test_pipeline_integral_refined_via_llm(cfg, dl):
    """无分类条目 → integral（用户口径：剩下的全是方案），LLM 整条提炼（批次 92
    裁决：概要/全文照抄 → 整理后的知识陈述），理由落 meta 可抽检。"""
    _seed_entries(dl, 1, body="一套完整的 SQLite 慢查询排查方案，"
                              "先 EXPLAIN QUERY PLAN 看计划。细节 " * 8)
    llm = FakeLlm([_INTEGRAL_REFINE_REPLY])
    stats = run_points_extract(cfg, dl, limit=5, llm=llm)
    assert stats["processed"] == 1 and stats["integral"] == 1 and stats["split"] == 0
    assert stats["points_created"] == 1 and dl.count_points() == 1
    assert len(llm.calls) == 1 and "形态判定" not in llm.calls[0]  # 提炼-only
    p = dl.list_points()[0]
    assert p["judge"] == "integral" and p["source_count"] == 1
    assert "整条即点" in p["meta"]["judge_reason"]
    assert "EXPLAIN" in p["text"]                     # 提炼后的知识文本非照抄
    src = dl.point_sources_of(p["id"])[0]
    assert src.get("anchor")                          # quote 锚点随溯源落库


def test_pipeline_rule_split_by_category_path(cfg, dl):
    """分类路径含「文学创作」→ split（LLM 只切点）；祖先链命中（子分类也生效）。"""
    es2 = _seed_entries(dl, 1, body="问一：FTS5 trigram。问二：WAL 并发。补充说明 " * 8)
    es = _seed_entries(dl, 1, body="小说写法讨论：视角与节奏。示例 " * 8)
    _attach_lit(dl, es)                # 直接挂文学创作
    _attach_lit(dl, es2, child=True)   # 挂「文学创作 › 小说写法」（祖先命中）
    novel = ('{"summary":"写作两问",'
             '"points":[{"text":"小说视角选第三人称有限视角。","summary":"视角"},'
             '{"text":"节奏靠场景切换控制。","summary":"节奏"}]}')
    llm = FakeLlm([novel, _SPLIT_ONLY_REPLY])
    stats = run_points_extract(cfg, dl, limit=5, llm=llm)
    assert stats["integral"] == 0 and stats["split"] == 2
    assert stats["points_created"] == 4 and dl.count_points() == 4
    for call in llm.calls:
        assert "形态判定" not in call                  # 全部切点-only prompt
    pts = dl.list_points()
    assert all(p["judge"] == "split" for p in pts)
    assert all("用户口径" in p["meta"]["judge_reason"] for p in pts)


def test_pipeline_no_llm_integral_runs_split_errors(cfg, dl):
    """LLM 未启用：integral 照产（零费用不依赖 LLM），split 条目记 error 不阻塞。"""
    es = _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    es2 = _seed_entries(dl, 1, body="小说写法讨论：视角与节奏。示例 " * 8)
    _attach_lit(dl, es2)
    stats = run_points_extract(cfg, dl, limit=5)      # cfg 无 [llm] → llm=None
    assert stats["integral"] == 1 and dl.count_points() == 1
    assert len(stats["errors"]) == 1
    assert stats["errors"][0]["entry_id"] == es2[0].id
    assert "llm 未启用" in stats["errors"][0]["error"]
    assert dl.point_source_entry_ids() == {es[0].id}  # 仅 integral 推进游标


def test_pipeline_dedup_across_entries_one_point_multi_source(cfg, dl):
    """同观点重复文档：两文学创作条目切出同文点 → 一点两溯源（一点多溯源探针）。"""
    es = _seed_entries(dl, 2, body="FTS5 中文检索用 trigram 分词。" * 3)
    _attach_lit(dl, es)
    same = ('{"summary":"分词选型",'
            '"points":[{"text":"FTS5 中文检索用 trigram 分词。","summary":"分词"}]}')
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([same, same]))
    assert stats["points_created"] == 1 and stats["points_linked"] == 1
    assert dl.count_points() == 1
    assert dl.list_points()[0]["source_count"] == 2  # 一点多溯源


def test_pipeline_rerun_is_idempotent(cfg, dl):
    """重跑：已抽条目跳过（游标），零新调用零新点。"""
    _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_INTEGRAL_REFINE_REPLY]))
    llm2 = FakeLlm([])  # 任何多余调用都会抛「多余调用」→ 若不跳过必红
    stats2 = run_points_extract(cfg, dl, limit=5, llm=llm2)
    assert stats2["processed"] == 0 and stats2["points_total"] == 1
    assert stats2["skip_counts"]["already_done"] == 1
    assert len(llm2.calls) == 0


def test_pipeline_llm_failure_recorded_not_blocking(cfg, dl):
    """split 条目 LLM 故障 → errors 记录、不写点、不中断（重跑补抽）。"""
    es = _seed_entries(dl, 2, body="小说写法讨论：视角与节奏。示例 " * 8)
    _attach_lit(dl, es)
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm(broken=True))
    assert stats["processed"] == 0
    assert len(stats["errors"]) == 2
    assert dl.count_points() == 0
    assert dl.point_source_entry_ids() == set()       # 失败不推进游标


def test_pipeline_dry_run_writes_nothing(cfg, dl):
    _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_INTEGRAL_REFINE_REPLY]),
                               dry_run=True)
    assert stats["dry_run"] is True and stats["points_created"] == 1
    assert "points_total" not in stats
    assert dl.count_points() == 0                    # 未写库
    assert dl.point_source_entry_ids() == set()      # 游标未推进（重跑可真写）


def test_pipeline_long_body_goes_pending_kpe(cfg, dl):
    """P3（2026-10-26）：正文 > _BODY_CAP 不再截断抽点，落 meta.points_pending_kpe 交 kpe。

    旧口径（截断 6,000 字照抽）产出的点会「假装覆盖全文」——下游分诊/勘误据此判错源头。
    """
    e = _long_body_entry(dl, 9000, "pt-long-0001")
    _attach_lit(dl, [e])  # split 路径：旧口径会截断后送 LLM
    llm = FakeLlm([_SPLIT_ONLY_REPLY])
    stats = run_points_extract(cfg, dl, limit=5, llm=llm)
    assert stats["pending_kpe"] == 1
    assert stats["pending_kpe_detail"][0]["chars"] == 9000
    assert stats["processed"] == 0 and stats["points_created"] == 0
    assert llm.calls == []                            # 零 LLM 调用：不截断硬抽
    assert dl.count_points() == 0
    flag = dl.get_entry(e.id).meta["points_pending_kpe"]
    assert flag["chars"] == 9000 and flag["at"]


def test_pending_kpe_is_idempotent(cfg, dl):
    """标记在 → 下一轮直接跳过（不重复读全文、不重复写、零 LLM）。"""
    _long_body_entry(dl, 9000, "pt-long-0002")
    run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_SPLIT_ONLY_REPLY]))
    llm2 = FakeLlm([_SPLIT_ONLY_REPLY])
    stats2 = run_points_extract(cfg, dl, limit=5, llm=llm2)
    assert stats2["skip_counts"]["pending_kpe"] == 1
    assert stats2["pending_kpe"] == 0
    assert llm2.calls == []
    assert dl.count_points() == 0


def test_retry_blocked_does_not_bypass_pending_kpe(cfg, dl):
    """--retry-blocked 只绕过候选过滤，长文仍转 kpe（不退回截断抽点）。"""
    _long_body_entry(dl, 9000, "pt-long-0003")
    run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_SPLIT_ONLY_REPLY]))
    llm2 = FakeLlm([_SPLIT_ONLY_REPLY])
    stats2 = run_points_extract(cfg, dl, limit=5, llm=llm2, retry_blocked=True)
    assert stats2["pending_kpe"] == 1 and stats2["points_created"] == 0
    assert llm2.calls == []


def test_long_body_dry_run_writes_no_flag(cfg, dl):
    """dry-run 只报账不写标记（改口径后仍可重跑观察）。"""
    e = _long_body_entry(dl, 9000, "pt-long-0004")
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([]), dry_run=True)
    assert stats["pending_kpe"] == 1
    assert "points_pending_kpe" not in dl.get_entry(e.id).meta


def test_entry_body_prefers_longer_full_text(cfg, dl):
    """正文取 inline 预览与全文的较长者（短文档行为不变）。"""
    e = _long_body_entry(dl, 20000, "pt-long-0005")
    short = Entry.build(source_type="folder", source_key="pt:short:0", title="短预览",
                        locator="file:///d/short.md", inline_content="预览" * 50,
                        content_hash="pt-long-0005", meta={"source_type": "folder"})
    dl.upsert_entries([short])
    assert len(_entry_body(dl, short)) == 20000      # inline 100 字 < 全文 20,000 字
    assert len(_entry_body(dl, e)) == 20000          # 无 inline 时取全文


def test_entry_body_keeps_inline_when_no_full_text(cfg, dl):
    """没有 content_store 正文时保留 inline（不因缺全文而丢正文）。"""
    e = _seed_entries(dl, 1, body="文" * 2000)[0]
    assert len(_entry_body(dl, e)) == 2000


# ---- 流水线：目录信号三路（批次 67，用户粗规则）----

def test_mixed_dir_hint_word_routes_to_llm_judge(cfg, dl):
    """目录名含暗示词（其他/归档/…）→ 杂烩：走 LLM 形态判定（不 forced split）。"""
    es = [_folder(dl, "Data/测试/其他", f"文件{i}", sfx)
          for i, sfx in enumerate([".pdf", ".docx", ".xls"])]
    llm = FakeLlm([_INTEGRAL_REPLY] * 3)
    stats = run_points_extract(cfg, dl, limit=10, llm=llm)
    assert stats["mixed_dir"] == 3          # 三条全走 LLM 判定
    assert stats["integral"] == 3           # LLM 判回 integral（宁整勿碎偏置）
    assert len(llm.calls) == 3
    assert "再做形态判定" in llm.calls[0]    # 判定+提炼合一 prompt（非 forced）


def test_mixed_dir_code_suffixes_route_to_llm(cfg, dl):
    """代码/文本类后缀 ≥3 种 → 杂烩（用户原话「后端目录有 python 和 java」）。"""
    [_folder(dl, "Data/git/杂项目录", f"f{i}", sfx)
     for i, sfx in enumerate([".py", ".java", ".md"])]
    llm = FakeLlm([_SPLIT_JUDGE_REPLY] * 3)
    stats = run_points_extract(cfg, dl, limit=10, llm=llm)
    assert stats["mixed_dir"] == 3
    assert stats["split"] == 3              # LLM 判回 split → 切点


def test_office_suffix_mix_not_mixed(cfg, dl):
    """办公后缀混杂（docx/xlsx/pdf）≠ 杂烩：同项目工作流，仍 integral 提炼（不判定）。"""
    [_folder(dl, "Data/百卓/PECOS", f"方案{i}", sfx)
     for i, sfx in enumerate([".docx", ".xlsx", ".pdf"])]
    llm = FakeLlm([_INTEGRAL_REFINE_REPLY] * 3)
    stats = run_points_extract(cfg, dl, limit=10, llm=llm)
    assert stats["mixed_dir"] == 0
    assert stats["integral"] == 3
    assert len(llm.calls) == 3 and all("形态判定" not in c for c in llm.calls)
    # （真实库教训：PECOS 79 条方案防误伤——只整条提炼，不进判定）


def test_emmx_and_manual_immune_to_dir_rule(cfg, dl):
    """目录规则只作用于 folder 源：emmx（自有判定缓存口径）/manual（无目录信号）免疫。"""
    _folder(dl, "Data/测试/其他", "脑图", ".emmx")   # emmx 在杂烩目录 → 不参与
    batch = uuid.uuid4().hex[:6]
    m = Entry.build(source_type="manual", source_key=f"pt:mm:{batch}",
                    title="手动条目", locator=f"https://example.com/{batch}",
                    inline_content="手动正文内容足够长，超过最短门槛要求。" * 4,
                    meta={"source_type": "manual"})
    dl.upsert_entries([m])
    llm = FakeLlm([_INTEGRAL_REFINE_REPLY] * 2)  # 两条都 integral 提炼（不判定）
    stats = run_points_extract(cfg, dl, limit=10, llm=llm)
    assert stats["mixed_dir"] == 0
    assert len(llm.calls) == 2 and all("形态判定" not in c for c in llm.calls)


# ---- 条目级形态覆盖（批次 70）：meta.force_form 优先于目录/分类规则 ----

def test_force_form_integral_overrides_split_rule(cfg, dl):
    """文学创作条目 force_form=integral → 强制整条即一点（LLM 整条提炼），理由带口径标注。"""
    es = _seed_entries(dl, 1, body="小说写法讨论：视角与节奏。示例 " * 8)
    _attach_lit(dl, es)
    dl.merge_meta(es[0].id, {"force_form": "integral"})
    llm = FakeLlm([_INTEGRAL_REFINE_REPLY])
    stats = run_points_extract(cfg, dl, limit=5, llm=llm)
    assert stats["integral"] == 1 and stats["split"] == 0
    assert stats["force_overrides"] == 1
    assert len(llm.calls) == 1 and "形态判定" not in llm.calls[0]
    p = dl.list_points()[0]
    assert p["judge"] == "integral"
    assert "整条即点" in p["meta"]["judge_reason"]


def test_force_form_split_overrides_integral_rule(cfg, dl):
    """普通方案条目 force_form=split → 强制走 LLM 切点（覆盖优先于「剩下的全是方案」）。"""
    es = _seed_entries(dl, 1, body="问一：FTS5 trigram。问二：WAL 并发。补充说明 " * 8)
    dl.merge_meta(es[0].id, {"force_form": "split"})
    llm = FakeLlm([_SPLIT_ONLY_REPLY])
    stats = run_points_extract(cfg, dl, limit=5, llm=llm)
    assert stats["integral"] == 0 and stats["split"] == 1
    assert stats["force_overrides"] == 1 and stats["points_created"] == 2
    assert len(llm.calls) == 1 and "形态判定" not in llm.calls[0]  # 切点-only
    assert all(p["judge"] == "split" for p in dl.list_points())


def test_entry_ids_rerun_bypasses_cursor(cfg, dl):
    """entry_ids 指定重抽（批次 70 端点配套）：跳过游标重处理；全量跑仍幂等。"""
    es = _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_INTEGRAL_REFINE_REPLY]))
    # 指定重抽：游标已记该条目，但仍处理（调用方配套 purge_entry_points）
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_INTEGRAL_REFINE_REPLY]),
                               entry_ids=[es[0].id])
    assert stats["processed"] == 1
    assert stats["points_created"] == 0 and dl.count_points() == 1
    # 同文点 hash 相同 → 幂等归并（created=0，不重复建点）
    # 全量跑不受影响：游标仍在，跳过
    stats2 = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([]))
    assert stats2["processed"] == 0 and stats2["points_total"] == 1
    assert stats2["skip_counts"]["already_done"] == 1


def test_purge_entry_points_keeps_shared_drops_orphan(cfg, dl):
    """单条目清溯源（批次 70 配套）：共享点保留（溯源降为 1）、孤儿点级联删、游标随之清。"""
    es = _seed_entries(dl, 2, body="FTS5 中文检索用 trigram 分词。" * 3)
    _attach_lit(dl, es)
    same = ('{"summary":"分词选型",'
            '"points":[{"text":"FTS5 中文检索用 trigram 分词。","summary":"分词"}]}')
    run_points_extract(cfg, dl, limit=5, llm=FakeLlm([same, same]))
    pid = dl.list_points()[0]["id"]
    assert dl.list_points()[0]["source_count"] == 2  # 一点两溯源
    # 清第一条溯源：共享点保留
    assert dl.purge_entry_points(es[0].id, reason="test") == 1
    assert dl.count_points() == 1 and dl.list_points()[0]["source_count"] == 1
    # 清第二条：孤儿点级联删，游标清空
    assert dl.purge_entry_points(es[1].id, reason="test") == 1
    assert dl.count_points() == 0
    assert dl.point_source_entry_ids() == set()
    # 不存在的条目：0，不报错
    assert dl.purge_entry_points("nonexistent0000", reason="test") == 0


# ---- 骨架守门（批次 92 裁决 12：抓来的必须是知识不是页面骨架） ----

def _skeleton_body() -> str:
    return "\n".join(["Skip to content", "Sign in", "Notifications", "Fork",
                      "Star", "Pull requests", "Issues", "Actions", "Projects",
                      "Wiki", "Security", "Insights", "© 2026 All rights reserved"])


def test_pipeline_skeleton_body_skipped_and_marked(cfg, dl):
    """骨架正文不切片：meta.body_flag=skeleton 打标（degraded 等重抓/人工裁决），
    零点零游标零 LLM 调用——守门在提炼之前，宁缺毋脏。"""
    es = _seed_entries(dl, 1, body=_skeleton_body())
    llm = FakeLlm([])  # 任何 LLM 调用都会抛「多余调用」→ 守门必须前置
    stats = run_points_extract(cfg, dl, limit=5, llm=llm)
    assert stats["skeleton"] == 1 and stats["processed"] == 0
    assert stats["points_created"] == 0 and dl.count_points() == 0
    assert dl.point_source_entry_ids() == set()
    assert len(llm.calls) == 0
    assert dl.get_entry(es[0].id).meta["body_flag"] == "skeleton"


def test_pipeline_skeleton_dry_run_no_meta_write(cfg, dl):
    """dry-run：骨架条目计数但不写 body_flag（与不落点同一纪律）。"""
    es = _seed_entries(dl, 1, body=_skeleton_body())
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([]), dry_run=True)
    assert stats["skeleton"] == 1
    assert "body_flag" not in dl.get_entry(es[0].id).meta


def test_normal_body_not_skeleton_flagged(cfg, dl):
    """正常正文零误伤：无骨架标，照常提炼。"""
    es = _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_INTEGRAL_REFINE_REPLY]))
    assert "body_flag" not in dl.get_entry(es[0].id).meta
    assert dl.count_points() == 1


# ---- 自洽性闸门（TODO 8.5，用户裁决 1，2026-10-24） ----

_BARE_NOUN_REPLY = ('{"summary":"数组与对象，没有展开说明",'
                    '"points":[{"text":"JavaScript 数组","summary":"数组"}]}')
_EMPTY_POINTS_REPLY = '{"summary":"原文只有名词与目录，没有可独立成点的知识","points":[]}'
_MIXED_GATE_REPLY = ('{"summary":"一好一坏",'
                    '"points":[{"text":"JavaScript 数组","summary":"数组"},'
                    '{"text":"SQLite 慢查询排查：先用 EXPLAIN QUERY PLAN 看计划，'
                    '再补统计信息。","summary":"排查两步"}]}')


def test_point_extract_prompts_carry_self_consistency_rules():
    """生成层纪律：三份 prompt（判定/切点/整条提炼）都带自洽性与零产出许可。"""
    for prompt in (point_extract._SYSTEM_PROMPT, point_extract._SPLIT_ONLY_PROMPT,
                   point_extract._INTEGRAL_REFINE_PROMPT):
        assert "自洽性纪律" in prompt
        assert "裸名词" in prompt and "空数组" in prompt


def test_point_extract_empty_points_is_legal_not_error():
    """LLM 明确判定"无可独立成点"：llm_used=True、points=[]、不记 error（8.5）。"""
    res = point_extract.run({"body": "a" * 60, "forced_judge": "integral"},
                            TaskContext(run_id="r1",
                                        llm=FakeLlm([_EMPTY_POINTS_REPLY])))
    assert res["llm_used"] is True and res["points"] == []
    assert not res.get("error")


def test_pipeline_gate_rejects_bare_noun_and_blocks_entry(cfg, dl):
    """裸名词点不落库；整条全拒 → meta.points_gate；二次运行零 LLM 调用（不重复烧钱）。"""
    es = _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_BARE_NOUN_REPLY]))
    assert stats["points_rejected"] == 1 and stats["gate_blocked"] == 1
    assert stats["points_created"] == 0 and dl.count_points() == 0
    assert stats["reject_reasons"] == {"bare_noun": 1}
    assert stats["rejected"][0]["reason"] == "bare_noun"
    gate = dl.get_entry(es[0].id).meta["points_gate"]
    assert gate["status"] == "blocked" and gate["reasons"] == {"bare_noun": 1}

    llm2 = FakeLlm([])  # 多余调用必抛 → 阻断生效的硬断言
    stats2 = run_points_extract(cfg, dl, limit=5, llm=llm2)
    assert stats2["processed"] == 0
    assert stats2["skip_counts"]["gate_blocked"] == 1
    assert len(llm2.calls) == 0


def test_pipeline_gate_keeps_valid_points_from_mixed_reply(cfg, dl):
    """一好一坏：只丢坏点，好点照常落库；有条目产出时不打阻断标记。"""
    es = _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_MIXED_GATE_REPLY]))
    assert stats["points_rejected"] == 1 and stats["gate_blocked"] == 0
    assert stats["points_created"] == 1 and dl.count_points() == 1
    assert "points_gate" not in dl.get_entry(es[0].id).meta


def test_pipeline_gate_dry_run_counts_but_does_not_block(cfg, dl):
    """dry-run：闸门计数照出，但不写 points_gate（改口径后可重跑观察，不锁死条目）。"""
    es = _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    stats = run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_BARE_NOUN_REPLY]),
                               dry_run=True)
    assert stats["gate_blocked"] == 1 and stats["points_rejected"] == 1
    assert stats["points_created"] == 0 and dl.count_points() == 0
    assert "points_gate" not in dl.get_entry(es[0].id).meta


def test_pipeline_llm_empty_points_blocks_with_no_point_reason(cfg, dl):
    """LLM 明确返回空点：算"无点"而非故障——阻断重抽，meta 原因记 no_point。"""
    es = _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    stats = run_points_extract(cfg, dl, limit=5,
                               llm=FakeLlm([_EMPTY_POINTS_REPLY]))
    assert stats["gate_blocked"] == 1 and stats["points_rejected"] == 0
    assert stats["points_created"] == 0
    gate = dl.get_entry(es[0].id).meta["points_gate"]
    assert gate["reasons"] == {"no_point": 1}
    assert len(stats["errors"]) == 0          # 不当故障记录


def test_pipeline_retry_blocked_reclears_and_reextracts(cfg, dl):
    """--retry-blocked：清标记后重抽，产出合格点即解除阻断。"""
    es = _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_BARE_NOUN_REPLY]))
    assert "points_gate" in dl.get_entry(es[0].id).meta

    stats = run_points_extract(cfg, dl, limit=5,
                               llm=FakeLlm([_INTEGRAL_REFINE_REPLY]),
                               retry_blocked=True)
    assert stats["processed"] == 1 and stats["points_created"] == 1
    assert "points_gate" not in dl.get_entry(es[0].id).meta


def test_pipeline_entry_ids_clears_gate_marker(cfg, dl):
    """Web 条目级重抽（entry_ids）同样清标记：合/拆之后能立刻恢复自动抽取。"""
    es = _seed_entries(dl, 1, body="一套完整的排查方案，" + "细节 " * 60)
    run_points_extract(cfg, dl, limit=5, llm=FakeLlm([_BARE_NOUN_REPLY]))
    stats = run_points_extract(cfg, dl, limit=5,
                               llm=FakeLlm([_INTEGRAL_REFINE_REPLY]),
                               entry_ids=[es[0].id])
    assert stats["points_created"] == 1
    assert "points_gate" not in dl.get_entry(es[0].id).meta
