"""simple 网页抓取后端：httpx + readability-lxml（零成本，默认）。"""

from __future__ import annotations

from ..errors import DegradedParseError, FetchError
from ..registry.capability import FetchContext

_USER_AGENT = "KnowAtlas/0.1 (+personal knowledge indexer)"


def fetch_page(locator: str, ctx: FetchContext) -> tuple[str, str]:
    """抓取并提取正文，返回 (text, title)。

    失败 = 抛 FetchError（网络/HTTP 错误）或 DegradedParseError（提取失败）；
    正文长度 < min_content_chars 视为提取失败（触发升级路由，§9.3）。
    """
    try:
        resp = ctx.http.get(
            locator,
            follow_redirects=True,
            timeout=float(ctx.config.get("fetch.timeout_seconds", 20)),
            headers={"User-Agent": _USER_AGENT},
        )
    except Exception as exc:  # httpx 传输层异常统一转 FetchError
        raise FetchError(f"请求失败：{exc}", hint="检查网络；或等待自动升级 DeepSeek 后端") from exc
    if resp.status_code >= 400:
        raise FetchError(f"HTTP {resp.status_code}：{locator}",
                         hint="需要登录/反爬的页面不属于 simple 后端能力范围")
    html = resp.text
    try:
        from lxml import html as lxml_html
        from readability import Document
    except ImportError as exc:
        raise DegradedParseError("readability-lxml 未安装", hint="pip install -r requirements-core.txt") from exc
    try:
        doc = Document(html)
        title = (doc.short_title() or "").strip()
        summary_html = doc.summary(html_partial=True)
        text = lxml_html.fromstring(summary_html).text_content().strip()
    except Exception as exc:
        raise DegradedParseError(f"readability 提取失败：{exc}") from exc

    min_chars = int(ctx.config.get("fetch.min_content_chars", 200))
    if len(text) < min_chars:
        raise FetchError(
            f"正文过短（{len(text)} < {min_chars} 字符）：{locator}",
            hint="升级 fallback 后端或保持标题级条目",
        )
    return text, title
