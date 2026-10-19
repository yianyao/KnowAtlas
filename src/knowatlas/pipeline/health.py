"""链接体检（0.2.0 第七批，用户需求"不可达的链接还要来干嘛"）。

对 active 的 http(s) 条目做可达性检测，结果写条目 meta：
- link_status: ok（2xx/3xx）/ dead（404/410，永久消失）/ error（超时、403、5xx 等，可能临时）
- link_code: HTTP 状态码或 0（网络异常）
- link_checked_at: 检查时间

纪律：
- 可达性是**波动属性**，放 meta 不放 status 列（status 归用户/源决定：active/archived/rejected）；
- 不自动舍弃——dead 只标记，批量舍弃由用户在 UI「失效链接」视图确认（防误杀）；
- GET + stream（读完头即断），比 HEAD 兼容性好；
- 限流：条目间 sleep 间隔（rate_limit_qps），默认全量限量防失控。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from ..models import Entry

_INLINE_LIMIT = 0


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def check_link(url: str, timeout: float = 10.0) -> tuple[str, int]:
    """单条链接检测。返回 (link_status, code)。网络异常返回 ("error", 0)。

    分级（2026-10-19 真实体检校准）：
    - ok: 2xx/3xx
    - dead: 404/410——服务器明确说内容没了，高置信死链
    - blocked: 401/403/412/429——反爬拦截，**链接对人有效**（浏览器可达），不算失效
    - error: 其余（5xx、超时、DNS/网络失败）——可能临时
    """
    import httpx

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                code = resp.status_code
                if code < 400:
                    return "ok", code
                if code in (404, 410):
                    return "dead", code
                if code in (401, 403, 412, 429):
                    return "blocked", code
                return "error", code
    except Exception:
        return "error", 0


def run_health_check(cfg: Any, dl: Any, *, limit: int = 100,
                     qps: float = 4.0) -> dict[str, Any]:
    """体检入口：逐条检测、merge_meta 写结果。返回统计。"""
    entries = [e for e in dl.list_entries(status="active", limit=10000)
               if e.locator_canonical is not None]  # 仅 http(s)
    entries = entries[:limit]
    counts = {"ok": 0, "dead": 0, "blocked": 0, "error": 0}
    checked_at = _now_iso()
    for i, e in enumerate(entries):
        status, code = check_link(e.locator)
        counts[status] += 1
        dl.merge_meta(e.id, {"link_status": status, "link_code": code,
                             "link_checked_at": checked_at})
        if i < len(entries) - 1:
            time.sleep(1.0 / qps)
    dl.log_task(_now_iso(), "kcheck", "health_check", "batch",
                {"checked": len(entries), **counts})
    return {"checked": len(entries), **counts}
