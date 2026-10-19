"""抓取路由与上下文（完整方案 §9.3）：升级路由集中在此，不在各适配器。"""

from __future__ import annotations

from ..errors import DegradedParseError, FetchError
from ..registry.capability import FetchContext, LocatorRegistry  # re-export 便于上层单一导入


def fetch_with_fallback(locator: str, locators: LocatorRegistry, ctx: FetchContext) -> tuple[str, str]:
    """返回 (text, title)。

    - http/https：走双后端路由（simple 失败/正文过短 → fallback_backend，当前为 DeepSeek Fetch）；
    - 其余 scheme：按注册表分发到唯一 handler。
    已命中 content_store 的条目在 pipeline 层短路（hash 命中不调任何后端，零成本）；
    inline_content 已内联的条目不过 fetcher 直传。
    """
    scheme = locator.split("://", 1)[0].lower()
    if scheme in ("http", "https"):
        return _fetch_http_with_fallback(locator, ctx)
    _spec, handler = locators.resolve(locator)
    return handler(locator, ctx)


def _fetch_http_with_fallback(locator: str, ctx: FetchContext) -> tuple[str, str]:
    from . import http_simple

    try:
        return http_simple.fetch_page(locator, ctx)
    except (FetchError, DegradedParseError) as primary_exc:
        fallback = str(ctx.config.get("fetch.fallback_backend") or "").strip()
        if not fallback or fallback == str(ctx.config.get("fetch.default_backend") or "simple"):
            raise
        try:
            from . import http_deepseek  # noqa: F401  导入成功才尝试升级
        except ImportError:
            raise primary_exc
        from . import http_deepseek

        return http_deepseek.fetch_page(locator, ctx)
