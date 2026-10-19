"""SourceAdapter 协议与 AdapterOutput（完整方案 §2）。

纪律：适配器绝不抓网页、绝不分类、绝不清洗正文，只做"翻译"——
读取原始形态 → 输出统一条目列表（抓取由 fetchers 在 pipeline 层完成）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..models import Entry


@dataclass(frozen=True)
class AdapterOutput:
    entries: list[Entry]
    stats: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """每个知识源一个实现；name 与 config [sources.<name>] 对应。"""

    name: str

    def collect(self, ctx: Any) -> AdapterOutput:
        """ctx 为适配器上下文（config 等）；源读取失败抛 AdapterError（跳过整个源）。"""
        ...
