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
- include_exts：扩展名白名单（如 [".txt", ".md", ".pdf"]）——设置后白名单外直接排除；
- 被排除文件不建条目、不计入 seen_rel，不参与 archive_missing 删除检测；
- 排除动作统计进 stats（skipped_excluded / skipped_ext）。
"""

from __future__ import annotations

import fnmatch
from datetime import datetime
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..models import Entry
from .base import AdapterOutput

_KIND_BY_SUFFIX: dict[str, str] = {}
for _s in (".txt", ".md", ".markdown", ".rst"):
    _KIND_BY_SUFFIX[_s] = "document"
_KIND_BY_SUFFIX[".pdf"] = "pdf"
for _s in (".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".wps", ".et"):
    _KIND_BY_SUFFIX[_s] = "office"

_MAX_FILES = 2000  # 防失控上限（超限计数并截断）


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
    entries: list[Entry] = []
    stats: dict[str, Any] = {
        "skipped_hidden": 0, "skipped_symlink": 0, "skipped_excluded": 0,
        "skipped_ext": 0, "duplicate_rel": 0, "roots_ok": [], "seen_rel": set(),
    }
    over = 0
    for root_str in roots:
        root = Path(root_str)
        if not root.is_dir():
            raise AdapterError(f"根目录不存在：{root_str}",
                               hint="修正 config [sources.folders].roots 中的路径")
        stats["roots_ok"].append(root.name)
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if p.is_symlink():
                stats["skipped_symlink"] += 1
                continue
            if _is_hidden_or_temp(p):
                stats["skipped_hidden"] += 1
                continue
            rel = p.relative_to(root).as_posix()
            suffix = p.suffix.lower()
            if any(fnmatch.fnmatch(p.name, g) or fnmatch.fnmatch(rel, g)
                   for g in exclude_globs):
                stats["skipped_excluded"] += 1
                continue
            if include_exts and suffix not in include_exts:
                stats["skipped_ext"] += 1
                continue
            if rel in stats["seen_rel"]:
                stats["duplicate_rel"] += 1
            stats["seen_rel"].add(rel)
            if len(entries) >= _MAX_FILES:
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
