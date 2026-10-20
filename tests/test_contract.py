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
    # topic_recall / thread_suggest：串联工作区语义任务（0.2.0 第三十二批，§9.4）
    assert {"classify_coarse", "classify_deep", "tag_keywords",
            "topic_recall", "thread_suggest"} == {s.name for s in semantics.specs()}
