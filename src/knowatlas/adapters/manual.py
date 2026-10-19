"""手动链接源（source_type=manual）：kadd 的极简适配器。

抓取由 pipeline.kadd 编排（fetch_with_fallback）；本模块只负责把"URL + 抓取结果"
翻译成统一条目。source_key = canonical URL（§3.2），重复粘贴同一 URL 幂等。
"""

from __future__ import annotations

from ..ids import canonical_url
from ..models import Entry

_INLINE_LIMIT = 4096
_TRUNCATED_AT = 4000


def build_manual_entry(url: str, title: str, text: str | None, content_hash: str | None,
                       fetcher: str, fetched_at: str) -> Entry:
    canonical = canonical_url(url)
    if canonical is None:
        raise ValueError(f"manual 源只收 http(s) URL：{url}")
    if text:
        if len(text) <= _INLINE_LIMIT:
            inline: str | None = text
        else:
            inline = text[:_TRUNCATED_AT] + "…[截断，全文在 content_store]"
        meta: dict = {
            "source_type": "manual",
            "fetch_backend": fetcher,
            "fetched_at": fetched_at,
        }
    else:
        inline = None
        meta = {"source_type": "manual", "fetch": "title_only"}
    return Entry.build(
        source_type="manual",
        source_key=canonical,
        title=title or url,
        locator=url,
        locator_canonical=canonical,
        inline_content=inline,
        content_hash=content_hash,
        meta=meta,
    )
