"""兼容 façade：拆分后 DataLayer 在 datalayer/core.py 组装。

外部一律 `from knowatlas.datalayer.db import DataLayer`（tests/、cli/、web/ 均如此），
所以保留本文件作为稳定导入路径；真正实现见 datalayer/ 的 9 个 mixin + core.py。
"""

from __future__ import annotations

from ._common import REJECT_COOLING_DAYS
from .core import DataLayer

__all__ = ["DataLayer", "REJECT_COOLING_DAYS"]
