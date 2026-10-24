"""批次 94/95 真库数据质量清理（用户截图指认；先 --scan 审阅后 --apply）。

垃圾类（仅 source_type='expand'——扩散抓取的垃圾，用户已指认可直接裁决；
folder/bookmark 源不在自动 reject 范围）：
- blacklist：locator 文件名命中仓库元数据/站点家具黑名单（.nojekyll、
  coverpage/navbar/sidebar 等，批次 95 扩充）；
- empty_body：正文为空（inline + content_store 均无）；
- skeleton_body：正文命中 is_skeleton_body（HTML 实体骨架 / 目录索引重复行 /
  GitHub 页面模板标记，批次 94/95 五路信号）。

骨架类（批次 95，**任意源**）：正文判骨架的存量条目 → merge_meta
body_flag=skeleton（degraded 等重抓，不 reject）+ purge_entry_points 清其
独源点（骨架正文产的点必是垃圾；多源点保留，其他溯源仍有效）。

处置：set_status rejected + meta.rejected_at（30 天冷却，误裁可 restore）+
task_log 留痕（action=batch94_reject，detail 记类与原因）。点不删——消费面
SQL 只认 active 溯源，垃圾条目的点自动退出消费面；反悔恢复条目即恢复点。

另做 display_name 回填（非破坏）：gh 扩散的 active 条目缺 display_name 时
补「仓库名 · 文件名」——修复来源 chips 裸文件名显示（截图指认）。

--apply 末尾跑 scan_and_merge（批次 95：canonical GitHub 仓库页归一后，
根页与 /tree/main 变体书签合并为 dedupe_master 组）。

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
from knowatlas.pipeline.dedupe import scan_and_merge
from knowatlas.pipeline.expand import _GH_FILE_LINK, _GH_FILE_NAME_BLACKLIST


def _file_name(locator: str) -> str:
    return unquote((locator or "").split("://")[-1].split("?")[0]
                   .rstrip("/").rsplit("/", 1)[-1]).lower()


def main() -> int:
    apply = "--apply" in sys.argv
    cfg = load_config()
    dl = DataLayer(cfg.db_path)
    garbage: list[tuple[str, str, str]] = []   # (entry_id, class, reason)
    skeleton_any: list[tuple[str, str]] = []   # 任意源骨架：条目 + 正文长度
    backfill: list[tuple[str, str]] = []       # (entry_id, display_name)
    scanned = 0
    all_active = dl.list_entries(status="active", limit=100000)
    for e in all_active:
        scanned += 1
        body = (e.inline_content or "").strip()
        if not body and e.content_hash:
            body = (dl.get_content(e.content_hash) or "").strip()
        # 任意源骨架（批次 95）：先于 expand 垃圾判定——expand 骨架走 reject，
        # 其余源走 degraded 标记
        if body and is_skeleton_body(body):
            if e.source_type == "expand":
                garbage.append((e.id, "skeleton_body",
                                f"{len(body)} 字符 {e.locator[:90]}"))
            else:
                skeleton_any.append((e.id, f"{len(body)} 字符 {e.locator[:90]}"))
            continue
        if e.source_type != "expand":
            continue
        name = _file_name(e.locator)
        if name in _GH_FILE_NAME_BLACKLIST:
            garbage.append((e.id, "blacklist", f"文件名 {name}"))
            continue
        if not body:
            garbage.append((e.id, "empty_body", e.locator[:120]))
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

    print(f"扫描条目 {scanned} 条：expand 垃圾 {len(garbage)} / "
          f"任意源骨架 {len(skeleton_any)} / display_name 待回填 {len(backfill)}")
    for eid, cls, reason in garbage:
        print(f"  [垃圾/{cls}] {eid} {reason}")
    for eid, reason in skeleton_any:
        print(f"  [骨架/degraded] {eid} {reason}")
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
    # 任意源骨架：degraded 标记 + 清独源点（点消了游标也清，重抓后可重抽）
    for eid, reason in skeleton_any:
        purged = dl.purge_entry_points(eid, reason="batch95 skeleton body",
                                       task_name="batch94")
        dl.merge_meta(eid, {"body_flag": "skeleton"})
        dl.log_task(now, "batch95", "skeleton_degraded", eid,
                    {"reason": reason, "points_purged": purged})
    for eid, dn in backfill:
        dl.merge_meta(eid, {"display_name": dn})
        dl.log_task(now, "batch94", "display_name_backfill", eid,
                    {"display_name": dn})
    print(f"APPLY 完成：rejected {len(ids)} 条（30 天冷却）| 骨架 degraded "
          f"{len(skeleton_any)} 条 | 回填 {len(backfill)} 条")
    merge_stats = scan_and_merge(dl)  # 批次 95：canonical 归一后的存量合并
    print(f"canonical 合并扫描：{merge_stats}")
    dl.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
