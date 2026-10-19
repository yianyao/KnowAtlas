"""L3 LLM 语义分类与全量重分类（0.2.0 提前落，原计划 M4）。

LLM 以 FakeLlm 替身测试——测试永不真调云端。
"""

from __future__ import annotations

import json

import pytest

from knowatlas.models import Entry
from knowatlas.pipeline.sync import run_sync
from knowatlas.semantic.base import SemanticInput, TaskContext
from knowatlas.semantic.llm import LlmError, extract_json_array
from knowatlas.semantic.tasks import classify_deep
from knowatlas.semantic.tasks.classify_coarse import run as run_coarse


class FakeLlm:
    """替身：按预设映射返回分类 JSON；记录收到的 prompt 供断言。"""

    def __init__(self, mapping: dict[str, str] | None = None, broken: bool = False):
        self.mapping = mapping or {}
        self.broken = broken
        self.calls: list[str] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append(user)
        if self.broken:
            raise LlmError("模拟故障")
        arr = []
        for line in user.splitlines():
            if line.strip() and line[0].isdigit():
                idx = int(line.split(".", 1)[0])
                title = line.split("标题:", 1)[1].split(" |", 1)[0] if "标题:" in line else ""
                path = self.mapping.get(title, "?")
                arr.append({"i": idx, "path": path, "conf": 0.9})
        return json.dumps(arr, ensure_ascii=False)


def test_extract_json_array_tolerant():
    assert extract_json_array('前言 ```json\n[{"i":1,"path":"a"}]\n``` 后记') == [{"i": 1, "path": "a"}]
    with pytest.raises(LlmError):
        extract_json_array("完全没有数组")


def test_classify_deep_llm_none_is_noop():
    """llm 未配置 → 全部空分类（进暂存区），绝不硬猜。"""
    inputs = [SemanticInput(entry_id="e1", title="某页", body=None,
                            native_path="书签栏", meta={"source_type": "bookmark"})]
    outs = classify_deep.run(inputs, TaskContext(run_id="r", llm=None))
    assert all(not o.classifications for o in outs)


def test_classify_deep_batch_parse_and_failure_isolation():
    inputs = [SemanticInput(entry_id=f"e{i}", title=f"页{i}", body=None,
                            native_path=None, meta={"source_type": "bookmark", "locator": f"https://h{i}.example/x"})
              for i in (1, 2, 3)]
    llm = FakeLlm(mapping={"页1": "技术开发/数据库"})
    outs = classify_deep.classify_batch(inputs, frozenset({"技术开发/数据库"}), llm, max_batch=2)
    assert outs[0].classifications[0].category_path == "技术开发/数据库"
    assert outs[0].classifications[0].origin == "llm"
    assert not outs[1].classifications and not outs[2].classifications  # 未映射 → "?"
    # 故障批次降级：全空，不抛
    broken = classify_deep.classify_batch(inputs, frozenset(), FakeLlm(broken=True))
    assert all(not o.classifications for o in broken)


def test_coarse_prior_hit_skips_llm():
    """L1 命中不消耗 LLM 调用（成本纪律）。"""
    llm = FakeLlm()
    inputs = [SemanticInput(entry_id="e1", title="随便", body=None,
                            native_path="其他书签/js", meta={"source_type": "bookmark"})]
    outs = run_coarse(inputs, TaskContext(run_id="r", llm=llm))
    assert outs[0].classifications[0].category_path == "技术开发/前端"
    assert llm.calls == []


def test_coarse_falls_through_to_llm():
    llm = FakeLlm(mapping={"大数据入门": "人工智能"})
    inputs = [SemanticInput(entry_id="e1", title="大数据入门", body=None,
                            native_path="其他书签/other", meta={"source_type": "bookmark",
                                                           "locator": "https://ai.example/x"})]
    outs = run_coarse(inputs, TaskContext(run_id="r", llm=llm, known_paths=frozenset({"人工智能"})))
    assert outs[0].classifications[0].category_path == "人工智能"
    assert outs[0].classifications[0].origin == "llm"
    assert len(llm.calls) == 1


def test_reclassify_skips_manual_and_reruns_rest(cfg, dl, registries):
    """reclassify：manual 挂接条目跳过；机器挂接按当前流水线重评。"""
    locators, semantics = registries
    e_keep = Entry.build(source_type="bookmark", source_key="edge:9001", title="人工校正过的",
                         locator="https://r.example/keep", locator_canonical="https://r.example/keep",
                         native_path="其他书签/other")
    e_re = Entry.build(source_type="bookmark", source_key="edge:9002", title="Python 教程",
                       locator="https://r.example/py", locator_canonical="https://r.example/py",
                       native_path="其他书签/other")
    dl.upsert_entries([e_keep, e_re])
    cat = dl.create_category("旧类", [], "rule")
    dl.attach_category(e_keep.id, cat.id, 0.8, "manual", "r0")
    dl.attach_category(e_re.id, cat.id, 0.8, "rule", "r0")

    stats = run_sync(cfg, dl, locators, semantics, reclassify=True)
    rec = stats["reclassify"]
    assert rec["reclassify_total"] == 1  # manual 条目被跳过
    assert "旧类" in {l["path"] for l in dl.get_entry_categories(e_keep.id)}
    # e_re：python 关键词命中规则 → 技术开发；旧类被 detach
    paths = {l["path"] for l in dl.get_entry_categories(e_re.id)}
    assert "技术开发" in paths and "旧类" not in paths
