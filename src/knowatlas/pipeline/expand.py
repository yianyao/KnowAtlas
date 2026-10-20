"""书签扩散抓取（0.2.0 第四十批，TODO Phase 2；用户 2026-10-20 需求）。

「像微信收藏全扒一样」：书签种子不只抓原文，还抓**同一目录页同一主题**的内容。
显式触发（`ksync --expand <entry_id>`），绝不自动跑；纯规则、可解释（relation_reason
纪律），LLM 相似判定后置。

扩散线索 = 种子页内链接中与种子**同目录**（同 scheme+host+父目录路径）者。整站
同 host 链接不收——导航/推荐噪音会演变成全站爬取，违背「显式触发、小步扩充」。

候选过滤链（顺序固定）：canonical 化去锚 → 排除种子自身 → 未入库
（find_by_canonical / find_by_locator）→ L0 价值守卫（judge_value 放行）→ limit 截断。
命中的候选逐条 fetch_with_fallback 抓正文入库：source_type="expand"
（bookmark 会被书签源 full 同步 archive_missing 归档；manual 语义不准），
meta 记 seed_entry_id + expand_reason（关联解释），照常走 classify_coarse 分类。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from ..errors import KnowAtlasError
from ..fetchers.base import fetch_with_fallback
from ..ids import canonical_url, content_hash
from ..models import Entry, FetchResult
from ..registry.capability import FetchContext
from ..semantic.base import SemanticInput, TaskContext
from .kadd import ensure_category_path

_USER_AGENT = "KnowAtlas/0.1 (+personal knowledge indexer)"
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.IGNORECASE)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parent_dir(url: str) -> tuple[str, str]:
    """(host, 父目录路径)。根路径页面父目录 = "/"。"""
    parts = urlsplit(url)
    path = parts.path or "/"
    if path.endswith("/"):
        parent = path
    else:
        parent = path.rsplit("/", 1)[0] + "/"
    return (parts.hostname or "").lower(), parent


def _same_dir(seed_url: str, cand_url: str) -> bool:
    """同目录判定：scheme+host+父目录路径一致。"""
    a, b = urlsplit(seed_url), urlsplit(cand_url)
    return (_parent_dir(seed_url) == _parent_dir(cand_url)
            and a.scheme.lower() == b.scheme.lower())


def _candidate_links(seed_url: str, html: str) -> list[str]:
    """从种子 HTML 提取同目录链接：urljoin 归一 → 去锚 → 同目录过滤 → 保序去重。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in _HREF_RE.findall(html):
        joined = urljoin(seed_url, raw.strip())
        canon = canonical_url(joined)
        if canon is None or canon in seen:
            continue
        seen.add(canon)
        if _same_dir(seed_url, joined):
            out.append(joined)
    return out


