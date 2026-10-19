"""kadd 全链路（完整方案 §12 步骤 5–7，M0.5 垂直切片）。

建条目 → 抓取（双后端路由）→ content_store → classify_coarse（L1/L2）→ 分类挂接 /
暂存区兜底 → task_log 审计。重复 URL（canonical 命中）幂等，不重复建条目。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..adapters.manual import build_manual_entry
from ..errors import DegradedParseError, FetchError, LocatorFormatError
from ..fetchers.base import fetch_with_fallback
from ..ids import canonical_url, content_hash
from ..models import FetchResult
from ..registry.capability import FetchContext, LocatorRegistry, SemanticRegistry
from ..semantic.base import SemanticInput, TaskContext

_KADD_LOG_FIELDS = ("url", "canonical", "fetched")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _fallback_title(url: str) -> str:
    path = urlsplit(url).path or url
    return path.rstrip("/").rsplit("/", 1)[-1] or url


def ensure_category_path(dl: Any, path: str, origin: str) -> str:
    """按 "/" 逐级查找/创建分类，返回叶子分类 id（H4：路径唯一命中→归并，未命中→创建）。"""
    parts = [p for p in path.split("/") if p]
    parent_ids: list[str] = []
    accumulated = ""
    cid = ""
    for part in parts:
        accumulated = f"{accumulated}/{part}" if accumulated else part
        existing = dl.get_category_by_path(accumulated)
        if existing is None:
            cid = dl.create_category(part, parent_ids, origin).id
        else:
            cid = existing.id
        parent_ids = [cid]
    return cid


def ingest_url(cfg: Any, dl: Any, locators: LocatorRegistry, semantics: SemanticRegistry,
               url: str, run_id: str) -> dict[str, Any]:
    """单条 URL 的完整入口链路。返回摘要 dict（entry_id / status / fetched / categorized）。"""
    canon = canonical_url(url)
    if canon is None:
        raise LocatorFormatError(f"不是可收录的 http(s) URL：{url}",
                                 hint="本地文件请走 folder 源或 file:// locator")

    existing = dl.find_by_canonical(canon)
    if existing is not None:
        if existing.locator != url:
            dl.attach_locator(existing.id, url)
        dl.log_task(_now(), "kadd", "import", existing.id,
                    {"canonical": canon, "dedupe": "canonical_hit"})
        return {"entry_id": existing.id, "status": "duplicate",
                "fetched": False, "categorized": True}

    # ---- 抓取（K1：抓取只发生在 kadd / 用户主动，不在同步里）----
    text: str | None = None
    title = ""
    fhash: str | None = None
    fetcher = ""
    fetched = False
    fetch_error: str | None = None
    if urlsplit(url).scheme in ("http", "https"):
        ctx = FetchContext(config=cfg, datalayer=dl,
                           http=httpx.Client(), run_id=run_id)
        try:
            text, title = fetch_with_fallback(url, locators, ctx)
            fetched = True
            fetcher = str(cfg.get("fetch.default_backend", "simple"))
        except (FetchError, DegradedParseError) as exc:
            fetch_error = str(exc)[:200]  # 标题级条目进暂存区，绝不硬猜

    if text:
        fhash = content_hash(text)

    entry = build_manual_entry(url, title, text, fhash, fetcher, _now())
    result = dl.upsert_entries([entry])
    if text and fhash:
        dl.put_content(FetchResult(text=text, content_hash=fhash,
                                   fetcher=fetcher or "unknown", fetched_at=_now()))
    dl.log_task(_now(), "kadd", "import", entry.id,
                {"url": url, "canonical": canon, "fetched": fetched,
                 **({"fetch_error": fetch_error} if fetch_error else {})})

    # ---- 分类（L1/L2/L3；未命中 → 未分类暂存区）----
    categorized = False
    if text or entry.inline_content:
        _, classify = semantics.resolve_task("classify_coarse")
        from ..semantic.llm import LlmClient

        known = frozenset(dl.all_category_paths())
        outputs = classify(
            [SemanticInput(entry_id=entry.id, title=entry.title,
                           body=text or entry.inline_content,
                           native_path=entry.native_path,
                           meta={**entry.meta, "locator": url})],
            TaskContext(run_id=run_id, known_paths=known,
                        llm=LlmClient.from_config(cfg), config=cfg),
        )
        for classification in outputs[0].classifications:
            cid = ensure_category_path(dl, classification.category_path, classification.origin)
            dl.attach_category(entry.id, cid, classification.confidence,
                               classification.origin, run_id)
            categorized = True

    return {
        "entry_id": entry.id,
        "status": "created" if result.created else "updated",
        "fetched": fetched,
        "categorized": categorized,
        **({"fetch_error": fetch_error} if fetch_error else {}),
    }
