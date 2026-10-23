"""simple 网页抓取后端：httpx + readability-lxml（零成本，默认）。

批次 92（裁决 12「抓来的必须是知识」）：
- raw.githubusercontent.com 直链直接返回纯文本（readability 对纯 markdown 是
  破坏性的——会包 <pre> 撕代码块；raw 内容本身就是知识本体，零加工直取）；
- readability 提取结果过骨架检测（导航/版权行占比过高 → 视为提取失败，
  触发升级路由到 DeepSeek Fetch 重抓——防「抓回一页按钮墙当正文」入库）。
"""

from __future__ import annotations

from urllib.parse import unquote

from ..errors import DegradedParseError, FetchError
from ..registry.capability import FetchContext
from .base import is_skeleton_body

_USER_AGENT = "KnowAtlas/0.1 (+personal knowledge indexer)"


def _raw_title(locator: str) -> str:
    """raw 直链无页面标题：取 URL 末段文件名去后缀（display_name 可后补）。"""
    seg = locator.split("://", 1)[-1].split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    return unquote(seg).rsplit(".", 1)[0][:120]


def fetch_page(locator: str, ctx: FetchContext) -> tuple[str, str]:
    """抓取并提取正文，返回 (text, title)。

    失败 = 抛 FetchError（网络/HTTP 错误/骨架/正文过短）或 DegradedParseError
    （提取失败）；两者都触发 base 的升级路由（fallback_backend）。
    """
    is_raw = "raw.githubusercontent.com" in locator
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
    min_chars = int(ctx.config.get("fetch.min_content_chars", 200))
    if is_raw:
        # 纯文本直取：markdown/代码是知识本体，readability 只会破坏它
        text = resp.text.strip()
        if len(text) < min_chars:
            raise FetchError(f"raw 正文过短（{len(text)} < {min_chars} 字符）：{locator}",
                             hint="升级 fallback 后端或保持标题级条目")
        return text, _raw_title(locator)
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

    if is_skeleton_body(text):
        raise FetchError(
            f"提取结果疑似页面骨架（导航/版权行占比过高，{len(text)} 字符）：{locator}",
            hint="升级 fallback 后端（DeepSeek Fetch）重新提取正文")
    if len(text) < min_chars:
        raise FetchError(
            f"正文过短（{len(text)} < {min_chars} 字符）：{locator}",
            hint="升级 fallback 后端或保持标题级条目",
        )
    return text, title
