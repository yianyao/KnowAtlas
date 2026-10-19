"""万兴脑图适配器（source_type=emmx，完整方案 §3.2 / §12 步骤 15，M1）。

.emmx = ZIP 包，主数据在 content.xml（MindMaster XML）。本模块做**防御性解析**：
- 遍历 topic 元素树（title/name 属性任取其一），children/topics 嵌套——
  覆盖 MindMaster 常见版本结构；节点 id 取 XML id 属性，缺失时用路径序号兜底；
- content.xml 缺失 / 无 topic 结构 / XML 解析失败 → 降级标题级（单条目，文件名做主题），
  meta.degraded=true（TODO Phase 1：page.bin 二进制情况下降级并标记）；
- 真实 .emmx 样本验收探针（解析出中心主题与主分支）待用户提供文件后执行。

契约：source_key = 文件相对路径 + 节点 id（§3.2）；locator = emmx://<相对路径>#<节点 id>；
native_path = 文件所在目录层级（先验信号），脑图内部主题路径进 meta.mind_path。
"""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..errors import AdapterError
from ..models import Entry
from .base import AdapterOutput

_MAX_NODES = 3000  # 单脑图节点上限（防失控）


def _node_title_safe(elem: ElementTree.Element) -> str:
    """topic 标题：title 属性优先，name 次之，再取元素文本首行。"""
    t = elem.get("title") or elem.get("name") or ""
    if not t and elem.text:
        t = elem.text.strip().splitlines()[0] if elem.text.strip() else ""
    return t.strip()


def _walk_topics(elem: ElementTree.Element, path: list[str], rel: str, root_dir_name: str,
                 entries: list[Entry], stats: dict[str, Any]) -> None:
    """递归收集 topic 节点。topic = 标签名含 topic 的元素（大小写不敏感）。"""
    if stats["nodes"] >= _MAX_NODES:
        stats["truncated"] = stats.get("truncated", 0) + 1
        return
    tag = elem.tag.rsplit("}", 1)[-1].lower()
    is_topic = tag == "topic"
    title = _node_title_safe(elem) if is_topic else ""
    node_id = elem.get("id") or ""
    if is_topic:
        child_path = [*path, title] if title else path
        stats["nodes"] += 1
        if title:
            # 根 topic（中心主题）之外的分支与叶节点都建条目；中心主题也建（脑图名已由文件名承载，跳过纯标题=文件名的中心主题？——保留，多一条锚点条目无害）
            key_node = node_id or "-".join(str(i + 1) for i in range(len(child_path)))
            entries.append(Entry.build(
                source_type="emmx",
                source_key=f"{rel}#{key_node}",
                title=title,
                locator=f"emmx://{rel}#{key_node}",
                locator_canonical=None,
                native_path=root_dir_name,
                meta={"source_type": "emmx", "mind_path": "/".join(child_path),
                      "depth": len(child_path)},
                created_at=None,
            ))
    else:
        child_path = path
    for child in list(elem):
        _walk_topics(child, child_path, rel, root_dir_name, entries, stats)


def _parse_emmx(path: Path, rel: str, root_dir_name: str,
                entries: list[Entry], stats: dict[str, Any]) -> bool:
    """解析单个 .emmx；返回 True=结构化解析成功，False=降级标题级。"""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            xml_name = next((n for n in names if n.lower().endswith("content.xml")), None)
            if xml_name is None:
                return False
            tree = ElementTree.fromstring(zf.read(xml_name))
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, OSError):
        return False
    before = len(entries)
    _walk_topics(tree, [], rel, root_dir_name, entries, stats)
    return len(entries) > before


def collect_emmx(config: Any) -> AdapterOutput:
    """按 [sources.emmx].roots 遍历 .emmx 文件，产出脑图节点条目。"""
    roots = [str(r) for r in (config.get("sources.emmx.roots") or []) if str(r).strip()]
    if not roots:
        raise AdapterError("[sources.emmx].roots 为空",
                           hint="在 config/knowatlas.toml 填写脑图文件所在目录")
    entries: list[Entry] = []
    stats: dict[str, Any] = {"files": 0, "degraded_files": 0, "nodes": 0,
                             "roots_ok": []}
    for root_str in roots:
        root = Path(root_str)
        if not root.is_dir():
            raise AdapterError(f"脑图根目录不存在：{root_str}",
                               hint="修正 config [sources.emmx].roots 中的路径")
        stats["roots_ok"].append(root.name)
        for p in sorted(root.rglob("*.emmx")):
            if p.is_symlink() or not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            stats["files"] += 1
            before = len(entries)
            structured = _parse_emmx(p, rel, root.name, entries, stats)
            if not structured:
                stats["degraded_files"] += 1
                entries.append(Entry.build(
                    source_type="emmx",
                    source_key=rel,  # 降级：文件级单条目
                    title=p.stem,
                    locator=f"emmx://{rel}#file",
                    locator_canonical=None,
                    native_path=root.name if p.parent == root
                    else "/".join([root.name, *p.parent.relative_to(root).parts]),
                    meta={"source_type": "emmx", "degraded": True,
                          "reason": "content.xml 缺失或结构无法解析（标题级降级）"},
                    created_at=datetime.fromtimestamp(p.stat().st_mtime)
                    .astimezone().isoformat(timespec="seconds"),
                ))
            del before
    return AdapterOutput(entries=entries, stats=stats)