def expand_seed(cfg: Any, dl: Any, locators: Any, semantics: Any,
                seed_entry_id: str, limit: int = 20) -> dict[str, Any]:
    """对单个种子条目做一轮同目录扩散。返回统计 dict。"""
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "expand")
    stats: dict[str, Any] = {"seed": seed_entry_id, "candidates": 0,
                             "created": 0, "fetch_failed": 0,
                             "blocked_by_guard": 0, "already_known": 0}
    try:
        seed = dl.get_entry(seed_entry_id)
        if seed is None:
            raise KnowAtlasError(f"种子条目不存在：{seed_entry_id}",
                                 hint="entry_id 可在条目详情/URL 中查看")
        canon_seed = canonical_url(seed.locator)
        if canon_seed is None:
            raise KnowAtlasError(
                f"种子不是 http(s) 条目，无法扩散：{seed.locator}",
                hint="扩散只支持网页书签（http/https locator）")

        # 现抓种子 HTML（content_store 存的是 readability 纯文本，链接已丢）
        with httpx.Client() as client:
            ctx = FetchContext(config=cfg, datalayer=dl, http=client, run_id=run_id)
            try:
                resp = client.get(seed.locator, follow_redirects=True,
                                  timeout=float(cfg.get("fetch.timeout_seconds", 20)),
                                  headers={"User-Agent": _USER_AGENT})
            except Exception as exc:
                raise KnowAtlasError(
                    f"种子页面抓取失败：{seed.locator}（{exc}）",
                    hint="扩散需重新读取种子页 HTML 以提取同目录链接；检查网络后重试") from exc
            if resp.status_code >= 400:
                raise KnowAtlasError(
                    f"种子页面 HTTP {resp.status_code}：{seed.locator}",
                    hint="种子页可能已失效；可先跑 kcheck 体检")
            from ..semantic.value_guard import judge_value

            candidates: list[str] = []
            for link in _candidate_links(seed.locator, resp.text):
                c = canonical_url(link)
                if c == canon_seed:
                    stats["already_known"] += 1                 # 种子自身
                    continue
                stats["candidates"] += 1
                if dl.find_by_canonical(c) is not None \
                        or dl.find_by_locator(link):
                    stats["already_known"] += 1                 # 已入库（canonical 去重）
                    continue
                reason = judge_value(link)
                if reason is not None:
                    stats["blocked_by_guard"] += 1              # L0：门户/列表/资源页
                    continue
                candidates.append(link)
                if len(candidates) >= max(1, int(limit)):
                    break

            created_ids: list[str] = []
            for link in candidates:
                try:
                    text, title = fetch_with_fallback(link, locators, ctx)
                except Exception as exc:
                    stats["fetch_failed"] += 1
                    dl.log_task(_now(), "expand", "fetch_fail", link,
                                {"error": str(exc)[:160], "run_id": run_id})
                    continue
                c = canonical_url(link)
                entry = Entry.build(
                    source_type="expand",
                    source_key=f"expand:{seed_entry_id}:{c}",
                    title=title or link.rsplit("/", 1)[-1] or link,
                    locator=link,
                    locator_canonical=c,
                    inline_content=text[:4000]
                    + ("…[截断，全文在 content_store]" if len(text) > 4000 else ""),
                    content_hash=content_hash(text),
                    native_path=_parent_dir(seed.locator)[1],
                    meta={"source_type": "expand", "seed_entry_id": seed_entry_id,
                          "expand_reason": "series_same_dir"},
                    created_at=_now(),
                )
                dl.upsert_entries([entry])
                dl.put_content(FetchResult(
                    text=text, content_hash=entry.content_hash,
                    fetcher=str(cfg.get("fetch.default_backend", "simple")),
                    fetched_at=_now()))
                dl.log_task(_now(), "expand", "create", entry.id,
                            {"seed": seed_entry_id, "url": link,
                             "reason": "series_same_dir", "run_id": run_id})
                created_ids.append(entry.id)
                stats["created"] += 1

            # 分类：复用 kadd 链路（L0 已过滤，classify_coarse 的 L0 短路不会误标）
            if created_ids:
                _categorize(dl, semantics, cfg,
                            [dl.get_entry(eid) for eid in created_ids if dl.get_entry(eid)],
                            run_id)
            stats["entry_ids"] = created_ids
            dl.log_task(_now(), "expand", "done", seed_entry_id, stats)
            return stats
    finally:
        dl.finish_run(run_id, stats)


def _categorize(dl: Any, semantics: Any, cfg: Any, entries: list[Any],
                run_id: str) -> None:
    """扩散条目批量 classify_coarse（与 sync._categorize 同款，未命中进暂存区）。"""
    from ..semantic.llm import LlmClient

    if not entries:
        return
    _, classify = semantics.resolve_task("classify_coarse")
    known = frozenset(dl.all_category_paths())
    inputs = [SemanticInput(entry_id=e.id, title=e.title, body=e.inline_content,
                            native_path=e.native_path,
                            meta={**e.meta, "locator": e.locator})
              for e in entries]
    outputs = classify(inputs, TaskContext(run_id=run_id, known_paths=known,
                                           llm=LlmClient.from_config(cfg), config=cfg))
    for entry, out in zip(entries, outputs):
        for classification in out.classifications:
            cid = ensure_category_path(dl, classification.category_path,
                                       classification.origin)
            dl.attach_category(entry.id, cid, classification.confidence,
                               classification.origin, run_id)
