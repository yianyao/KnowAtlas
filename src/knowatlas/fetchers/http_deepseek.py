"""DeepSeek Fetch API 后端（可靠抓取兜底）—— TODO Phase 2（M2）接入。

接口规格（2026-10-19 已核实）：POST https://api.deepseek.com/v1/tools/fetch，
Bearer 鉴权与 DeepSeek API key 通用；成功返回正文 Markdown；5 元/千次成功请求，
仅 HTTP 200 且有内容才计费；账号级 5 QPS、另有域名级限制，超限 429 → 指数退避 max_retries 次。
接入时实现 fetch_page(locator, ctx) -> (text, title)，签名与 http_simple 一致。
"""

from __future__ import annotations

from ..errors import FetchError
from .capability import FetchContext


def fetch_page(locator: str, ctx: FetchContext) -> tuple[str, str]:
    raise FetchError(
        "DeepSeek Fetch 后端尚未接入（TODO Phase 2 / M2 步骤 13）",
        hint="当前保持标题级条目即可；接入后此路由自动生效（fetch.fallback_backend=deepseek）",
    )
