"""浏览器书签适配器（source_type=bookmark，完整方案 §3.2 / §12 步骤 9）。

只翻译：读取 Chrome/Edge 的 Bookmarks JSON（两者格式相同）→ 统一条目列表。
不抓网页、不分类（抓取由 fetchers 在 pipeline 层完成，分类由 semantic 完成）。

契约要点：
- source_key = 浏览器名 + 书签节点 id（§3.2）；节点无 id 时用「收藏夹路径 + 标题」兜底；
- native_path = 收藏夹层级路径（如「书签栏/技术/数据库」），供先验映射
  （semantic/priors.py）消费——书签文件夹是免费且可靠的分类信号；
- 非 http/https 的书签（chrome://、edge://、javascript: 等）不进索引，仅计数；
- 同一 URL 在多个文件夹重复收藏 → 不同节点 id 各建一条（M2 跨源去重统一处理），
  stats.duplicate_urls 记录重复次数供运维观察。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..ids import canonical_url
from ..models import Entry
from .base import AdapterOutput

# Chrome/Edge Bookmarks JSON 的三个根；native_path 用稳定中文标签开头
# （先验映射表 PRIOR_MAP 依赖此前缀，改名必须同步 priors.py 并跑 canary）
_ROOT_LABELS: dict[str, str] = {
    "bookmark_bar": "书签栏",
    "other": "其他书签",
    "synced": "移动设备书签",
}


def _webkit_ts_to_iso(raw: Any) -> str | None:
    """Chrome/Edge date_added：1601-01-01 起的微秒字符串 → 本地时区 ISO 8601。

    解析失败返回 None（created_at 允许为空，不因脏数据丢条目）。
    """
    try:
        us = int(str(raw))
    except (TypeError, ValueError):
        return None
    if us <= 0:
        return None
    return (datetime(1601, 1, 1) + timedelta(microseconds=us)).astimezone().isoformat(timespec="seconds")


def _walk(browser: str, node: dict[str, Any], path_parts: list[str],
          entries: list[Entry], stats: dict[str, int]) -> None:
    """深度优先遍历书签树；url 节点产条目，folder 节点下钻，其余类型计数跳过。"""
    ntype = node.get("type")
    if ntype == "url":
        url = str(node.get("url") or "").strip()
        canon = canonical_url(url)
        if canon is None:
            stats["skipped_non_http"] += 1
            return
        title = str(node.get("name") or "").strip() or canon
        native_path = "/".join(path_parts)
        node_id = str(node.get("id") or "").strip()
        source_key = f"{browser}:{node_id}" if node_id else f"{browser}:{native_path}::{title}"
        meta = {"source_type": "bookmark", "browser": browser, "native_path": native_path}
        entries.append(Entry.build(
            source_type="bookmark",
            source_key=source_key,
            title=title,
            locator=url,
            locator_canonical=canon,
            native_path=native_path or None,
            meta=meta,
            created_at=_webkit_ts_to_iso(node.get("date_added")),
        ))
        if canon in stats["_seen_canonicals"]:
            stats["duplicate_urls"] += 1
        else:
            stats["_seen_canonicals"].add(canon)
        return
    if ntype != "folder":
        # Chrome/Edge 理论上只有 url/folder 两型；防御未知类型
        stats["skipped_other"] += 1
        return
    name = str(node.get("name") or "").strip()
    child_path = [*path_parts, name] if name else path_parts
    for child in node.get("children") or []:
        if isinstance(child, dict):
            _walk(browser, child, child_path, entries, stats)


def collect_bookmarks(config: Any) -> AdapterOutput:
    """按 [sources.bookmarks] 收集全部浏览器的书签条目。

    单个浏览器文件缺失/损坏抛 AdapterError（跳过整个源，其余源继续）。
    """
    sec = config.get("sources.bookmarks") or {}
    browsers = sec.get("browsers") or []
    paths = sec.get("paths") or {}
    entries: list[Entry] = []
    stats: dict[str, Any] = {
        "skipped_non_http": 0, "skipped_other": 0, "duplicate_urls": 0,
        "_seen_canonicals": set(), "browsers_ok": [],
    }
    for browser in browsers:
        raw_path = str((paths.get(browser) if isinstance(paths, dict) else None) or "").strip()
        if not raw_path:
            continue
        file = Path(raw_path)
        if not file.is_file():
            raise AdapterError(
                f"{browser} 书签文件不存在：{raw_path}",
                hint="在 config/knowatlas.toml [sources.bookmarks.paths] 修正路径，"
                     "或把该浏览器从 browsers 列表移除",
            )
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AdapterError(f"{browser} 书签文件解析失败：{raw_path}（{exc}）",
                               hint="浏览器未正常退出可能写坏 Bookmarks 文件，重启浏览器后重试") from exc
        roots = data.get("roots")
        if not isinstance(roots, dict):
            raise AdapterError(f"{browser} 书签文件缺少 roots 节：{raw_path}",
                               hint="确认这是 Chrome/Edge 的 Bookmarks 文件而非书签导出 HTML")
        for root_key, label in _ROOT_LABELS.items():
            node = roots.get(root_key)
            if not isinstance(node, dict):
                continue
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    _walk(browser, child, [label], entries, stats)
        stats["browsers_ok"].append(browser)
    stats.pop("_seen_canonicals")
    return AdapterOutput(entries=entries, stats=stats)
