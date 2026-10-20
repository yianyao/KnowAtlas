"""DDL 常量、user_version 与 canary 摘要（完整方案 §3.4 / §11.2）。

DDL 事实源 = migrations/ 目录下按文件名序排列的 `NNN_*.sql`（001_init、002_threads…）。
本文件只负责发现、加载与摘要，不重复 DDL 文本（防两处漂移）。
迁移纪律：只进不前——已落库的迁移文件禁止修改， schema 变更一律新增 003_*.sql。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")
USER_VERSION = 1
INITIAL_MIGRATION = "001_init.sql"


def migration_versions() -> list[int]:
    """已发现的迁移版本号（按文件名序，如 [1, 2]）。"""
    versions = []
    for p in MIGRATIONS_DIR.iterdir():
        m = _MIGRATION_RE.match(p.name)
        if m:
            versions.append(int(m.group(1)))
    return sorted(versions)


def latest_version() -> int:
    """代码支持的最新 schema 版本（无迁移文件时回退 USER_VERSION）。"""
    versions = migration_versions()
    return versions[-1] if versions else USER_VERSION


def load_migration(version: int) -> str:
    path = MIGRATIONS_DIR / f"{version:03d}_*.sql"
    matches = sorted(MIGRATIONS_DIR.glob(path.name))
    if not matches:
        raise FileNotFoundError(f"迁移文件不存在：{path}")
    return matches[0].read_text(encoding="utf-8")


def load_initial_schema() -> str:
    return (MIGRATIONS_DIR / INITIAL_MIGRATION).read_text(encoding="utf-8")


def load_all_migrations() -> str:
    """全部迁移文本按序拼接——test_canary 的 DDL 摘要源（新表即契约面，必须纳管）。"""
    return "\n".join(load_migration(v) for v in migration_versions())


def digest(text: str) -> str:
    """canary 稳定摘要：sha1 前 12 位。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
