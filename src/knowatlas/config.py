"""配置加载：TOML + KNOWATLAS_* 环境变量覆盖 + 启动校验（完整方案 §6）。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .errors import ConfigError

# 顶层节（环境变量覆盖识别用）
_TOP_SECTIONS = ("general", "web", "llm", "embedding", "fetch")

# config schema 键集（canary 覆盖项：改动必须先写工单）
CONFIG_SCHEMA_KEYS = (
    "general.backup_dir", "general.content_root", "general.db_path",
    "general.log_level", "general.server_host", "general.server_port",
    "web.token_env",
    "llm.api_key_env", "llm.backends", "llm.base_url", "llm.enabled", "llm.max_batch",
    "llm.model", "llm.temperature",
    "embedding.enabled", "embedding.model_path", "embedding.provider",
    "fetch.default_backend", "fetch.deepseek_api_key_env", "fetch.deepseek_base_url",
    "fetch.fallback_backend", "fetch.max_fetch_per_run",
    "fetch.max_retries", "fetch.min_content_chars", "fetch.on_sync",
    "fetch.rate_limit_qps", "fetch.timeout_seconds",
    "sources.bilibili", "sources.bookmarks", "sources.db", "sources.emmx",
    "sources.folders", "sources.ima", "sources.mail", "sources.manual",
    "sources.session", "sources.txdoc", "sources.wx",
)


class Config:
    """轻量配置访问器。raw 字典保底；快捷属性覆盖高频键。"""

    def __init__(self, data: dict, path: Path) -> None:
        self._data = data
        self.path = path

    @property
    def raw(self) -> dict:
        return self._data

    def get(self, dotted: str, default=None):
        cur: object = self._data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def section(self, name: str) -> dict:
        v = self._data.get(name)
        return dict(v) if isinstance(v, dict) else {}

    @property
    def db_path(self) -> Path:
        return Path(str(self.get("general.db_path", "data/knowledge.db")))

    @property
    def backup_dir(self) -> Path:
        return Path(str(self.get("general.backup_dir", "data/backups")))

    @property
    def log_level(self) -> str:
        return str(self.get("general.log_level", "INFO"))

    @property
    def sources(self) -> dict:
        v = self._data.get("sources")
        return dict(v) if isinstance(v, dict) else {}


def _apply_env_overrides(data: dict) -> None:
    """KNOWATLAS_<SECTION>_<KEY> 全覆盖（只支持标量，§6 加载规则第 2 条）。"""
    for env_key, raw in os.environ.items():
        if not env_key.startswith("KNOWATLAS_"):
            continue
        tokens = env_key[len("KNOWATLAS_"):].lower().split("_")
        if tokens[0] == "sources" and len(tokens) >= 3:
            section, key = f"sources.{tokens[1]}", "_".join(tokens[2:])
        elif tokens[0] in _TOP_SECTIONS and len(tokens) >= 2:
            section, key = tokens[0], "_".join(tokens[1:])
        else:
            continue
        node = data.get(section)
        if isinstance(node, dict) and key in node and isinstance(node[key], (str, int, float, bool)):
            node[key] = raw


def _validate_enabled_sources(data: dict) -> None:
    """§6 加载规则第 4 条：enabled=true 的源必须有非空路径/凭证。"""
    sources = data.get("sources", {})
    requirements = {
        "bookmarks": lambda s: any(bool(v) for v in (s.get("paths") or {}).values()),
        "folders": lambda s: bool(s.get("roots")),
        "emmx": lambda s: bool(s.get("roots")),
        "mail": lambda s: any(bool((s.get("accounts") or {}).get(a, {}).get("path") if isinstance(a_sec, dict) else a_sec)
                              for a, a_sec in (s.get("accounts") or {}).items()),
        "db": lambda s: bool(s.get("sqlite_paths") or s.get("postgres_dsn")),
        "session": lambda s: bool(s.get("harvester_dirs")),
        "bilibili": lambda s: bool(s.get("up_mid")) and bool(s.get("sessdata_env")),
        "wx": lambda s: any(bool(s.get(k)) for k in ("fav_export_dir", "chat_export_dir", "article_export_dir")),
    }
    for name, ok in requirements.items():
        sec = sources.get(name)
        if isinstance(sec, dict) and sec.get("enabled") and not ok(sec):
            raise ConfigError(
                f"sources.{name} enabled=true 但路径/凭证为空",
                hint=f"在 config/knowatlas.toml 填写 [sources.{name}] 必填项，或改 enabled = false",
            )
    manual = sources.get("manual")
    if manual is not None and not isinstance(manual, dict):
        raise ConfigError("[sources.manual] 必须是表", hint="对照 config/knowatlas.example.toml")


def load_config(config_path: str | Path | None = None) -> Config:
    """默认读 config/knowatlas.toml（相对 cwd）；不存在则报错退出，不静默用默认值。"""
    if config_path is None:
        config_path = os.environ.get("KNOWATLAS_CONFIG", "config/knowatlas.toml")
    path = Path(config_path)
    if not path.is_file():
        raise ConfigError(
            f"配置文件不存在：{path}",
            hint="复制 config/knowatlas.example.toml 为 config/knowatlas.toml 并按本机填写",
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件解析失败：{exc}", hint=str(path)) from exc
    _apply_env_overrides(data)
    _validate_enabled_sources(data)
    return Config(data, path)
