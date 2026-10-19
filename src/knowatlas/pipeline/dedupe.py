"""跨源去重（完整方案 §12 步骤 14，M2 实现）。

M2 落地内容：canonical 命中 / content_hash 命中 / simhash 近似 / embedding 余弦
→ 命中已有条目时走 dl.attach_locator（双 locator 进 entry_locators 表，可跳转）。
当前仅提供 canonical/hash 的基础判断供上游使用。
"""

from __future__ import annotations

from ..ids import canonical_url, content_hash  # noqa: F401  re-export


def is_same_url(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    ca, cb = canonical_url(a), canonical_url(b)
    return ca is not None and ca == cb
