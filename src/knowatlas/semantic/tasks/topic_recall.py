"""topic_recall：多路召回聚合（完整方案 §9.4，0.2.0 第三十二批）。

定位：用户「知道要什么，但知识散落多个源多个条目」——输入一个主题词（或节点 id），
把跨源相关条目聚合到一起，**每条都带 relation_reason**（没有解释的关联不展示，§9.4 纪律）。

四路召回（全部纯规则、零费用；语义相似通道按 §9.4 为可选项，留待 M4 embedding）：
1. `fts`                  —— FTS5/LIKE 命中主题词（种子）
2. `cocategory:<路径>`     —— 与种子同分类路径共现的条目
3. `same_host:<host>`      —— 与种子同站点的条目（http(s) locator）
4. `thread:<线索名>`        —— 与种子同处一个用户线索的条目（显式关联）

输入解析（完整方案 §9.4「输入主题/节点 id」）：
- `c:<分类id>` —— 焦点分类：其子树条目为种子（reason=focus_category:<路径>）
- `e:<条目id>` —— 焦点条目：该条目为种子（reason=focus_entry）
- 其他         —— 主题词：走 FTS 种子（reason=fts）

签名说明（对 §4.3 SemanticProcessor 批处理签名的 documented exception）：
召回型任务是查询驱动而非逐条加工，输入是 query 字符串、输出是聚合 dict；
能力描述以 CapabilitySpec 的 input/output contract 为准（canary 覆盖 name@version）。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ...registry.capability import CapabilitySpec
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="topic_recall",
    input_contract={"query": "主题词；或节点 id（c:<分类id> / e:<条目id>）"},
    output_contract={
        "hits": "list[dict]（entry_id/title/locator/source_type/channels/is_seed）",
        "groups": "按 source_type 的分组计数",
        "resolved_as": "topic | category | entry | empty",
    },
    version="1.0.0",
    description="多路召回：FTS 命中 + 同分类共现 + 同 host 聚类 + 同线索显式关联，每条带 relation_reason（纯规则零费用）",
)

_PER_CATEGORY = 30   # 单个分类共现通道的取样上限
_PER_HOST = 30       # 单个 host 聚类通道的取样上限


def _host_of(locator: str) -> str:
    if not locator.startswith(("http://", "https://")):
        return ""
    try:
        return (urlsplit(locator).hostname or "").lower()
    except ValueError:
        return ""  # 非 ASCII 全角字符等非法 netloc——放弃该通道，不丢条目


def _resolve_seeds(dl: Any, q: str, limit: int) -> tuple[list[str], str, str]:
    """返回 (种子 entry_id 列表, 种子 reason, resolved_as)。"""
    if q.startswith("c:"):
        cat = dl.get_category(q[2:].strip())
        if cat is None:
            return [], "", "empty"
        entries = dl.get_entries_for_categories(
            dl.subtree_category_ids(cat.id), limit=limit)
        return [e.id for e in entries], f"focus_category:{cat.path}", "category"
    if q.startswith("e:"):
        entry = dl.get_entry(q[2:].strip())
        if entry is None or entry.status != "active":
            return [], "", "empty"
        return [entry.id], "focus_entry", "entry"
    hits = dl.search_fts(q, limit=limit)
    return [h.entry_id for h in hits], "fts", "topic"


def recall(query: str, ctx: TaskContext, limit: int = 60) -> dict[str, Any]:
    """多路召回主入口（Web API / 未来 UI 共用）。"""
    q = (query or "").strip()
    empty = {"query": q, "hits": [], "groups": {}, "resolved_as": "empty", "seeds": 0}
    dl = ctx.datalayer
    if dl is None or not q:
        return empty

    seed_ids, seed_reason, resolved_as = _resolve_seeds(dl, q, limit)
    if not seed_ids:
        return empty

    channels: dict[str, list[str]] = {}  # entry_id -> relation_reason 列表（保序去重）

    def add(entry_id: str, reason: str) -> None:
        reasons = channels.setdefault(entry_id, [])
        if reason not in reasons:
            reasons.append(reason)

    for sid in seed_ids:
        add(sid, seed_reason)

    # 通道 2：同分类路径共现
    for sid in seed_ids:
        for link in dl.get_entry_categories(sid):
            peers = dl.get_entries_for_categories({link["category_id"]},
                                                  limit=_PER_CATEGORY)
            for p in peers:
                if p.id != sid:
                    add(p.id, f"cocategory:{link['path'] or link['name']}")

    # 通道 3：同 host 聚类（只对 http(s) 种子；按 host 汇总后一次查询）
    hosts: dict[str, None] = {}
    for sid in seed_ids:
        seed_entry = dl.get_entry(sid)
        host = _host_of(seed_entry.locator) if seed_entry else ""
        if host:
            hosts.setdefault(host, None)
    for host in hosts:
        for p in dl.entries_by_host(host, limit=_PER_HOST):
            add(p.id, f"same_host:{host}")

    # 通道 4：同线索显式关联（用户自己串过的路径 = 最强显式信号）。
    # 不加种子豁免——种子也展示该通道（与 cocategory/same_host 对种子的口径一致：
    # 每条结果列出全部生效的关联解释，种子另有 seed_reason 在最前）。
    thread_names: dict[str, str] = {}
    for sid in seed_ids:
        for t in dl.threads_for_entry(sid):
            thread_names[t["id"]] = t["name"]
    for tid, tname in thread_names.items():
        full = dl.get_thread(tid)
        if full is None:
            continue
        for item in full.items:
            add(item.entry_id, f"thread:{tname}")

    # 汇总：只保留 active 条目，种子优先、多通道次之
    entries = {e.id: e for e in dl.get_entries_by_ids(list(channels))}
    hits: list[dict[str, Any]] = []
    for eid, reasons in channels.items():
        e = entries.get(eid)
        if e is None or e.status != "active":
            continue
        hits.append({
            "entry_id": eid,
            "title": e.title,
            "locator": e.locator,
            "source_type": e.source_type,
            "channels": reasons,
            "is_seed": eid in set(seed_ids),
        })
    hits.sort(key=lambda h: (not h["is_seed"], -len(h["channels"]), h["title"]))
    hits = hits[:limit]

    groups: dict[str, int] = {}
    for h in hits:
        groups[h["source_type"]] = groups.get(h["source_type"], 0) + 1
    return {"query": q, "hits": hits, "groups": groups,
            "resolved_as": resolved_as, "seeds": len(seed_ids)}


def run(query: str, ctx: TaskContext, limit: int = 60) -> dict[str, Any]:
    """注册表入口（签名例外见模块 docstring）。"""
    return recall(query, ctx, limit=limit)
