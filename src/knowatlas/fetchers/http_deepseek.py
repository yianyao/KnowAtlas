"""DeepSeek Fetch 升级抓取后端（完整方案 §9.3 步骤 13；0.2.0 第二十四批接入）。

DeepSeek Fetch API（2026-10-17 上线，https://api-docs.deepseek.com/zh-cn/api/fetch/）：
POST {base}/v1/tools/fetch，Bearer 鉴权，返回 {title, content(markdown)}。
计费：5 元/千次成功请求（失败/超时/空结果不计费）；账号级 5 QPS + 域级限速。

纪律：
- 只作升级后端：fetch_with_fallback 在 simple 失败（HTTP ≥400 / 正文过短 / 提取失败）时
  才路由到这里，同步默认不触发（K1）；
- 429 指数退避（0.8s 起步翻倍，fetch.max_retries 次）；其余非 200 直接抛（失败不计费，
  重试同请求无益的 4xx 更不该烧钱）；
- key 走环境变量（铁律：key 本体不入配置/日志），默认复用 KNOWATLAS_LLM_API_KEY；
- 请求前客户端预检 URL（≤8192 字符、http/https）——不符合规范的请求不发出，不花冤枉钱。
"""

from __future__ import annotations

import os
import time

from ..errors import FetchError
from ..registry.capability import FetchContext

_MAX_URL_LEN = 8192  # Fetch API 请求字段上限（官方规范）


def fetch_page(locator: str, ctx: FetchContext) -> tuple[str, str]:
    """经 DeepSeek Fetch API 抓取，返回 (markdown 正文, 标题)。

    key 从 fetch.deepseek_api_key_env 指向的环境变量读取（默认 KNOWATLAS_LLM_API_KEY，
    与 LLM 后端共用同一把 DeepSeek key）；429 按 fetch.max_retries 指数退避。
    """
    base = str(ctx.config.get("fetch.deepseek_base_url",
                              "https://api.deepseek.com")).rstrip("/")
    key_env = str(ctx.config.get("fetch.deepseek_api_key_env",
                                 "KNOWATLAS_LLM_API_KEY"))
    key = os.environ.get(key_env, "").strip()
    if not key:
        raise FetchError(
            f"DeepSeek Fetch 未配置：环境变量 {key_env} 为空",
            hint=f"setx {key_env} <DeepSeek API Key>（设完重开终端）；不需要升级后端时"
                 f"把 fetch.fallback_backend 置空即可关闭本路径")
    # 客户端预检：不合规的 URL 不发请求（Fetch API 必拒绝，预检省一次失败调用）
    if not locator.lower().startswith(("http://", "https://")):
        raise FetchError(f"Fetch API 仅支持 http/https URL：{locator[:120]}")
    if len(locator) > _MAX_URL_LEN:
        raise FetchError(
            f"URL 超过 Fetch API 上限 {_MAX_URL_LEN} 字符（实际 {len(locator)}）：{locator[:120]}")

    retries = int(ctx.config.get("fetch.max_retries", 3) or 3)
    timeout = float(ctx.config.get("fetch.timeout_seconds", 20))
    delay = 0.8  # 首次退避 0.8s，指数翻倍（账号 5 QPS + 域级限速，退避到通过为止）
    for attempt in range(retries + 1):
        try:
            resp = ctx.http.post(
                f"{base}/v1/tools/fetch",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"url": locator},
                timeout=timeout,
            )
        except Exception as exc:  # 传输层异常（DeepSeek 侧连不上）
            raise FetchError(f"DeepSeek Fetch 请求失败：{exc}",
                             hint="检查网络与 fetch.deepseek_base_url") from exc
        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError as exc:
                raise FetchError(f"DeepSeek Fetch 响应非 JSON：{resp.text[:200]}") from exc
            content = str(data.get("content") or "").strip()
            title = str(data.get("title") or "").strip()
            if not content:
                raise FetchError(
                    f"DeepSeek Fetch 返回空正文：{locator[:120]}",
                    hint="目标站点反爬或无正文——保持标题级条目（此响应按规范不计费）")
            return content, title
        if resp.status_code == 429 and attempt < retries:
            time.sleep(delay)
            delay *= 2
            continue
        raise FetchError(
            f"DeepSeek Fetch HTTP {resp.status_code}：{resp.text[:200]}",
            hint="429=账号 5 QPS 或域级限速（已退避重试仍失败）；"
                 "其余状态码重试同请求无益。仅成功请求计费（5 元/千次）")
    raise FetchError(f"DeepSeek Fetch 重试 {retries} 次仍 429：{locator[:120]}")  # 兜底，理论不可达
