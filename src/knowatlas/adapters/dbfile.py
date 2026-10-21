"""数据文件适配器（0.2.0 第五十七批，完整方案 §3.2/TODO Phase 3，零凭证）。

SQLite（stdlib）与 PostgreSQL（psycopg，optional）统一「schema 自省 + 采样」：
每张用户表一条目——列清单、行数、前 5 行采样进 inline_content（探针：
表清单与采样行正确进入条目）。视图与系统表（sqlite_%/pg_%/information_schema）
排除。只读打开：SQLite 用 mode=ro URI（缺文件 fail loud，绝不静默建空库——
dbmeta.py 教训）。

source_key = "<文件名或连接串名>::<表名>"（契约：文件相对路径或连接串名 + 表名；
文件名作相对标识避免机器绝对路径入库，完整路径进 meta.source_path 供溯源）。
locator = db://<标识>?table=<表名>（quote 转义）。

采样是压缩表示：表数据本体永在原库，本工具只读不自改。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..errors import AdapterError
from ..models import Entry
from .base import AdapterOutput

_SAMPLE_ROWS = 5
_INLINE_CAP = 4000
_SYSTEM_TABLE_PREFIXES_SQLITE = ("sqlite_",)
_SYSTEM_TABLE_PREFIXES_PG = ("pg_", "sql_")


def _cell(v: Any) -> Any:
    """采样值 JSON 安全化（bytes repr 截断、其余原样）。"""
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    if isinstance(v, str) and len(v) > 120:
        return v[:120] + "…"
    return v


def _entry_for_table(kind: str, ident: str, display: str, table: str,
                     columns: list[str], row_count: int | None,
                     sample: list[dict[str, Any]],
                     native_path: str) -> Entry:
    lines = [f"{display} · 表 {table}："
             f"{'?' if row_count is None else f'{row_count} 行'}，{len(columns)} 列"
             f"（{', '.join(columns)}）"]
    if sample:
        lines.append("")
        lines.append("采样（前 %d 行）：" % len(sample))
        for row in sample:
            lines.append(json.dumps({k: _cell(v) for k, v in row.items()},
                                    ensure_ascii=False, default=str))
    inline = "\n".join(lines)[:_INLINE_CAP]
    return Entry.build(
        source_type="db", source_key=f"{ident}::{table}",
        title=f"{display}·{table}",
        locator=f"db://{quote(ident, safe='')}?table={quote(table, safe='')}",
        locator_canonical=None,
        native_path=native_path,
        inline_content=inline,
        meta={"source_type": "db", "db_kind": kind, "table": table,
              "columns": columns, "row_count": row_count},
    )


def _collect_sqlite(path: Path, stats: dict[str, Any]) -> list[Entry]:
    if not path.is_file():
        raise AdapterError(
            f"sources.db：SQLite 文件不存在：{str(path)!r}",
            hint="检查 config/knowatlas.toml 的 [sources.db] sqlite_paths")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name")]
        stats["sqlite_tables"] = stats.get("sqlite_tables", 0) + len(names)
        out: list[Entry] = []
        for t in names:
            try:
                cols = [r["name"] for r in con.execute(f'PRAGMA table_info("{t}")')]
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                rows = [dict(r) for r in con.execute(
                    f'SELECT * FROM "{t}" LIMIT {_SAMPLE_ROWS}')]
            except sqlite3.Error:
                stats["skipped_tables"] = stats.get("skipped_tables", 0) + 1
                continue
            out.append(_entry_for_table(
                "sqlite", path.name, path.stem, t, cols, n, rows,
                native_path=path.name))
        return out
    finally:
        con.close()


def _collect_postgres(name: str, dsn: str, stats: dict[str, Any]) -> list[Entry]:
    try:
        import psycopg  # optional 依赖（requirements-optional）
    except ImportError as exc:
        raise AdapterError(
            f"sources.db：PostgreSQL 源 {name} 需要 psycopg（未安装）",
            hint="pip install -r requirements-optional.txt（含 psycopg[binary]）；"
                 "不需要 PostgreSQL 时从 sqlite_paths/postgres_dsn 移除该连接串") from exc
    try:
        with psycopg.connect(dsn) as con:  # type: ignore[attr-defined]
            with con.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' ORDER BY table_name")
                names = [r[0] for r in cur.fetchall()]
                stats["pg_tables"] = stats.get("pg_tables", 0) + len(names)
                out: list[Entry] = []
                for t in names:
                    if str(t).startswith(_SYSTEM_TABLE_PREFIXES_PG):
                        continue
                    cur.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name=%s "
                        "ORDER BY ordinal_position", (t,))
                    cols = [r[0] for r in cur.fetchall()]
                    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                    n = cur.fetchone()[0]
                    cur.execute(f'SELECT * FROM "{t}" LIMIT {_SAMPLE_ROWS}')
                    pg_cols = [d[0] for d in cur.description] if cur.description else []
                    rows = [dict(zip(pg_cols, r)) for r in cur.fetchall()]
                    out.append(_entry_for_table(
                        "postgres", name, name, str(t), cols, n, rows,
                        native_path=name))
                return out
    except AdapterError:
        raise
    except Exception as exc:
        raise AdapterError(
            f"sources.db：PostgreSQL 连接失败（{name}）：{type(exc).__name__}: {exc}",
            hint="检查 postgres_dsn 连接串（主机/端口/库名/凭证）；"
                 "凭证过期请更新 config/knowatlas.toml 后重跑") from exc


def collect_dbs(cfg: Any) -> AdapterOutput:
    """[sources.db] 配置：{sqlite_paths: [文件, ...], postgres_dsn: str|{名: dsn}}。"""
    sec = cfg.get("sources.db") or {}
    if not sec.get("enabled"):
        return AdapterOutput([], {"skipped_disabled": 1})
    sqlite_paths = [Path(str(p)) for p in (sec.get("sqlite_paths") or [])
                    if str(p).strip()]
    pg = sec.get("postgres_dsn")
    pg_dsns: dict[str, str] = {}
    if isinstance(pg, dict):
        pg_dsns = {str(k): str(v) for k, v in pg.items() if str(v).strip()}
    elif isinstance(pg, str) and pg.strip():
        pg_dsns = {"postgres": pg.strip()}
    if not sqlite_paths and not pg_dsns:
        raise AdapterError(
            "sources.db 未配置任何数据文件",
            hint="在 config/knowatlas.toml 配置 [sources.db] sqlite_paths = "
                 "[\"…db 文件\"] 和/或 postgres_dsn = \"连接串\"")

    stats: dict[str, Any] = {}
    entries: list[Entry] = []
    for p in sqlite_paths:
        entries.extend(_collect_sqlite(p, stats))
    for name, dsn in pg_dsns.items():
        entries.extend(_collect_postgres(name, dsn, stats))
    return AdapterOutput(entries, stats)
