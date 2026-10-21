"""自动备份与恢复测试（0.2.0 第四十六批，M5 Gate 后半）。

探针（CHANGELOG 第四十六批）：
① WAL 开启下从快照恢复（删 -wal/-shm）后条目数与快照时一致；
② 轮换 keep=2，快照 3 次后剩 2 份且最旧的被删；
③ 节流——min_interval_hours 内二次快照 skipped，force 强制；
④ run_sync 主体后 backup_dir 有新快照；dry_run 不产生；
⑥ restore 前自动安全网快照；
外加：restore 白名单（目录外快照拒绝）、CLI 三模式冒烟。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowatlas.config import Config
from knowatlas.datalayer.db import DataLayer
from knowatlas.models import Entry
from knowatlas.pipeline.backup import restore, snapshot, verify_snapshot


def _entry(**overrides) -> Entry:
    defaults = dict(
        source_type="bookmark", source_key="https://x.com/a",
        title="示例", locator="https://x.com/a",
        locator_canonical="https://x.com/a",
        meta={"source_type": "bookmark"},
    )
    defaults.update(overrides)
    return Entry.build(**defaults)


@pytest.fixture
def bcfg(tmp_path: Path) -> Config:
    data = {
        "general": {"db_path": str(tmp_path / "test.db"),
                    "backup_dir": str(tmp_path / "backups"),
                    "log_level": "WARNING",
                    "backup_on_sync": True, "backup_keep": 10,
                    "backup_min_interval_hours": 24},
        "sources": {"manual": {"enabled": True}},
    }
    return Config(data, tmp_path / "knowatlas.toml")


@pytest.fixture
def bdl(bcfg: Config):
    layer = DataLayer(bcfg.db_path)
    layer.init_schema()
    yield layer
    try:
        layer.close()  # restore 类测试内部已 close——幂等容错
    except Exception:
        pass


def _seed(dl: DataLayer, n: int = 3, tag: str = "a") -> None:
    """追加语义：tag 命名空间隔离（同 tag 重跑幂等不翻倍——upsert ON CONFLICT）。"""
    dl.upsert_entries([_entry(source_key=f"https://x.com/{tag}/{i}",
                              locator=f"https://x.com/{tag}/{i}",
                              title=f"条目{tag}{i}") for i in range(n)])


def _count(dl: DataLayer) -> int:
    return len(dl.list_entries(limit=10000))


def _snap_files(backup_dir: Path) -> list[str]:
    return sorted(p.name for p in backup_dir.iterdir() if p.suffix == ".db")


def test_snapshot_and_verify(bcfg, bdl):
    _seed(bdl, 3)
    stats = snapshot(bcfg, bdl, keep=5, force=True)
    assert stats["status"] == "ok"
    snap = bcfg.backup_dir / stats["file"]
    assert snap.is_file()
    v = verify_snapshot(snap)
    assert v["ok"] and v["integrity"] == "ok" and v["entries"] == 3


def test_restore_roundtrip_wal_probe1_safety_probe6(bcfg, bdl):
    """探针①：WAL 开启下恢复后条目数与快照时一致；探针⑥：安全网快照。"""
    _seed(bdl, 3)
    stats = snapshot(bcfg, bdl, keep=10, force=True)
    snap_at = bcfg.backup_dir / stats["file"]

    # 快照后再写 5 条（共 8；WAL 内可能有未 checkpoint 数据）
    _seed(bdl, 5, "b")
    assert _count(bdl) == 8
    wal = Path(str(bcfg.db_path) + "-wal")
    assert bdl._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    _ = wal.exists()  # WAL 文件存在与否取决于 checkpoint 时机，不断言其存在

    # restore 自包含：内部安全网快照 → close → 换文件 → sanity 对账
    r = restore(bcfg, bdl, snap_at)
    assert r["ok"], r
    assert r["entries"] == 3 == r["snapshot_entries"]
    # 探针⑥：恢复前自动安全网快照（恢复前库的 5 条形态留底）
    assert r["safety_snapshot"] in _snap_files(bcfg.backup_dir)

    # restore 返回时旧 -wal/-shm 已清（否则旧 WAL 会污染恢复出来的库）；
    # 注意：之后任何新连接都会按 WAL 模式重建 -wal（db 头持久化）——属正常行为
    assert not Path(str(bcfg.db_path) + "-wal").exists()
    assert not Path(str(bcfg.db_path) + "-shm").exists()
    # 重开库验证：恢复后就是快照时点（新写的 5 条不在）
    dl2 = DataLayer(bcfg.db_path)
    try:
        assert _count(dl2) == 3
        titles = {e.title for e in dl2.list_entries(limit=100)}
        assert "条目b4" not in titles
    finally:
        dl2.close()
    # 安全网快照里是恢复前的 8 条形态
    v = verify_snapshot(bcfg.backup_dir / r["safety_snapshot"])
    assert v["ok"] and v["entries"] == 8


def test_rotation_keep_probe2(bcfg, bdl):
    """探针②：轮换 keep=2——快照 3 次后剩 2 份且最旧的被删。"""
    _seed(bdl, 1)
    s1 = snapshot(bcfg, bdl, keep=2, force=True)
    s2 = snapshot(bcfg, bdl, keep=2, force=True)
    s3 = snapshot(bcfg, bdl, keep=2, force=True)
    assert s3["removed"] == [s1["file"]]
    files = _snap_files(bcfg.backup_dir)
    assert files == sorted([s2["file"], s3["file"]])
    assert s1["file"] not in files


def test_throttle_skip_probe3(bcfg, bdl):
    """探针③：节流——min_interval_hours 内二次快照 skipped；force 强制。"""
    _seed(bdl, 1)
    s1 = snapshot(bcfg, bdl, keep=10, min_interval_hours=24, force=True)
    s2 = snapshot(bcfg, bdl, keep=10, min_interval_hours=24)
    assert s2["status"] == "skipped" and s2["reason"] == "min_interval"
    assert s2["latest"] == s1["file"]
    s3 = snapshot(bcfg, bdl, keep=10, min_interval_hours=24, force=True)
    assert s3["status"] == "ok"


def test_restore_rejects_outside_and_badname(bcfg, bdl, tmp_path):
    """白名单：backup_dir 外的快照拒绝；非自家命名拒绝（防误恢复/路径穿越）。"""
    _seed(bdl, 1)
    outside = tmp_path / "other.db"
    outside.write_bytes(b"junk")
    r = restore(bcfg, bdl, outside)
    assert not r["ok"] and "备份目录" in r["error"]
    # 目录内但命名不合规（用户自己的文件，绝不碰）
    badname = bcfg.backup_dir / "我的重要文件.db"
    bcfg.backup_dir.mkdir(parents=True, exist_ok=True)
    badname.write_bytes(b"junk")
    r2 = restore(bcfg, bdl, badname)
    assert not r2["ok"] and "自家快照" in r2["error"]
    assert badname.exists()  # 原样不动


def test_sync_snapshots_before_write_probe4(bcfg, bdl, registries):
    """探针④：run_sync 主体后 backup_dir 有新快照；dry_run 不产生。"""
    from knowatlas.pipeline.sync import run_sync

    bcfg.raw["sources"]["bookmark"] = {"enabled": True, "roots": []}
    stats = run_sync(bcfg, bdl, registries[0], registries[1], dry_run=True)
    assert "backup" not in stats                      # 只读跑不备份
    assert not bcfg.backup_dir.exists() or _snap_files(bcfg.backup_dir) == []

    stats2 = run_sync(bcfg, bdl, registries[0], registries[1])
    assert stats2["backup"]["status"] == "ok"
    assert len(_snap_files(bcfg.backup_dir)) == 1


def test_sync_aborts_when_backup_fails(bcfg, bdl, registries):
    """契约=没快照不同步：快照失败中断同步、不写库。

    用「文件当目录」构造确定失败（Windows 上 /proc 式路径是项目根相对路径，
    mkdir 反而会成功——2026-10-21 调试发现，勿用）。
    """
    from knowatlas.pipeline.sync import run_sync

    blocker = bcfg.db_path.parent / "blocker.file"
    blocker.write_text("x", encoding="utf-8")
    bcfg.raw["general"]["backup_dir"] = str(blocker)  # 目录位是个文件 → mkdir 必失败
    stats = run_sync(bcfg, bdl, registries[0], registries[1])
    assert stats.get("aborted") == "backup_failed"
    assert stats["backup"]["status"] == "error"
    assert _count(bdl) == 0                           # 库未被写入


def test_cmd_kbackup_cli(bcfg, tmp_path, monkeypatch, capsys):
    """CLI 冒烟：--snap / --verify / --restore 三模式真跑。"""
    from knowatlas import cli

    seeder = DataLayer(bcfg.db_path)
    seeder.init_schema()
    _seed(seeder, 2)
    seeder.close()  # 不占锁：CLI 各子命令自己 _open，restore 要换文件
    args = type("A", (), {"snap": True, "restore": None, "verify": None,
                          "keep": None, "no_throttle": True})()
    monkeypatch.setattr(cli, "load_config", lambda: bcfg)
    monkeypatch.setattr(cli, "setup_logging", lambda *a: None)
    assert cli._cmd_kbackup(args) == 0
    out = capsys.readouterr().out
    assert "OK 快照完成" in out
    snap = bcfg.backup_dir / _snap_files(bcfg.backup_dir)[-1]

    # 恢复：_cmd_kbackup 内部自包含（安全网→close→换文件→sanity）
    args2 = type("A", (), {"snap": False, "restore": str(snap), "verify": None,
                           "keep": None, "no_throttle": True})()
    assert cli._cmd_kbackup(args2) == 0
    assert "OK 恢复" in capsys.readouterr().out

    args3 = type("A", (), {"snap": False, "restore": None, "verify": str(snap),
                           "keep": None, "no_throttle": True})()
    assert cli._cmd_kbackup(args3) == 0
    assert "OK 快照验证" in capsys.readouterr().out


# ---- 第四十七批修复：安全网轮换口径 / serve 占用预检 / 写失败结构化 ----

def test_restore_safety_rotation_reads_backup_keep_and_protects_source(bcfg, bdl):
    """安全网快照轮换读 cfg.backup_keep（原硬编码 keep=10）；且源快照受
    protect 保护——轮换该删的最旧快照恰是本次恢复源时不删（否则 copy2 无源）。"""
    bcfg.raw["general"]["backup_keep"] = 2
    _seed(bdl, 1)
    s1 = snapshot(bcfg, bdl, keep=bcfg.backup_keep, force=True)
    s2 = snapshot(bcfg, bdl, keep=bcfg.backup_keep, force=True)
    _seed(bdl, 1, "b")
    src = bcfg.backup_dir / s1["file"]
    r = restore(bcfg, bdl, src)
    assert r["ok"], r
    files = _snap_files(bcfg.backup_dir)
    assert s1["file"] in files                       # 源快照被 protect 留下
    assert len(files) == 3                           # keep=2 但保护源 → 暂 3 份，下轮收敛
    assert r["restored_from"] == s1["file"]


def test_restore_refuses_when_serve_port_busy(bcfg, bdl):
    """恢复前探测 serve 端口——可连通即拒（文件级操作需独占），任何破坏动作不发生。"""
    import socket

    _seed(bdl, 2)
    stats = snapshot(bcfg, bdl, keep=10, force=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        bcfg.raw["general"]["server_port"] = srv.getsockname()[1]
        r = restore(bcfg, bdl, bcfg.backup_dir / stats["file"])
    assert not r["ok"] and "停止 serve" in r["error"]
    assert _count(bdl) == 2                          # 预检拒绝发生在 close/换文件之前


def test_restore_copy_failure_points_to_safety_snapshot(bcfg, bdl, monkeypatch):
    """写文件阶段 OSError 结构化上报（不裸抛 traceback），指路安全网快照回滚。"""
    import knowatlas.pipeline.backup as bk

    _seed(bdl, 2)
    stats = snapshot(bcfg, bdl, keep=10, force=True)

    def _boom(s, d):
        raise PermissionError(32, "模拟占用：另一个进程正使用文件")

    monkeypatch.setattr(bk.shutil, "copy2", _boom)
    r = restore(bcfg, bdl, bcfg.backup_dir / stats["file"])
    assert not r["ok"] and "安全网" in r["error"]
    safety = bcfg.backup_dir / r["safety_snapshot"]
    assert safety.is_file() and verify_snapshot(safety)["entries"] == 2
