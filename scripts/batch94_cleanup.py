"""批次 94 真库数据质量清理（用户截图指认四类问题；先 --scan 审阅后 --apply）。

垃圾类（仅 source_type='expand'——扩散抓取的垃圾，用户已指认可直接裁决；
folder/bookmark 源不在本脚本裁决范围）：
- blacklist：locator 文件名命中仓库元数据黑名单（.nojekyll 等）；
- empty_body：正文为空（inline + content_store 均无）；
- skeleton_body：正文命中 is_skeleton_body（HTML 实体骨架 / 目录索引重复行，
  批次 94 四路信号）。

处置：set_status rejected + meta.rejected_at（30 天冷却，误裁可 restore）+
task_log 留痕（action=batch94_reject，detail 记类与原因）。点不删——消费面
SQL 只认 active 溯源，垃圾条目的点自动退出消费面；反悔恢复条目即恢复点。

另做 display_name 回填（非破坏）：gh 扩散的 active 条目缺 display_name 时
补「种子名 · 文件名」——修复来源 chips 裸文件名显示（截图 1 指认）。

用法：
    python scripts/batch94_cleanup.py            # 扫描打印（默认，零写入）
    python scripts/batch94_cleanup.py --apply    # 裁决生效（rejected + 回填）

环境：KNOWATLAS_HOME=%USERPROFILE%\\.knowatlas。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knowatlas.config import load_config
from knowatlas.datalayer.db import DataLayer
from knowatlas.fetchers.base import is_skeleton_body
from knowatlas.pipeline.expand import _GH_FILE_LINK, _GH_FILE_NAME_BLACKLIST


def _file_name(locator: str) -> str:
    return unquote((locator or "").split("://")[-1].split("?")[0]
                   .rstrip("/").rsplit("/", 1)[-1]).lower()


def main() -> int:
    apply = "--apply" in sys.argv
    cfg = load_config()
    dl = DataLayer(cfg.db_path)
    garbage: list[tuple[str, str, str]] = []   # (entry_id, class, reason)
    backfill: list[tuple[str, str]] = []       # (entry_id, display_name)
    scanned = 0
    for e in dl.list_entries(status="active", limit=100000):
        if e.source_type != "expand":
            continue
        scanned += 1
        name = _file_name(e.locator)
        if name in _GH_FILE_NAME_BLACKLIST:
            garbage.append((e.id, "blacklist", f"文件名 {name}"))
            continue
        body = (e.inline_content or "").strip()
        if not body and e.content_hash:
            body = (dl.get_content(e.content_hash) or "").strip()
        if not body:
            garbage.append((e.id, "empty_body", e.locator[:120]))
            continue
        if is_skeleton_body(body):
            garbage.append((e.id, "skeleton_body",
                            f"{len(body)} 字符 {e.locator[:90]}"))
            continue
        if e.meta.get("display_name"):
            continue
        m = _GH_FILE_LINK.match(e.locator or "")
        if not m:
            continue
        fname = unquote(m.group(5).strip("/").rsplit("/", 1)[-1])
        stem = fname.rsplit(".", 1)[0] if "." in fname else fname
        # 前缀用仓库名（不用种子标题——gh 书签标题常是 GitHub 全量描述，
        # 与 expand.py 新建条目的标题公式同口径）
        backfill.append((e.id, f"{m.group(2)} · {stem}"[:120]))

    print(f"扫描 expand 条目 {scanned} 条：垃圾 {len(garbage)} / "
          f"display_name 待回填 {len(backfill)}")
    for eid, cls, reason in garbage:
        print(f"  [垃圾/{cls}] {eid} {reason}")
    for eid, dn in backfill:
        print(f"  [回填] {eid} -> {dn}")
    if not apply:
        print("（--scan 模式零写入；确认清单后加 --apply 生效）")
        dl.close()
        return 0

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    ids = [eid for eid, _c, _r in garbage]
    if ids:
        dl.set_status(ids, "rejected")
    for eid, cls, reason in garbage:
        dl.merge_meta(eid, {"rejected_at": now,
                            "reject_reason": f"batch94:{cls}"})
        dl.log_task(now, "batch94", "reject", eid, {"class": cls, "reason": reason})
    for eid, dn in backfill:
        dl.merge_meta(eid, {"display_name": dn})
        dl.log_task(now, "batch94", "display_name_backfill", eid,
                    {"display_name": dn})
    print(f"APPLY 完成：rejected {len(ids)} 条（30 天冷却）| 回填 {len(backfill)} 条")
    dl.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
