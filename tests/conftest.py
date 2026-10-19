"""pytest fixtures：临时库 + 配置 + 注册表（内存/临时目录，端到端不碰真实数据）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 本地 fixture 测试绝不走系统代理（httpx trust_env 会读 http_proxy，
# 代理对 127.0.0.1 的转发行为不稳定 → kadd 端到端偶发假挂，2026-10-19）
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knowatlas.config import Config  # noqa: E402
from knowatlas.datalayer.db import DataLayer  # noqa: E402
from knowatlas.registry.builtins import build_registries  # noqa: E402


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    data = {
        "general": {"db_path": str(tmp_path / "test.db"), "log_level": "WARNING"},
        "web": {"token_env": "KNOWATLAS_TEST_TOKEN"},
        "fetch": {
            "default_backend": "simple", "fallback_backend": "",
            "timeout_seconds": 5, "min_content_chars": 20,
            "on_sync": False, "max_fetch_per_run": 10,
        },
        "sources": {"manual": {"enabled": True}},
    }
    return Config(data, tmp_path / "knowatlas.toml")


@pytest.fixture
def dl(cfg: Config):
    layer = DataLayer(cfg.db_path)
    layer.init_schema()
    yield layer
    layer.close()


@pytest.fixture
def registries(cfg: Config):
    return build_registries(cfg)
