"""全部核心 dataclass 与枚举（完整方案 §3.1–3.3、§4.3）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# §3.2 source_type 白名单（canary 覆盖项：改动必须先写工单）
SOURCE_TYPES = (
    "bookmark", "folder", "emmx", "mail", "ima", "txdoc", "db", "session",
    "wxfav", "manual", "wxchat", "wxarticle", "bili",
)

# status 枚举：active=在库 / archived=源里消失（可复活） / rejected=用户明确舍弃（永不复活，
# 重新同步也不会重新加载——2026-10-19 用户需求）/ deleted=物理删除前过渡
STATUSES = ("active", "archived", "rejected", "deleted")

# §5 locator scheme 清单（canary 覆盖项）
SCHEMES = (
    "http", "https", "file", "mail", "ima", "txdoc", "emmx", "db", "session", "wxfav", "bili",
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class Entry:
    """统一条目（§3.1）。id 由 ids.entry_id 生成，禁止手工指定。"""

    id: str
    source_type: str
    title: str
    locator: str                  # 主 locator；其余见 entry_locators 表
    locator_canonical: str | None  # https 主 locator 的规范化形式；kadd 判重走此列索引
    native_path: str | None
    inline_content: str | None
    content_hash: str | None
    meta: dict[str, Any]
    created_at: str | None
    exported_at: str
    status: str = "active"

    @classmethod
    def build(
        cls,
        *,
        source_type: str,
        source_key: str,
        title: str,
        locator: str,
        locator_canonical: str | None = None,
        native_path: str | None = None,
        inline_content: str | None = None,
        content_hash: str | None = None,
        meta: dict[str, Any] | None = None,
        created_at: str | None = None,
        exported_at: str | None = None,
        status: str = "active",
    ) -> "Entry":
        """适配器构造条目的唯一入口：自动生成 id 与 exported_at。"""
        from .ids import entry_id

        return cls(
            id=entry_id(source_type, source_key),
            source_type=source_type,
            title=title,
            locator=locator,
            locator_canonical=locator_canonical,
            native_path=native_path,
            inline_content=inline_content,
            content_hash=content_hash,
            meta=meta if meta is not None else {},
            created_at=created_at,
            exported_at=exported_at or _now(),
            status=status,
        )


@dataclass(frozen=True)
class Category:
    """分类节点。path 为派生量（category_parents + 递归 CTE），不落库。"""

    id: str
    name: str
    note: str | None
    origin: str
    created_at: str
    path: str  # 派生首条路径；根分类为自身 name


@dataclass(frozen=True)
class UpsertResult:
    created: int
    updated: int
    unchanged: int
    ids: list[str]


@dataclass(frozen=True)
class FetchResult:
    """fetcher 产出；由 pipeline 经 datalayer.put_content 落库。"""

    text: str
    content_hash: str
    fetcher: str
    fetched_at: str
    degraded: bool = False


@dataclass(frozen=True)
class SearchHit:
    entry_id: str
    title: str
    locator: str
    snippet: str
    rank: float
