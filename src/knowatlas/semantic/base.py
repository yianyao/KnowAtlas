"""语义层基础结构（完整方案 §4.3）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Classification:
    category_path: str   # 规范路径；入库时按派生路径匹配现有分类（H4 路径解析规则）
    confidence: float    # 0.0–1.0
    origin: str          # prior / rule / embedding / llm / manual


@dataclass(frozen=True)
class SemanticInput:
    entry_id: str
    title: str
    body: str | None            # inline_content 或 content_store 文本；可空
    native_path: str | None
    meta: dict[str, Any]        # 约定 meta["source_type"] 携带来源类型（先验级使用）


@dataclass(frozen=True)
class SemanticOutput:
    classifications: list[Classification]   # 至少 1 条；空列表 = 明确"无法归类"（进暂存区）
    tags: list[str] = field(default_factory=list)
    summary: str | None = None


@dataclass(frozen=True)
class TaskContext:
    run_id: str
    llm: Any | None = None       # llm.enabled=false 或 key 未设时为 None（L3 跳过）
    embedder: Any | None = None  # optional 依赖缺失时为 None
    known_paths: frozenset[str] = frozenset()  # 现有分类路径（任务须优先归并）
    config: Any | None = None    # Config 访问器（任务读取自身参数如 llm.max_batch）
