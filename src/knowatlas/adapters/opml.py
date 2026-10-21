"""OPML 导入适配器（source_type=opml，0.2.0 第五十批）。

用途：把外部工具导出的 OPML 大纲文件（书签/订阅列表迁移、本工具 kexport
--format opml 的产物回吃）作为 ksync 批量源导入。只翻译：outline 树 →
统一条目列表；不抓网页、不分类。

契约要点：
- [sources.opml] enabled + files（OPML 文件路径数组）；单文件缺失/解析失败
  抛 AdapterError（跳过整个源，其余源继续）；
- outline 嵌套 = native_path（text/title 属性逐层拼接）；有 htmlUrl 的
  outline 产条目，纯容器下钻；type="rss" 只有 xmlUrl 无 htmlUrl 的是订阅源，
  不是知识条目，跳过计数；
- 非 http/https 的 htmlUrl（ftp:// 等）canonical 校验不通过，仅计数——
  与 bookmark 源同一纪律；
- source_key = 文件标识 + outline 全路径 + 标题兜底（OPML 无稳定节点 id；
  文件标识取配置里写的路径串，改名=换源，旧条目归档重建，SOP 注明）；
- created 属性：先按 ISO 8601 解析（本工具导出形态），再按 RFC 822
  （OPML 2.0 标准常用形态，email.utils 标准库）；都失败置 NULL 不臆造；
- 同一 URL 在不同 outline 分支重复 → 各建一条（与 bookmark 源一致），
  stats.duplicate_urls 计数，跨源去重（M2 判据）统一兜底。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..ids import canonical_url
from ..models import Entry
from .base import AdapterOutput


def _parse_created(raw: Any) -> str | None:
    """outline@created：ISO 8601 优先（本工具导出），RFC 822 兜底（OPML 2.0
    惯例）；无法解析置 NULL 不臆造。"""
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).astimezone().isoformat(timespec="seconds")
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s).astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def _walk(node: ET.Element, path_parts: list[str], file_key: str,
          entries: list[Entry], stats: dict[str, Any]) -> None:
    """深度优先遍历 outline 树；有 htmlUrl 产条目，容器下钻。"""
    url = (node.get("htmlUrl") or node.get("htmlurl") or "").strip()
    label = (node.get("text") or node.get("title") or "").strip()
    if url:
        canon = canonical_url(url)
        if canon is None:
            stats["skipped_non_http"] += 1
        else:
            title = label or canon
            native_path = "/".join(path_parts)
            entries.append(Entry.build(
                source_type="opml",
                source_key=f"{file_key}:{native_path}::{title}",
                title=title,
                locator=url,
                locator_canonical=canon,
                native_path=native_path or None,
                meta={"source_type": "opml", "native_path": native_path},
                created_at=_parse_created(node.get("created")),
            ))
            if canon in stats["_seen_canonicals"]:
                stats["duplicate_urls"] += 1
            else:
                stats["_seen_canonicals"].add(canon)
    elif node.get("xmlUrl") or node.get("xmlurl"):
        # type="rss" 订阅源（只有 xmlUrl）：不是知识条目
        stats["skipped_rss"] += 1
    child_path = [*path_parts, label] if label else path_parts
    for child in node:
        if child.tag.lower().endswith("outline"):
            _walk(child, child_path, file_key, entries, stats)


def collect_opml(config: Any) -> AdapterOutput:
    """按 [sources.opml] 收集全部 OPML 文件的条目。

    单个文件缺失/解析失败抛 AdapterError（跳过整个源，其余源继续）。
    """
    sec = config.get("sources.opml") or {}
    files = [str(p).strip() for p in (sec.get("files") or []) if str(p).strip()]
    entries: list[Entry] = []
    stats: dict[str, Any] = {
        "skipped_non_http": 0, "skipped_rss": 0, "duplicate_urls": 0,
        "_seen_canonicals": set(), "files_ok": [],
    }
    if not files:
        raise AdapterError(
            "[sources.opml] enabled 但 files 为空",
            hint="在 config/knowatlas.toml [sources.opml] 配置 files = [\"<OPML 文件路径>\"]，"
                 "或把 enabled 改回 false",
        )
    for raw_path in files:
        file = Path(raw_path)
        if not file.is_file():
            raise AdapterError(
                f"OPML 文件不存在：{raw_path}",
                hint="在 config/knowatlas.toml [sources.opml] files 修正路径；"
                     "文件改名=换源（旧条目归档、新条目重建），尽量用稳定路径",
            )
        try:
            root = ET.parse(file).getroot()
        except ET.ParseError as exc:
            raise AdapterError(f"OPML 文件解析失败：{raw_path}（{exc}）",
                               hint="确认文件是合法 XML/OPML 2.0（可被其他工具打开）") from exc
        body = root.find("body")
        if body is None:
            raise AdapterError(f"OPML 文件缺少 <body> 节：{raw_path}",
                               hint="确认文件是合法 OPML 2.0（outline 必须在 body 下）")
        file_key = raw_path.replace("\\", "/")
        # 只从 body 的**直接子** outline 起遍历——嵌套 outline 由 _walk 递归
        # 处理（若用 root.iter() 会把嵌套节点重复当顶层，native_path 丢层级）
        for node in body:
            if node.tag.lower().endswith("outline"):
                _walk(node, [], file_key, entries, stats)
        stats["files_ok"].append(str(file.name))
    stats.pop("_seen_canonicals")
    return AdapterOutput(entries=entries, stats=stats)
