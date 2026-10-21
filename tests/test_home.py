"""KNOWATLAS_HOME 数据根策略（0.2.0 第五十三批）。

语义：home 未设 = 相对路径挂 cwd（仓库内现状）；home 已设 = 相对路径挂
home；绝对路径永远原样。测试用例经 conftest 隔离（宿主机该变量被清），
这里用 monkeypatch.setenv 显式构造。
"""

from __future__ import annotations

from pathlib import Path

from knowatlas.config import Config


def _cfg(tmp_path: Path, **general) -> Config:
    data = {"general": {"db_path": "data/knowledge.db",
                        "backup_dir": "data/backups", **general}}
    return Config(data, tmp_path / "knowatlas.toml")


def test_home_unset_keeps_cwd_relative(tmp_path, monkeypatch):
    monkeypatch.delenv("KNOWATLAS_HOME", raising=False)
    cfg = _cfg(tmp_path)
    assert cfg.home is None
    # 未设 = 现状：相对路径按 cwd 解析（Config 不做绝对化，Path 保持相对）
    assert not cfg.db_path.is_absolute()


def test_home_set_mounts_relative_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWATLAS_HOME", str(tmp_path / "home"))
    cfg = _cfg(tmp_path)
    assert cfg.home == tmp_path / "home"
    assert cfg.db_path == tmp_path / "home" / "data" / "knowledge.db"
    assert cfg.backup_dir == tmp_path / "home" / "data" / "backups"


def test_absolute_paths_untouched(tmp_path, monkeypatch):
    """绝对路径配置不受 home 影响（换机时用户显式指定的路径优先）。"""
    monkeypatch.setenv("KNOWATLAS_HOME", str(tmp_path / "home"))
    abs_db = tmp_path / "elsewhere" / "x.db"
    cfg = _cfg(tmp_path, db_path=str(abs_db))
    assert cfg.db_path == abs_db


def test_home_blank_and_whitespace(tmp_path, monkeypatch):
    """空串/纯空白 = 未设（不产生 ` / relative` 的怪路径）。"""
    monkeypatch.setenv("KNOWATLAS_HOME", "   ")
    cfg = _cfg(tmp_path)
    assert cfg.home is None
