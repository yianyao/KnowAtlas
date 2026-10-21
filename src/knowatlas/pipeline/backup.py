"""自动备份与恢复（第四十六批，M5 Gate 后半）。

纯 SQLite 官方机制，零自研：
- 快照走 ``VACUUM INTO``——官方一致性快照，WAL 开启状态下安全（直接拷 .db
  文件会丢 -wal 内未 checkpoint 的数据，这是用内置机制不自己拷文件的理由）；
- 恢复 = 删目标 -wal/-shm + copy2 快照回 db_path + sanity（integrity_check）。

安全纪律（个人文件安全规则）：
- 轮换删除只认自家白名单：backup_dir 内 + knowledge- 前缀 + .db 后缀 +
  时间戳名格式，绝不碰用户放在同目录的其他文件；
- restore 只接受 backup_dir 内的快照文件（防路径穿越）；
- restore 前对当前库自动快照（安全网：恢复错了也有后悔药）。

节流：VACUUM INTO 是全库重建，大库成本高——min_interval_hours 内已有新
快照则跳过（ksync 频繁跑时不必每次全量重建）；force=True 或 CLI
--no-throttle 可强制。
"""

from __future__ import annotations

import re
import shutil
import socket
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SNAP_PREFIX = "knowledge-"
SNAP_SUFFIX = ".db"
# knowledge-YYYYmmdd-HHMMSS.db（秒级时间戳名，轮换按名排序即按时间排序）
_SNAP_NAME_RE = re.compile(r"^knowledge-\d{8}-\d{6}\.db$")


def _is_snap_name(name: str) -> bool:
    return bool(_SNAP_NAME_RE.match(name))


def _list_snapshots(backup_dir: Path) -> list[Path]:
    """目录内自家快照（名字不合白名单的一律不当快照，轮换绝不碰）。"""
    if not backup_dir.is_dir():
        return []
    snaps = [p for p in backup_dir.iterdir() if p.is_file() and _is_snap_name(p.name)]
    return sorted(snaps, key=lambda p: p.name)  # 名内时间戳字典序 = 时间序


