"""文件夹适配器（source_type=folder，完整方案 §3.2 / §12 步骤 10，M1）。

只翻译：遍历 [sources.folders].roots 下的文件 → 统一条目列表。
不读文件内容（K1：抓取只在 kadd / --fetch-limit，file_reader 已注册 file:// scheme）。

契约要点：
- source_key = 配置根相对路径（POSIX 风格 / 分隔，§3.2）；
- locator = file://<配置根相对路径>（禁绝对机器路径，§5——file_reader 按 roots 逐根解析）；
- native_path = 根目录名 / 子目录层级（TODO Phase 1 探针：嵌套目录路径正确进入 native_path）；
- meta.file_kind = document / pdf / office / other（TODO Phase 1：文档/PDF/其他分类标记）；
- 隐藏文件（. 开头）、Office 临时文件（~$ 开头）、符号链接跳过并计数。

过滤（0.2.0 补充，用户反馈：roots 里混入会话数据等非知识文件不该进条目）：
- exclude_globs：fnmatch 黑名单（匹配文件名或相对路径，如 "cj_session*"）；
  也可做目录级排除——fnmatch 的 * 会跨路径分隔符，故 "发票*" 可排除 发票/ 整棵目录；
- include_exts：扩展名白名单（如 [".txt", ".md", ".pdf"]）——设置后白名单外直接排除；
- 被排除文件不建条目、不计入 seen_rel，不参与 archive_missing 删除检测；
- 排除动作统计进 stats（skipped_excluded / skipped_ext）。

上限（0.2.0 第十四批）：max_entries 配置项（缺省 2000，<=0 视为不限）。**硬上限会让
全量同步静默截断**（真实案例：roots=D:/Data 撞 2000 后 617 个白名单文件永远进不来，
且未 collect 到的旧条目会被 archive_missing 误判为"源已删除"）——撞上限时 stats.truncated
>0 必须在同步报告里显式呈现。
"""

from __future__ import annotations

import fnmatch
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..models import Entry
from .base import AdapterOutput, match_path_pattern

_KIND_BY_SUFFIX: dict[str, str] = {}
for _s in (".txt", ".md", ".markdown", ".rst"):
    _KIND_BY_SUFFIX[_s] = "document"
_KIND_BY_SUFFIX[".pdf"] = "pdf"
for _s in (".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".wps", ".et"):
    _KIND_BY_SUFFIX[_s] = "office"

_MAX_FILES_DEFAULT = 2000  # 防失控上限缺省值（[sources.folders].max_entries 可覆盖，<=0=不限）


def _is_hidden_or_temp(p: Path) -> bool:
    return p.name.startswith(".") or p.name.startswith("~$") or p.name.endswith(".tmp")


def _mtime_iso(p: Path) -> str | None:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None


def collect_folders(config: Any) -> AdapterOutput:
    """按 [sources.folders] 遍历全部根目录，产出文件条目。"""
    roots = [str(r) for r in (config.get("sources.folders.roots") or []) if str(r).strip()]
    if not roots:
        raise AdapterError("[sources.folders].roots 为空",
                           hint="在 config/knowatlas.toml 填写要收录的根目录（绝对路径）")
    exclude_globs = [str(g) for g in (config.get("sources.folders.exclude_globs") or [])]
    include_exts = {str(x).lower() for x in (config.get("sources.folders.include_exts") or [])}
    # 目录级排除（0.2.0 第十五批，用户需求"要 d:/data 但不要 d:/data/Fiction"）：
    # 全局 [sources].exclude_dirs 供各文件系统型源共用（folder 及将来的 maildir/会话记录/
    # 微信导出目录），源级 [sources.folders].exclude_dirs 追加。匹配目录名或相对路径，
    # 支持通配：["Fiction", ".git", "项目/*_备份"]。命中的目录整棵不下钻（剪枝）。
    exclude_dirs = ([str(g) for g in (config.get("sources.exclude_dirs") or [])]
                    + [str(g) for g in (config.get("sources.folders.exclude_dirs") or [])])
    _raw_max = config.get("sources.folders.max_entries")
    max_files = _MAX_FILES_DEFAULT if _raw_max is None else int(_raw_max)
    entries: list[Entry] = []
    stats: dict[str, Any] = {
        "skipped_hidden": 0, "skipped_symlink": 0, "skipped_excluded": 0,
        "skipped_dir": 0, "skipped_ext": 0, "duplicate_rel": 0, "roots_ok": [],
        "seen_rel": set(),
    }
    over = 0
    for root_str in roots:
        root = Path(root_str)
        if not root.is_dir():
            raise AdapterError(f"根目录不存在：{root_str}",
                               hint="修正 config [sources.folders].roots 中的路径")
        stats["roots_ok"].append(root.name)
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            if rel_dir == ".":
                rel_dir = ""
            if exclude_dirs:  # 目录剪枝：命中的目录整棵不进入
                kept = []
                for d in dirnames:
                    child_rel = f"{rel_dir}/{d}" if rel_dir else d
                    if any(match_path_pattern(g, d, child_rel)
                           for g in exclude_dirs):
                        stats["skipped_dir"] += 1
                        continue
                    kept.append(d)
                dirnames[:] = sorted(kept)  # 排序保证遍历顺序稳定（幂等）
            for fn in sorted(filenames):
                p = Path(dirpath) / fn
                if p.is_symlink():
                    stats["skipped_symlink"] += 1
                    continue
                if _is_hidden_or_temp(p):
                    stats["skipped_hidden"] += 1
                    continue
                rel = p.relative_to(root).as_posix()
                suffix = p.suffix.lower()
                if any(match_path_pattern(g, p.name, rel)
                       for g in exclude_globs):
                    stats["skipped_excluded"] += 1
                    continue
                if include_exts and suffix not in include_exts:
                    stats["skipped_ext"] += 1
                    continue
                if rel in stats["seen_rel"]:
                    stats["duplicate_rel"] += 1
                stats["seen_rel"].add(rel)
                if max_files > 0 and len(entries) >= max_files:
                    over += 1
                    continue
                entries.append(Entry.build(
                    source_type="folder",
                    source_key=rel,
                    title=p.stem or p.name,
                    locator=f"file://{rel}",
                    locator_canonical=None,  # 非 http，无 canonical
                    native_path="/".join([root.name, *p.parent.relative_to(root).parts])
                    if p.parent != root else root.name,
                    meta={"source_type": "folder", "ext": suffix,
                          "file_kind": _KIND_BY_SUFFIX.get(suffix, "other"),
                          "size_bytes": p.stat().st_size},
                    created_at=_mtime_iso(p),
                ))
    stats.pop("seen_rel")
    if over:
        stats["truncated"] = over
    return AdapterOutput(entries=entries, stats=stats)
