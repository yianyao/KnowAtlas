"""老化域闸门：社科/人文类知识不参与自动老化（工单 2026-10-27 裁决 ④）。

用户原话（2026-10-27 22:30）：「老化应针对**非社科类**知识且自动，其一……其二老化
某个知识点不会影响同源（同一文件）的其他知识点」。

为什么要第二层闸门：老化的既有闸门是 `kind=hard`（可判定硬事实），但人文内容里也有
硬事实（真库 `文学创作` 下有 3 个 hard 点）——「技术过时」对文学/历史/哲学没有意义，
按分类再挡一道，宁漏勿误。

口径（确定性、零 LLM；只读库）：
- 点 → 溯源条目 → 条目直挂分类 → 逐级上溯到**一级分类名**；
- 一级分类名（含 `startswith` 前缀，兼容「文学创作与评论」这类变体）命中
  `[aging] exclude_categories` → 不判；
- **黑名单语义**：没有分类的点不因此被挡（仍由 `kind=hard` 闸门把关）——只有
  「明确属于社科/人文类」才排除，不为未知领域做假设。

点级隔离是**既有事实**（`DataLayer.set_point_aging` 只 `UPDATE ... WHERE id=?`，
条目状态不被改写、同源其他点的 `aging_flag` 不受影响）；本模块只负责「谁能进候选」，
隔离由 `tests/test_aging_isolation.py` 钉死。
"""

from __future__ import annotations

from typing import Any, Iterable


def _top_names(dl: Any) -> dict[str, set[str]]:
    """分类 id → 一级分类名集合（DAG：可能有多个根，全收）。"""
    cats = {c["id"]: c for c in dl.all_categories_dag()}
    memo: dict[str, set[str]] = {}

    def roots(cid: str, seen: frozenset[str] = frozenset()) -> set[str]:
        if cid in memo:
            return memo[cid]
        if cid in seen or cid not in cats:
            return set()
        parents = cats[cid].get("parents") or []
        if not parents:
            out = {str(cats[cid].get("name") or "")}
        else:
            out = set()
            for p in parents:
                out |= roots(p, seen | {cid})
        memo[cid] = {n for n in out if n}
        return memo[cid]

    for cid in cats:
        roots(cid)
    return memo


def point_domains(dl: Any, point_ids: Iterable[str]) -> dict[str, set[str]]:
    """点 → 一级分类名集合（无溯源/无分类 → 空集）。"""
    ids = [p for p in point_ids if p]
    src = dl.point_source_map(ids) if ids else {}
    entry_cats = dl.all_entry_categories()
    top = _top_names(dl)
    out: dict[str, set[str]] = {}
    for pid in ids:
        names: set[str] = set()
        for eid in src.get(pid, []):
            for cid in entry_cats.get(eid, []):
                names |= top.get(cid, set())
        out[pid] = names
    return out


def _hit(name: str, exclude: tuple[str, ...]) -> bool:
    return any(name == ex or name.startswith(ex) for ex in exclude)


def eligible_points(dl: Any, point_ids: Iterable[str],
                    exclude: tuple[str, ...]) -> dict[str, bool]:
    """点是否允许自动老化：其一级分类一个都不在黑名单里（无分类 → 允许）。"""
    if not exclude:
        return {pid: True for pid in point_ids if pid}
    domains = point_domains(dl, point_ids)
    return {pid: not any(_hit(n, exclude) for n in names)
            for pid, names in domains.items()}


__all__ = ["eligible_points", "point_domains"]