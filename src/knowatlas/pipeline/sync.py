"""同步编排（完整方案 §3.6）。

两类同步策略：
- 全量遍历型（bookmark/folder/emmx/bili/session/db/wx 文件产物）：全量拉取 + 幂等 upsert
  + 删除检测（archive_missing）——各适配器在 M1 起逐个注册；
- 游标型（mail/ima/txdoc）：各自游标增量。

M0.5：批量适配器尚未接入；manual 源走 kadd（pipeline/kadd.py）。
K1：同步默认不抓正文（fetch.on_sync=false），--fetch-limit N 显式开启本次最多 N 条。
"""

from __future__ import annotations

import uuid
from typing import Any


def run_sync(cfg: Any, dl: Any, locators: Any, semantics: Any, *,
             full: bool = False, source: str | None = None, dry_run: bool = False,
             limit: int | None = None, fetch_limit: int | None = None) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:16]
    kind = "sync_full" if full else "sync_incremental"
    dl.start_run(run_id, kind)
    stats: dict[str, Any] = {
        "sources": {},
        "note": "M0.5：批量适配器尚未接入（bookmark/folder/emmx 属 M1）；manual 源请使用 kadd",
    }
    dl.finish_run(run_id, stats)
    return {"run_id": run_id, **stats}
