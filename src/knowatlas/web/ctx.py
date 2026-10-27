"""web 层共享上下文：AppCtx + 时间助手。

为什么有它：拆分前 73 个 handler 共享 register_routes 的闭包变量（cfg/dl/locators/semantics）；
拆到 routers/ 后用显式上下文传递，函数体一字不改。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class AppCtx:
    """一次进程内稳定的依赖集（由 app 工厂构造一次，所有 router 共用）。"""

    cfg: Any
    dl: Any
    locators: Any
    semantics: Any


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
