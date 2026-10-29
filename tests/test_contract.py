"""契约二测试：注册表行为（重复注册拒绝、未注册 scheme 拒绝）。"""

from __future__ import annotations

import pytest

from knowatlas.errors import DuplicateCapabilityError, UnknownSchemeError
from knowatlas.registry.capability import CapabilitySpec, LocatorRegistry


def test_duplicate_registration_rejected():
    reg = LocatorRegistry()
    spec = CapabilitySpec("https", {}, {}, "1.0.0")
    reg.register(spec, lambda locator, ctx: ("t", "title"))
    with pytest.raises(DuplicateCapabilityError):
        reg.register(spec, lambda locator, ctx: ("t", "title"))


def test_unknown_scheme_rejected(registries):
    locators, _ = registries
    with pytest.raises(UnknownSchemeError):
        locators.resolve("ftp://example.org/x")


def test_builtin_specs_present(registries):
    locators, semantics = registries
    assert {"http", "https", "file"} == {s.name for s in locators.specs()}
    # topic_recall / thread_suggest：串联工作区语义任务（0.2.0 第三十二批，§9.4）；
    # delta_summarize / thread_digest：线程语义压缩（第五十五批，§9.4 LLM 后置层）；
    # point_extract：知识点抽取（第六十二批，Phase 7 批次 61a，方案 §7.1）；
    # aging_judge：老化 L2 时效复核（第六十三批，Phase 7 批次 64a，方案 §7.5）；
    # errata_check：勘误 L2 事实核查（第六十四批，Phase 7 批次 65a，方案 §7.6）；
    # point_aging：点级老化 L2（批次 93，裁决 #14 条目过时不连坐点）；
    # point_explain：大白话释疑（批次 90，方案 §9 点卡片 LLM 解释+示例）；
    # point_triage：点分诊（P0，2026-10-25 裁决，变更工单-2026-10-25-点分诊.md）；
    # point_errata：点级勘误（P1，2026-10-25 裁决，变更工单-2026-10-25-P1点级勘误.md）；
    # point_lifecycle：点级老化两型（P2，2026-10-26，变更工单-2026-10-26-P2点级老化两型.md）；
    # point_dupe_judge：去重边界对裁定（R30，2026-10-29，变更工单-2026-10-29-dedupe误并裁定.md）；
    # synthesize：知识梳理合成层（批次 69，§7.9 勾点生成方案，回灌+隔离+强制溯源）
    assert {"classify_coarse", "classify_deep", "tag_keywords", "topic_recall",
            "thread_suggest", "delta_summarize",
            "thread_digest", "point_extract", "aging_judge",
            "errata_check", "point_aging", "point_explain",
            "point_triage", "point_errata", "point_lifecycle",
            "point_dupe_judge", "synthesize"} == {
                s.name for s in semantics.specs()}
