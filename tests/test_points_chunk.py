"""长网页分块抽取（R16，变更工单-2026-10-27-长网页分块抽取）。

覆盖：切块器（边界/上限/偏移/不丢字）、6k–60k 在管道内分块并合并点、
>60,000 仍落 points_pending_kpe、LLM 未启用时长文不分块。
"""

from __future__ import annotations

import uuid

from knowatlas.models import Entry, FetchResult
from knowatlas.pipeline.points import (
    _BODY_CAP, _CHUNK_TOTAL_MAX, _chunk_body, run_points_extract,
)
from knowatlas.semantic.llm import LlmError

_SENT = "分块抽取要保证偏移正确。"


class ChunkLlm:
    """按调用序返回可区分的点；quote 用正文里确实存在的句子（验证全文偏移）。"""

    def __init__(self, points_per_chunk: int = 1):
        self.calls: list[str] = []
        self.points_per_chunk = points_per_chunk

    def chat(self, system: str, user: str) -> str:
        self.calls.append(system + "\n" + user)
        n = len(self.calls)
        if n > 50:
            raise LlmError("调用次数异常")
        pts = [{"text": f"第 {n} 块要点：分块抽取先按段落切，再逐块提炼知识陈述。",
                "summary": f"块 {n}", "quote": _SENT}
               for _ in range(self.points_per_chunk)]
        import json
        return json.dumps({"summary": f"块 {n}", "points": pts},
                          ensure_ascii=False)


def _make_body(chars: int) -> str:
    parts: list[str] = []
    i = 0
    total = 0
    while total < chars:
        part = f"第{i}段。" + _SENT * 3 + "\n\n"
        parts.append(part)
        total += len(part)
        i += 1
    return "".join(parts)[:chars]


def _long_entry(dl, chars: int) -> Entry:
    key = uuid.uuid4().hex[:12]
    body = _make_body(chars)
    dl.put_content(FetchResult(text=body, content_hash=key, fetcher="test",
                               fetched_at="2026-10-27T00:00:00+08:00"))
    e = Entry.build(source_type="folder", source_key=f"chunk:{key}:0",
                    title=f"长文 {chars}", locator=f"file:///d/{key}.md",
                    inline_content=None, content_hash=key,
                    meta={"source_type": "folder"})
    dl.upsert_entries([e])
    return e


# ---- 切块器 ----

def test_chunk_body_short_is_single_chunk():
    body = "短正文一段。"
    assert _chunk_body(body) == [(0, body)]


def test_chunk_body_keeps_offsets_and_covers_text():
    body = _make_body(15_000)
    chunks = _chunk_body(body)
    assert len(chunks) >= 3
    assert all(len(text) <= _BODY_CAP for _, text in chunks)
    for base, text in chunks:
        # 偏移是全文坐标：按偏移切出来必须逐字相同
        assert body[base:base + len(text)] == text
    # 块之间首尾相接，只有空白被剥掉，没有整段丢失
    for (b1, t1), (b2, _t2) in zip(chunks, chunks[1:]):
        assert body[b1 + len(t1):b2].strip() == ""
    assert chunks[0][0] == 0
    assert chunks[-1][0] + len(chunks[-1][1]) == len(body.rstrip())


def test_chunk_body_prefers_paragraph_boundary():
    para = "这是一个完整段落。" * 40 + "\n\n"          # 每段 320 字
    body = para * 30                                    # 9600 字
    chunks = _chunk_body(body)
    assert all(len(t) <= _BODY_CAP for _, t in chunks)
    # 段落在窗口后 40% 处存在，切点必须落在段落边界上（不硬切）
    assert all(t.endswith("。") or t.endswith("\n") for _, t in chunks[:-1])


def test_chunk_body_hard_cuts_single_long_paragraph():
    body = "无标点长串" * 3_000                          # 15000 字、无任何切点
    chunks = _chunk_body(body)
    assert len(chunks) >= 3
    assert all(len(t) <= _BODY_CAP for _, t in chunks)
    assert "".join(t for _, t in chunks) == body


# ---- 管道 ----

def test_pipeline_chunks_medium_long_entry(cfg, dl):
    """6k–60k：分块抽取、点合并、溯源偏移回到全文、meta 打点且清旧标记。"""
    e = _long_entry(dl, 13_000)
    dl.merge_meta(e.id, {"points_pending_kpe": {"chars": 13_000, "at": "x"}})
    llm = ChunkLlm()
    stats = run_points_extract(cfg, dl, limit=5, llm=llm)
    assert stats["chunked"] == 1
    assert stats["chunks_total"] == len(llm.calls) >= 3
    assert stats["pending_kpe"] == 0
    assert stats["points_created"] == len(llm.calls)      # 每块一条不同文本
    assert dl.count_points() == len(llm.calls)
    stored = dl.get_entry(e.id)
    assert stored.meta["points_chunked"]["chunks"] == len(llm.calls)
    assert stored.meta.get("points_pending_kpe") is None  # 旧标记被消化
    body = _make_body(13_000)
    for p in dl.list_points():
        src = dl.point_sources_of(p["id"])[0]
        off = src["char_offset"]
        assert off is not None                            # 锚点仍在全文里定位得到
        assert body[off:off + len(_SENT)] == _SENT


def test_pipeline_above_total_cap_goes_to_kpe(cfg, dl):
    """> _CHUNK_TOTAL_MAX：不分块，仍写 points_pending_kpe，零 LLM 调用。"""
    e = _long_entry(dl, _CHUNK_TOTAL_MAX + 5_000)
    llm = ChunkLlm()
    stats = run_points_extract(cfg, dl, limit=5, llm=llm)
    assert stats["pending_kpe"] == 1 and stats["chunked"] == 0
    assert stats["points_created"] == 0 and len(llm.calls) == 0
    assert dl.get_entry(e.id).meta["points_pending_kpe"]["chars"] > _CHUNK_TOTAL_MAX


def test_pipeline_long_body_without_llm_stays_pending(cfg, dl):
    """LLM 未启用：长文不分块（照抄 6000 字/块无提炼价值），仍等 kpe。"""
    e = _long_entry(dl, 9_000)
    stats = run_points_extract(cfg, dl, limit=5)          # cfg 无 [llm] → llm=None
    assert stats["chunked"] == 0 and stats["pending_kpe"] == 1
    assert stats["points_created"] == 0
    assert dl.get_entry(e.id).meta["points_pending_kpe"]["chars"] == 9_000