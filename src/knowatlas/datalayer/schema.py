"""DDL 常量、user_version 与 canary 摘要（完整方案 §3.4 / §11.2）。

唯一 DDL 事实源 = migrations/001_init.sql；本文件只负责加载与摘要，不重复 DDL 文本（防两处漂移）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
USER_VERSION = 1
INITIAL_MIGRATION = "001_init.sql"


def load_initial_schema() -> str:
    return (MIGRATIONS_DIR / INITIAL_MIGRATION).read_text(encoding="utf-8")


def digest(text: str) -> str:
    """canary 稳定摘要：sha1 前 12 位。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
