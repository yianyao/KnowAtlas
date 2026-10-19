"""CapabilitySpec + 两个注册表（完整方案 §4.1–4.3）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..errors import DuplicateCapabilityError, UnknownSchemeError
from ..models import FetchResult


@dataclass(frozen=True)
class CapabilitySpec:
    """能力描述：名字 + 输入/输出契约 + 语义化版本。输出结构变更必须升版。"""

    name: str                       # 注册表键：scheme 名或 task 名
    input_contract: dict[str, str] = field(default_factory=dict)
    output_contract: dict[str, str] = field(default_factory=dict)
    version: str = "1.0.0"
    description: str = ""


# ---- Locator Handler 注册表（契约二·第一张） ----

LocatorHandler = Callable[[str, "FetchContext"], "tuple[str, str]"]
"""handler(locator, ctx) -> (text, title)；抛 FetchError/DegradedParseError 表示失败。"""


@dataclass
class FetchContext:
    """抓取上下文：配置 + 缓存查询（写入必须走 datalayer.put_content）+ 共享 http 客户端。"""

    config: Any                     # knowatlas.config.Config
    datalayer: Any                  # knowatlas.datalayer.db.DataLayer（只读查询缓存用）
    http: Any                       # httpx.Client
    run_id: str


class LocatorRegistry:
    """scheme -> handler。重名注册直接抛错；未注册 scheme 不静默跳过。"""

    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}
        self._handlers: dict[str, LocatorHandler] = {}

    def register(self, spec: CapabilitySpec, handler: LocatorHandler) -> None:
        if spec.name in self._specs:
            raise DuplicateCapabilityError(f"locator handler 重复注册：{spec.name}")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def resolve(self, locator: str) -> tuple[CapabilitySpec, LocatorHandler]:
        scheme = locator.split("://", 1)[0].lower()
        if scheme not in self._specs:
            raise UnknownSchemeError(
                f"未注册 scheme：{scheme}",
                hint="在 registry/builtins.py 登记对应 handler（新能力 = 新文件 + 一行注册）",
            )
        return self._specs[scheme], self._handlers[scheme]

    def specs(self) -> tuple[CapabilitySpec, ...]:
        return tuple(self._specs.values())


# ---- Semantic Task 注册表（契约二·第二张） ----

SemanticProcessor = Callable[[list, "TaskContext"], list]


class SemanticRegistry:
    """task_name -> processor。"""

    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}
        self._processors: dict[str, SemanticProcessor] = {}

    def register(self, spec: CapabilitySpec, processor: SemanticProcessor) -> None:
        if spec.name in self._specs:
            raise DuplicateCapabilityError(f"semantic task 重复注册：{spec.name}")
        self._specs[spec.name] = spec
        self._processors[spec.name] = processor

    def resolve_task(self, task_name: str) -> tuple[CapabilitySpec, SemanticProcessor]:
        if task_name not in self._specs:
            raise UnknownSchemeError(
                f"未注册 semantic task：{task_name}",
                hint="在 registry/builtins.py 登记对应 task",
            )
        return self._specs[task_name], self._processors[task_name]

    def specs(self) -> tuple[CapabilitySpec, ...]:
        return tuple(self._specs.values())


def put_content_note() -> str:  # pragma: no cover - 文档性占位
    """fetcher 不碰库：FetchResult 由 pipeline 经 datalayer.put_content 落库。"""
    return FetchResult.__doc__ or ""
