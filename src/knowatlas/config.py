"""配置加载：TOML + KNOWATLAS_* 环境变量覆盖 + 启动校验（完整方案 §6）。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .errors import ConfigError

# 顶层节（环境变量覆盖识别用）
_TOP_SECTIONS = ("general", "web", "llm", "embedding", "fetch", "clean",
                 "ingest", "points", "aging")

# config schema 键集（canary 覆盖项：改动必须先写工单）
CONFIG_SCHEMA_KEYS = (
    "general.backup_dir", "general.backup_keep", "general.backup_min_interval_hours",
    "general.backup_on_sync", "general.content_root", "general.db_path",
    "general.log_level", "general.server_host", "general.server_port",
    "web.allow_lan_writes", "web.token_env",
    "llm.api_key_env", "llm.backends", "llm.base_url", "llm.enabled", "llm.max_batch",
    "llm.model", "llm.temperature",
    "embedding.enabled", "embedding.model_path", "embedding.provider",
    "fetch.default_backend", "fetch.deepseek_api_key_env", "fetch.deepseek_base_url",
    "fetch.fallback_backend", "fetch.max_fetch_per_run",
    "fetch.max_retries", "fetch.min_content_chars", "fetch.on_sync",
    "fetch.pdf_backend",
    "fetch.rate_limit_qps", "fetch.timeout_seconds",
    "clean.enabled", "clean.min_keep_ratio", "clean.redact_enabled",
    "aging.auto", "aging.exclude_categories", "aging.interval_hours",
    "aging.limit_per_run",
    "ingest.allow_kpe", "ingest.enabled", "ingest.interval_seconds",
    "ingest.kpe_max_chars", "ingest.max_entries_per_run", "ingest.max_retries",
    "points.chunk_chars", "points.chunk_total_max", "points.max_per_chunk",
    "sources.bilibili", "sources.bookmarks", "sources.db", "sources.emmx",
    "sources.folders", "sources.ima", "sources.mail", "sources.manual",
    "sources.opml", "sources.session", "sources.txdoc", "sources.wx",
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
    def home(self) -> Path | None:
        """数据根（0.2.0 第五十三批）：KNOWATLAS_HOME 环境变量，未设为 None。

        语义：home 未设 = 现状（相对 cwd，仓库内使用）；home 已设 = 相对
        路径全部挂到 home 下（换机/装 wheel 后 cwd 不定，数据位置由环境
        变量锚定，代码与数据彻底分离）。绝对路径配置永远原样，不受影响。
        """
        v = os.environ.get("KNOWATLAS_HOME", "").strip()
        return Path(v) if v else None

    def _resolve(self, raw: str, default: str) -> Path:
        """数据路径解析：绝对路径原样；相对路径 home 已设则挂 home，未设挂 cwd。"""
        p = Path(str(self.get(raw, default)))
        if p.is_absolute():
            return p
        home = self.home
        return home / p if home else p

    @property
    def db_path(self) -> Path:
        return self._resolve("general.db_path", "data/knowledge.db")

    @property
    def backup_dir(self) -> Path:
        return self._resolve("general.backup_dir", "data/backups")

    @property
    def backup_on_sync(self) -> bool:
        """同步前是否自动快照（第四十六批；false=显式关闭，没快照也不同步的契约由用户承担）。"""
        return bool(self.get("general.backup_on_sync", True))

    @property
    def backup_keep(self) -> int:
        return int(self.get("general.backup_keep", 10))

    @property
    def backup_min_interval_hours(self) -> int:
        """快照节流：距上次快照不足该小时数则跳过（VACUUM INTO 全库重建成本高）。"""
        return int(self.get("general.backup_min_interval_hours", 24))

    @property
    def log_level(self) -> str:
        return str(self.get("general.log_level", "INFO"))

    @property
    def sources(self) -> dict:
        v = self._data.get("sources")
        return dict(v) if isinstance(v, dict) else {}

    # ---- 入库即抽点（工单 2026-10-27-入库即抽点与自动老化 §2.1）----

    @property
    def ingest_enabled(self) -> bool:
        """serve 内置 worker 开关（kauto 不受此限：显式命令总是执行）。"""
        return bool(self.get("ingest.enabled", False))

    @property
    def ingest_interval_seconds(self) -> int:
        return max(30, int(self.get("ingest.interval_seconds", 600)))

    @property
    def ingest_max_entries_per_run(self) -> int:
        """每轮总条数上限（费用护栏）；0 = 不限（不建议）。"""
        return max(0, int(self.get("ingest.max_entries_per_run", 10)))

    @property
    def ingest_max_retries(self) -> int:
        """单条目失败重试上限；超限进 meta.ingest.dead，不再自动烧钱。"""
        return max(0, int(self.get("ingest.max_retries", 2)))

    @property
    def ingest_allow_kpe(self) -> bool:
        return bool(self.get("ingest.allow_kpe", True))

    @property
    def ingest_kpe_max_chars(self) -> int:
        """单卷上限（工单 2026-10-29《超大书分卷摄取》C1）。

        按 **chunks 实际字符数** 判定：超过就按章装箱成 `v001..` 多卷、逐卷抽取、断点续跑
        （旧口径「正文字数超了硬报错」已废弃——正文 2.59M 的书 PDF 通道可能只有 776k）。
        """
        return max(10000, int(self.get("ingest.kpe_max_chars", 600000)))

    # ---- 抽点阈值（KPE 与管道同源，工单 §2.1）----

    @property
    def points_max_per_chunk(self) -> int:
        """单块/单条最多几个点：KPE --max-points；管道 split 上限。"""
        return max(1, int(self.get("points.max_per_chunk", 6)))

    @property
    def points_chunk_chars(self) -> int:
        return max(1000, int(self.get("points.chunk_chars", 6000)))

    @property
    def points_chunk_total_max(self) -> int:
        """管道内分块上限；超过的条目改走 KPE（书/超长文档）。"""
        return max(6000, int(self.get("points.chunk_total_max", 60000)))

    # ---- 老化（工单 §2.1）----

    @property
    def aging_auto(self) -> bool:
        return bool(self.get("aging.auto", True))

    @property
    def aging_interval_hours(self) -> int:
        return max(1, int(self.get("aging.interval_hours", 24)))

    @property
    def aging_limit_per_run(self) -> int:
        return max(1, int(self.get("aging.limit_per_run", 200)))

    @property
    def aging_exclude_categories(self) -> tuple[str, ...]:
        """域闸门黑名单：一级分类名（含子树）命中即不自动老化（社科/人文类）。"""
        v = self.get("aging.exclude_categories",
                     ["文学创作", "哲学", "历史", "文学", "艺术", "社会学",
                      "心理学", "经济学", "政治学", "法律", "教育", "宗教",
                      "人类学", "语言学", "传播学"])
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",") if x.strip()]
        return tuple(str(x).strip() for x in (v or []) if str(x).strip())


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
