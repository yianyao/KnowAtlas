"""数据文件源测试（0.2.0 第五十七批，TODO Phase 3 探针）。

SQLite 全链路（stdlib）；PostgreSQL 本机无服务端——覆盖 psycopg 缺失报错
指引与 DSN 路径分支，真机探针挂账（docker 起 PG 后补跑）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from knowatlas.adapters.dbfile import collect_dbs
from knowatlas.errors import AdapterError
from knowatlas.pipeline.sync import run_sync


def _make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT, budget REAL);"
        "INSERT INTO projects VALUES (1,'PECOS',1.2),(2,'Atlas',3.5);"
        "CREATE TABLE tags (name TEXT);"
        "INSERT INTO tags VALUES ('知识库'),('检索');"
        "CREATE VIEW v_summary AS SELECT name FROM projects;")
    con.commit()
    con.close()


def _cfg(sqlite_paths=None, pg=None, enabled=True):
    class Cfg:
        def get(self, key):
            assert key == "sources.db"
            sec: dict = {"enabled": enabled}
            if sqlite_paths is not None:
                sec["sqlite_paths"] = sqlite_paths
            if pg is not None:
                sec["postgres_dsn"] = pg
            return sec
    return Cfg()


# ---- collect_dbs：SQLite ----

def test_collect_sqlite_tables_and_sample(tmp_path):
    db = tmp_path / "assets.db"
    _make_db(db)
    out = collect_dbs(_cfg(sqlite_paths=[str(db)]))
    tables = {e.meta["table"]: e for e in out.entries}
    # 用户表入条目；视图与 sqlite_% 系统表排除
    assert set(tables) == {"projects", "tags"}
    p = tables["projects"]
    assert p.locator == "db://assets.db?table=projects"
    assert p.title == "assets·projects"
    assert p.native_path == "assets.db"
    assert p.meta["db_kind"] == "sqlite" and p.meta["row_count"] == 2
    assert p.meta["columns"] == ["id", "name", "budget"]
    # 探针：采样行正确进入条目
    assert "采样（前 2 行）" in p.inline_content
    assert "PECOS" in p.inline_content and "1.2" in p.inline_content


def test_collect_sqlite_missing_file_fails_loud(tmp_path):
    with pytest.raises(AdapterError) as ei:
        collect_dbs(_cfg(sqlite_paths=[str(tmp_path / "ghost.db")]))
    assert "sources.db" in str(ei.value)


def test_collect_dbs_nothing_configured(tmp_path):
    with pytest.raises(AdapterError):
        collect_dbs(_cfg())
    out = collect_dbs(_cfg(enabled=False))
    assert out.stats == {"skipped_disabled": 1}


# ---- collect_dbs：PostgreSQL 分支 ----

def test_collect_postgres_psycopg_missing_hint(tmp_path, monkeypatch):
    """psycopg 未安装 → 报错含安装指引（本机无 optional 依赖时真实走到）。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "psycopg":
            raise ImportError("No module named 'psycopg'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(AdapterError) as ei:
        collect_dbs(_cfg(pg={"repo": "postgresql://u:p@localhost/repo"}))
    assert "requirements-optional" in ei.value.hint


def test_collect_postgres_bad_dsn_reports_config():
    """psycopg 已装但连接失败 → 报错指向连接串配置（无服务端必然走到）。"""
    pytest.importorskip("psycopg")
    with pytest.raises(AdapterError) as ei:
        collect_dbs(_cfg(pg="postgresql://u:p@127.0.0.1:1/ghost"))
    assert "postgres_dsn" in ei.value.hint or "连接失败" in str(ei.value)


# ---- 端到端：ksync dbs 源 ----

def test_sync_dbs_end_to_end(cfg, dl, registries, tmp_path):
    db = tmp_path / "assets.db"
    _make_db(db)
    cfg._data["sources"]["db"] = {"enabled": True, "sqlite_paths": [str(db)]}
    locators, semantics = registries

    stats = run_sync(cfg, dl, locators, semantics, full=True)
    src = stats["sources"]["dbs"]
    assert src["entries"] == 2 and src["created"] == 2
    by_title = {e.title: e for e in dl.list_entries(status="active", limit=10)}
    assert "assets·projects" in by_title
    assert "PECOS" in by_title["assets·projects"].inline_content
    # 二跑幂等（源未变 → unchanged）
    stats2 = run_sync(cfg, dl, locators, semantics, full=True)
    assert stats2["sources"]["dbs"]["created"] == 0
    assert stats2["sources"]["dbs"]["unchanged"] == 2