def _serve_port_busy(cfg: Any) -> bool:
    """本机 serve 端口可连通即视为运行中（恢复是文件级操作，需独占）。

    与 web/api._port_of 同默认端口；pipeline 不反向依赖 web 层，就地小探测。
    """
    port = int(cfg.get("general.server_port", 8420))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def snapshot(cfg: Any, dl: Any, *, keep: int = 10,
             min_interval_hours: int = 24, force: bool = False,
             protect: set[str] | None = None) -> dict[str, Any]:
    """VACUUM INTO 一致性快照 + 轮换。返回统计 dict。

    keep<=0 表示不轮换（只增不减，用户自负）。
    节流命中返回 {"status": "skipped", ...}（不写库、不删文件）。
    protect：轮换跳过的文件名集合（restore 保护本次恢复的源快照不被
    安全网快照的轮换删掉——被删了 copy2 就没源了）。
    """
    backup_dir = Path(cfg.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    existing = _list_snapshots(backup_dir)
    if not force and existing and min_interval_hours > 0:
        latest = existing[-1]
        m = re.search(r"knowledge-(\d{8})-(\d{6})\.db$", latest.name)
        if m:
            stamp = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            age_h = (datetime.now() - stamp).total_seconds() / 3600
            if age_h < min_interval_hours:
                return {"status": "skipped", "reason": "min_interval",
                        "latest": latest.name, "age_hours": round(age_h, 2)}

    name = "knowledge-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
    dest = backup_dir / name
    # VACUUM INTO 目标必须不存在；同秒重名（批量脚本连跑）等到下一秒——
    # 不编造后缀名：白名单正则钉死时间戳格式，轮换/识别都靠它
    waited = 0.0
    while dest.exists():
        time.sleep(1.05)  # 固定多睡 50ms，严格跨秒（边界精度不可靠）
        waited += 1.05
        if waited > 70:
            raise RuntimeError(f"快照名持续冲突（{dest.name}），放弃")
        name = "knowledge-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
        dest = backup_dir / name
    # 路径转 POSIX 字符串进 SQL（反斜杠在 SQLite 字符串里是字面量，安全；
    # 但引号需防注入——dest 由本函数生成，无用户可控部分）
    dl.vacuum_into(dest)
    dl.log_task(datetime.now().isoformat(timespec="seconds"), "backup",
                "snapshot", "", {"file": name, "keep": keep})

    removed: list[str] = []
    if keep > 0:
        snaps = _list_snapshots(backup_dir)
        for old in snaps[:-keep] if len(snaps) > keep else []:
            if protect and old.name in protect:
                continue  # 受保护的源快照不删（份数暂时 keep+1，下轮轮换自然收敛）
            old.unlink()
            removed.append(old.name)
    return {"status": "ok", "file": name, "removed": removed,
            "total": len(_list_snapshots(backup_dir))}


def verify_snapshot(snap_path: Path | str) -> dict[str, Any]:
    """恢复演练验证：integrity_check + entries 数 + 文件时间。"""
    p = Path(snap_path)
    if not p.is_file():
        return {"ok": False, "error": f"快照不存在：{p}"}
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        n = conn.execute("SELECT count(*) FROM entries").fetchone()[0]
    finally:
        conn.close()
    return {"ok": integrity == "ok", "integrity": integrity, "entries": n,
            "file": p.name, "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}


def restore(cfg: Any, dl: Any, snap_path: Path | str) -> dict[str, Any]:
    """从快照恢复 db_path。**自包含：内部会 close dl**（文件级操作前必须关
    连接，否则 WAL/shm 占着不放；返回后调用方如需继续用库要自行重开）。

    步骤：白名单校验（snap 须在 backup_dir 内）→ serve 端口预检（占用即拒，
    文件级操作需独占）→ 恢复前自动安全网快照（用原 dl 连接做 VACUUM INTO，
    轮换份数读 cfg.backup_keep、并保护源快照不被轮换删掉）→ close →
    删目标 -wal/-shm → copy2 快照回 db_path（OSError 结构化上报，指路安全网
    快照回滚）→ 重开只读连接 sanity（integrity_check + 条目数对账）。
    """
    backup_dir = Path(cfg.backup_dir).resolve()
    src = Path(snap_path).resolve()
    if backup_dir not in src.parents:
        return {"ok": False, "error": f"快照须在备份目录内：{backup_dir}（收到 {src}）"}
    if not _is_snap_name(src.name):
        return {"ok": False, "error": f"不是自家快照文件名：{src.name}"}
    v = verify_snapshot(src)
    if not v["ok"]:
        return {"ok": False, "error": f"快照自身校验失败：{v}"}
    if _serve_port_busy(cfg):
        port = int(cfg.get("general.server_port", 8420))
        return {"ok": False, "error": (
            f"检测到本机服务可能正在运行（端口 {port} 可连通）。恢复是文件级"
            f"操作需独占 db，请先停止 serve 再恢复。")}

    # 安全网：恢复前对当前库自动快照（此刻 dl 连接仍开着，VACUUM INTO 可用）；
    # 轮换口径与日常快照一致读 backup_keep，且绝不轮换掉本次恢复的源快照
    safety = snapshot(cfg, dl, keep=cfg.backup_keep, force=True, protect={src.name})
    if safety.get("status") != "ok":
        return {"ok": False, "error": f"安全网快照失败，已中止恢复：{safety}"}

    dl.close()  # 文件级操作前关连接（自包含，调用方无需预先 close）
    db = Path(cfg.db_path)
    try:
        for ext in ("-wal", "-shm"):
            side = db.with_name(db.name + ext)
            if side.exists():
                side.unlink()
        db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, db)
    except OSError as exc:
        # 此刻原库文件本体未动（仅可能丢了 -wal 未 checkpoint 数据）——
        # 安全网快照含完整恢复前形态，指路回滚
        return {"ok": False, "error": (
            f"恢复写文件失败（库可能被其他进程占用，关闭后重试）："
            f"{type(exc).__name__}: {exc}。原库已自动快照留底"
            f"（安全网）：{safety['file']}，可 kbackup --restore 回滚。"),
            "safety_snapshot": safety["file"]}

    # sanity：重开只读连接验证恢复结果
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        n = conn.execute("SELECT count(*) FROM entries").fetchone()[0]
    finally:
        conn.close()
    ok = integrity == "ok" and n == v["entries"]
    return {"ok": ok, "restored_from": src.name, "safety_snapshot": safety["file"],
            "integrity": integrity, "entries": n, "snapshot_entries": v["entries"]}
