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
    # aging_judge：老化 L2 时效复核（第六十三批，Phase 7 批次 64a，方案 §7.5）
    assert {"classify_coarse", "classify_deep", "tag_keywords", "topic_recall",
            "thread_suggest", "delta_summarize",
            "thread_digest", "point_extract", "aging_judge"} == {s.name for s in semantics.specs()}
