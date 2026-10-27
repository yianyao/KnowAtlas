"""DataLayer 组合与连接/事务/迁移：唯一 sqlite3 建连处（原 datalayer/db.py 的 core 部分）。"""

from __future__ import annotations

import functools
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..errors import ContractError
from .categories import _CategoriesMixin
from .content import _ContentMixin
from .entries import _EntriesMixin
from .graph import _GraphMixin
from .ops import _OpsMixin
from .points import _PointsMixin
from .schema import latest_version, load_migration
from .search import _SearchMixin
from .threads import _ThreadsMixin
from .vectors import _VectorsMixin
from .views import _ViewsMixin


class _CoreMixin:
    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        self._lock = threading.RLock()
        # check_same_thread=False：web 层线程池访问；并发安全由 self._lock 串行化保证
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 连接纪律（§3.4）
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        # 实例级串行化：公开方法统一加锁（RLock 可重入，事务方法自行持锁）。
        # 必须扫整个 MRO：拆分后 DataLayer 只做组合，方法都在各 mixin 里；
        # 只扫 vars(type(self)) 会让父类方法漏包 → 锁静默失效。按 name 去重，派生类优先。
        seen: set[str] = set()
        for klass in type(self).__mro__[:-1]:
            for name, fn in vars(klass).items():
                if name.startswith("_") or name == "transaction" or not callable(fn):
                    continue
                if name in seen:
                    continue
                seen.add(name)
                setattr(self, name, functools.partial(self._guard, fn))

    def _guard(self, fn, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ---- 建库与迁移（只进不前） ----

    def init_schema(self) -> int:
        """建库与迁移（只进不前，0.2.0 第三十二批升级为多迁移按序应用）。

        - user_version=0（新库）→ 从 001 起顺序应用全部迁移；
        - user_version 介于 1..latest-1（旧库）→ 只应用缺失的后续迁移
          （如 001→002 加 threads 表，既有数据无损）；
        - user_version > latest（库比代码新）→ 明确报错，绝不用旧代码静默写新库。
        """
        latest = latest_version()
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > latest:
            raise ContractError(
                f"数据库 user_version={version} 高于代码支持的 {latest}",
                hint="该库由更新版本的 knowatlas 创建：请升级 knowatlas，或用旧版备份恢复",
            )
        if version == latest:
            return version
        for v in range(version + 1, latest + 1):
            self._conn.executescript(load_migration(v))
            self._conn.commit()
            self._conn.execute(f"PRAGMA user_version = {v}")
            self._conn.commit()
        return latest


class DataLayer(
    _EntriesMixin,
    _CategoriesMixin,
    _PointsMixin,
    _GraphMixin,
    _ViewsMixin,
    _ThreadsMixin,
    _VectorsMixin,
    _ContentMixin,
    _SearchMixin,
    _OpsMixin,
    _CoreMixin,
):
    """组合类：方法全在各 mixin 里，这里只声明 MRO。

    锁由 `_CoreMixin.__init__` 按 `type(self).__mro__` 扫描后统一包装（见 tests/
    test_datalayer_surface.py::test_public_methods_are_lock_guarded）。
    """
