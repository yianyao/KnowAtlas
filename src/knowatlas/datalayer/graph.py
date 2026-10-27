"""关系图域：三视图（总览/下钻/搜索）、放射导航与反查、分类树。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..models import Entry
from ._common import _consumable


class _GraphMixin:
    def get_graph_data(self, max_entries: int = 400) -> dict[str, Any]:
        """关系图数据（结构关系 v0）：分类节点 + 条目节点。

        边的来源：条目↔分类（挂接，含 origin）。语义级关系（引用/相似度）随
        M2 正文与 M4 embedding 接入后扩展。（域名节点已废——2026-10-22 用户裁决：
        「域名也作为关联项，毫无意义」，同域关系只在 radiate/reverse 通道保留。）
        """
        entries = self._conn.execute(
            "SELECT id, title, locator FROM entries WHERE status='active'"
            + _consumable("entries") + " LIMIT ?",
            (max_entries,),
        ).fetchall()
        ecat = self._conn.execute(
            "SELECT entry_id, category_id, origin FROM entry_categories"
        ).fetchall()
        cats = {r["id"]: r["name"] for r in
                self._conn.execute("SELECT id, name FROM categories").fetchall()}

        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        seen_cids: set[str] = set()
        for e in entries:
            nodes.append({"id": f"e:{e['id']}", "name": (e["title"] or e["locator"])[:40],
                          "kind": "entry"})
        for r in ecat:
            cid = r["category_id"]
            if cid not in cats:
                continue
            if cid not in seen_cids:
                seen_cids.add(cid)
                nodes.append({"id": f"c:{cid}", "name": cats[cid], "kind": "category"})
            links.append({"source": f"e:{r['entry_id']}", "target": f"c:{cid}",
                          "kind": r["origin"]})
        return {"nodes": nodes, "links": links}

    # ---- 关系图三视图（0.2.0 第二十二批：总览 → 搜索/下钻按需子图） ----
    # 用户定调：全量力导一次渲染会拖垮——初始只显示一级大类；搜索框按关键字出
    # 相关子图；点分类节点下钻子树。全部按需加载，服务端裁剪。

    def _consumable_count(self, cat_ids: list[str]) -> int:
        """分类集合内可消费条目数（去重；消费面守卫口径，见 _consumable）。"""
        if not cat_ids:
            return 0
        ph = ",".join("?" * len(cat_ids))
        return self._conn.execute(
            "SELECT count(DISTINCT ec.entry_id) FROM entry_categories ec"
            " JOIN entries e ON e.id=ec.entry_id AND e.status='active'" + _consumable("e") +
            f" WHERE ec.category_id IN ({ph})", cat_ids).fetchone()[0]

    def _cat_descendants(self, cid: str) -> list[str]:
        """子树全 id（含自身；多父 DAG 防环）。"""
        down: dict[str, list[str]] = {}
        for r in self._conn.execute("SELECT category_id, parent_id FROM category_parents"):
            down.setdefault(r["parent_id"], []).append(r["category_id"])
        ids, stack, seen = [cid], [cid], {cid}
        while stack:
            x = stack.pop()
            for k in down.get(x, []):
                if k not in seen:
                    seen.add(k)
                    ids.append(k)
                    stack.append(k)
        return ids

    def _cat_ancestors(self, cid: str) -> list[str]:
        """祖先链 id（自父到根；多父取全部父，BFS 向上，防环）。"""
        up: dict[str, list[str]] = {}
        for r in self._conn.execute("SELECT category_id, parent_id FROM category_parents"):
            up.setdefault(r["category_id"], []).append(r["parent_id"])
        out: list[str] = []
        stack, seen = list(up.get(cid, [])), {cid}
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
            stack.extend(up.get(x, []))
        return out

    @staticmethod
    def _like_pattern(q: str) -> str:
        """LIKE 模式（转义 %/_，配 ESCAPE '\\' 使用）。"""
        return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    def get_graph_overview(self) -> dict[str, Any]:
        """大纲图：只含一级大类节点，value = 子树 active 条目数（前端按它定气泡大小）。"""
        has_parent = {r["category_id"] for r in
                      self._conn.execute("SELECT category_id FROM category_parents")}
        nodes: list[dict[str, Any]] = []
        for r in self._conn.execute("SELECT id, name FROM categories ORDER BY name"):
            if r["id"] in has_parent:
                continue
            ids = self._cat_descendants(r["id"])
            count = self._consumable_count(ids)
            if count == 0:
                continue    # 空类剪枝（第三十六批）：无可消费条目的大类不进总览
            nodes.append({"id": f"c:{r['id']}", "name": r["name"],
                          "kind": "category", "value": count})
        return {"nodes": nodes, "links": []}

    _SPARSE_FOLD = 2    # 稀疏分支折叠阈值（批次 72）：直挂 ≤2 条的子分类藏条目

    def get_graph_subtree(self, category_id: str, limit: int = 120,
                          hierarchy: bool = False, compact: bool = False,
                          layer: str = "entries", point_limit: int = 200
                          ) -> dict[str, Any] | None:
        """子树下钻图：该分类的子孙分类 + 挂接条目/点（近 limit 条）+ 祖先链上下文。

        条目节点带 locator（前端点击可打开原链接）；分类不存在返回 None。
        hierarchy=True（纯层级模式，批次 63）：只出下一级子分类（child 边，
        value=子树可消费数），不出条目/祖先链——叶子层（无未剪空子类）
        自动出本子树条目；非叶子层条目由前端「显示条目」显式拉经典视图。
        compact=True（稀疏折叠，批次 72）：直挂条目 ≤2 的子分类藏其条目与
        挂接边（分类节点带 folded=N，前端点击下钻可见），图密度下降、结构
        可读——只藏边不藏类，点击下钻信息零丢失。经典视图分类节点带 depth
        （root=0，多父取最短；祖先 ctx=-1），供前端分层铺开。
        layer="points"（P4，2026-10-26）：第三层由条目卡换成点卡——条目集照旧
        先算（含 hierarchy 叶子/compact 口径），再把挂接条目上的可消费点接成
        p:<point_id> 节点、边 p→c 标 kind="point"；超出 point_limit 的点记
        truncated.points；该范围没有可消费点时自动回退条目层（layer="entries"
        + note），新条目/未抽点范围不会空图。默认 "entries"，行为与旧版一致。
        """
        cat = self._conn.execute(
            "SELECT id, name FROM categories WHERE id=?", (category_id,)).fetchone()
        if cat is None:
            return None
        cats = {r["id"]: r["name"] for r in
                self._conn.execute("SELECT id, name FROM categories").fetchall()}
        sub_ids = self._cat_descendants(category_id)
        if hierarchy:
            kids = [(r["id"], self._consumable_count(self._cat_descendants(r["id"])))
                    for r in self._conn.execute(
                        "SELECT c.id FROM category_parents cp"
                        " JOIN categories c ON c.id=cp.category_id WHERE cp.parent_id=?"
                        " ORDER BY c.name", (category_id,)).fetchall()]
            if kids and any(n > 0 for _, n in kids):
                h_nodes: list[dict[str, Any]] = [
                    {"id": f"c:{category_id}", "name": cat["name"], "kind": "category",
                     "value": self._consumable_count(sub_ids)}]
                h_links: list[dict[str, Any]] = []
                for cid, n in kids:
                    if n == 0:    # 空类剪枝（第三十六批口径，与经典视图一致）
                        continue
                    h_nodes.append({"id": f"c:{cid}", "name": cats.get(cid, "?"),
                                    "kind": "category", "value": n})
                    h_links.append({"source": f"c:{category_id}", "target": f"c:{cid}",
                                    "kind": "child"})
                return {"root": category_id, "nodes": h_nodes, "links": h_links}
            # 叶子层（无子类或子类全空）：条目在此层出现——落经典装配但不带祖先链
        anc_ids = [] if hierarchy else \
            [a for a in self._cat_ancestors(category_id) if a not in sub_ids]
        ph = ",".join("?" * len(sub_ids))
        entries = self._conn.execute(
            "SELECT DISTINCT e.id, e.title, e.locator FROM entries e"
            f" JOIN entry_categories ec ON ec.entry_id=e.id"
            f" WHERE ec.category_id IN ({ph}) AND e.status='active'" + _consumable("e") +
            " ORDER BY e.created_at DESC LIMIT ?", (*sub_ids, limit)).fetchall()
        entry_ids = [e["id"] for e in entries]
        # 分类深度（批次 72，分层铺开原料）：root=0，多父取最短路径；不动点
        # 松弛（子树规模小，几十-几百节点，O(V·E) 可忽略）
        depth: dict[str, int] = {}
        if not hierarchy:
            depth = {category_id: 0}
            sub_set = set(sub_ids)
            parents_of: dict[str, list[str]] = {}
            for r in self._conn.execute(
                    f"SELECT category_id, parent_id FROM category_parents"
                    f" WHERE category_id IN ({ph})", sub_ids):
                if r["parent_id"] in sub_set:
                    parents_of.setdefault(r["category_id"], []).append(r["parent_id"])
            changed = True
            while changed:
                changed = False
                for cid in sub_ids:
                    cand = [depth[p] + 1 for p in parents_of.get(cid, []) if p in depth]
                    if cand and (cid not in depth or min(cand) < depth[cid]):
                        depth[cid] = min(cand)
                        changed = True
        # 稀疏折叠（批次 72）：直挂 ≤_SPARSE_FOLD 条的子分类（非根）藏条目——
        # 直挂数独立于 limit 全量统计（截断样本计数会失真）；只藏边，条目若
        # 另挂非折叠分类仍可见（边保留），孤立时节点才隐
        fold_cats: set[str] = set()
        if compact and not hierarchy:
            counts = self._conn.execute(
                "SELECT ec.category_id, COUNT(DISTINCT ec.entry_id) AS n"
                " FROM entry_categories ec"
                " JOIN entries e ON e.id=ec.entry_id AND e.status='active'" + _consumable("e") +
                f" WHERE ec.category_id IN ({ph}) AND ec.category_id != ?"
                " GROUP BY ec.category_id", (*sub_ids, category_id)).fetchall()
            fold_cats = {r["category_id"] for r in counts
                         if r["n"] <= self._SPARSE_FOLD}
        nodes: list[dict[str, Any]] = [
            {"id": f"c:{a}", "name": cats.get(a, "?"), "kind": "category",
             "ctx": True, "depth": -1}
            for a in anc_ids]
        for cid in sub_ids:
            # 空类剪枝（第三十六批）：子树内无可消费条目的子类不进下钻图；焦点根保留
            if cid != category_id and self._consumable_count(self._cat_descendants(cid)) == 0:
                continue
            node = {"id": f"c:{cid}", "name": cats.get(cid, "?"), "kind": "category"}
            if not hierarchy:
                node["depth"] = depth.get(cid, 0)
            if cid in fold_cats:
                folded = next(r["n"] for r in counts if r["category_id"] == cid)
                node["folded"] = folded    # 被藏直挂条目数（前端徽标提示）
            nodes.append(node)
        entry_nodes: list[dict[str, Any]] = []
        point_nodes: list[dict[str, Any]] = []
        point_links: list[dict[str, Any]] = []
        points_truncated = 0
        layer_used = "entries"
        if layer == "points" and entry_ids:
            point_nodes, point_links, points_truncated = self._subtree_points(
                entry_ids, sub_ids, fold_cats, max(1, point_limit))
            if point_nodes:
                layer_used = "points"
        links: list[dict[str, Any]] = []
        if layer_used == "points":
            nodes.extend(point_nodes)
            links.extend(point_links)
        else:
            for e in entries:
                entry_nodes.append({"id": f"e:{e['id']}",
                                    "name": (e["title"] or e["locator"])[:40],
                                    "kind": "entry", "locator": e["locator"]})
            nodes.extend(entry_nodes)
            if entry_ids:
                eph = ",".join("?" * len(entry_ids))
                for r in self._conn.execute(
                        f"SELECT entry_id, category_id, origin FROM entry_categories"
                        f" WHERE entry_id IN ({eph}) AND category_id IN ({ph})",
                        (*entry_ids, *sub_ids)):
                    if fold_cats and r["category_id"] in fold_cats:
                        continue    # 折叠分支的挂接边不进图
                    links.append({"source": f"e:{r['entry_id']}",
                                  "target": f"c:{r['category_id']}",
                                  "kind": r["origin"]})
            if fold_cats:
                # 折叠后孤立的条目（挂接边全被藏）节点也隐——留着是漂空噪音
                linked = {l["source"] for l in links}
                nodes = [n for n in nodes
                         if n["kind"] != "entry" or n["id"] in linked]
        out = {"root": category_id, "nodes": nodes, "links": links}
        if not hierarchy:
            out["compact"] = bool(fold_cats) or compact
        if layer == "points":
            out["layer"] = layer_used
            if points_truncated:
                out["truncated"] = {"points": points_truncated}
            if layer_used == "entries":
                out["note"] = "该范围暂无可显示的知识点，已回退条目层"
        return out

    def search_graph(self, q: str, limit: int = 80) -> dict[str, Any]:
        """搜索驱动子图：条目标题 / 分类名命中 + 各自分类链与挂接边（按需加载）。

        只带命中条目、其直挂分类与祖先链——不扩散拉全子树，保证子图小而相关。
        """
        pat = self._like_pattern(q)
        matched_entries = self._conn.execute(
            "SELECT id, title, locator FROM entries WHERE status='active'"
            + _consumable("entries") +
            " AND title LIKE ? ESCAPE '\\' ORDER BY created_at DESC LIMIT ?",
            (pat, limit)).fetchall()
        matched_cats = [r["id"] for r in self._conn.execute(
            "SELECT id FROM categories WHERE name LIKE ? ESCAPE '\\' ORDER BY name LIMIT 20",
            (pat,))]
        cats = {r["id"]: r["name"] for r in
                self._conn.execute("SELECT id, name FROM categories").fetchall()}
        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        entry_ids = [e["id"] for e in matched_entries]
        entry_nodes: list[dict[str, Any]] = []
        for e in matched_entries:
            entry_nodes.append({"id": f"e:{e['id']}", "name": (e["title"] or e["locator"])[:40],
                                "kind": "entry", "locator": e["locator"]})
        nodes.extend(entry_nodes)
        # 命中分类节点（含其祖先链，保证能看见大类归属）
        involved: set[str] = set(matched_cats)
        for cid in matched_cats:
            involved.update(self._cat_ancestors(cid))
        if entry_ids:
            eph = ",".join("?" * len(entry_ids))
            for r in self._conn.execute(
                    f"SELECT entry_id, category_id, origin FROM entry_categories"
                    f" WHERE entry_id IN ({eph})", entry_ids):
                cid = r["category_id"]
                links.append({"source": f"e:{r['entry_id']}", "target": f"c:{cid}",
                              "kind": r["origin"]})
                involved.add(cid)
                involved.update(self._cat_ancestors(cid))
        for cid in involved:
            if cid in cats:
                nodes.append({"id": f"c:{cid}", "name": cats[cid], "kind": "category"})
        return {"query": q, "nodes": nodes, "links": links}

    # ---- 放射导航（0.2.0 第三十三批：§9.4 探索导向迭代，不推翻三视图） ----
    # 纪律：没有解释的关联不展示——每个节点带 reasons[]、每条边带 reason；
    # relation_reason 全部由规则生成（共现/同源/显式关联），语义相似边留 M4 embedding。

    _RADIATE_KINDS = {"c": "category", "e": "entry", "d": "domain",
                      "p": "point"}   # P4（2026-10-26）：点成为一等节点

    def _entry_node(self, row: sqlite3.Row) -> dict[str, Any]:
        from urllib.parse import urlsplit
        host = urlsplit(row["locator"]).hostname or ""
        return {"id": f"e:{row['id']}", "name": (row["title"] or row["locator"])[:40],
                "kind": "entry", "locator": row["locator"], "host": host}

    def _entry_row(self, entry_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT id, title, locator FROM entries WHERE id=? AND status='active'"
            + _consumable("entries"),
            (entry_id,)).fetchone()

    def radiate(self, node_id: str, per_channel: int = 8) -> dict[str, Any] | None:
        """焦点一跳邻域（放射模式数据源）。

        节点 id 约定 `c:<分类id>` / `e:<条目id>` / `d:<host>` / `p:<点id>`。通道与 relation_reason：
        分类焦点 → child / attach:<origin> / parent；条目焦点 → attach:<origin> /
        same_host:<host> / thread:<线索名>；域名焦点 → host_member:<host>；
        点焦点 → attach:<origin> / same_book:<book> / same_section:<book>/<section> /
        sim:<score>（P4，2026-10-26：点成为一等节点）。
        每通道上限 per_channel，超出记 truncated[通道]=剩余数。焦点不存在返回 None。
        """
        from urllib.parse import urlsplit

        prefix, _, raw_id = node_id.partition(":")
        kind = self._RADIATE_KINDS.get(prefix)
        if kind is None or not raw_id:
            return None

        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        truncated: dict[str, int] = {}

        def add_node(nid: str, name: str, nkind: str, reason: str, **extra: Any) -> None:
            if nid == node_id:
                return
            n = nodes.setdefault(nid, {"id": nid, "name": name, "kind": nkind,
                                       "reasons": [], **extra})
            if reason and reason not in n["reasons"]:
                n["reasons"].append(reason)

        def add_edge(target: str, reason: str) -> None:
            e = edges.setdefault(target, {"source": node_id, "target": target,
                                          "reason": reason})
            if reason and reason not in e["reason"]:
                e["reason"] = f"{e['reason']}；{reason}" if e["reason"] else reason

        def cut(channel: str, total: int) -> None:
            if total > per_channel:
                truncated[channel] = total - per_channel

        if kind == "category":
            cat = self._conn.execute(
                "SELECT id, name FROM categories WHERE id=?", (raw_id,)).fetchone()
            if cat is None:
                return None
            focus = {"id": node_id, "name": cat["name"], "kind": "category"}
            # child：子分类（空类剪枝：子树内无可消费条目的子类不出）
            children = self._conn.execute(
                "SELECT c.id, c.name FROM category_parents cp"
                " JOIN categories c ON c.id=cp.category_id WHERE cp.parent_id=?"
                " ORDER BY c.name", (raw_id,)).fetchall()
            children = [r for r in children
                        if self._consumable_count(self._cat_descendants(r["id"])) > 0]
            for r in children[:per_channel]:
                add_node(f"c:{r['id']}", r["name"], "category", "child")
                # child 必须落边：只加节点会让子分类在力导向图里成孤立点
                # （漂在画布中央冒充主要内容，tooltip 也无从解释）——第四十八批
                add_edge(f"c:{r['id']}", "child")
            cut("child", len(children))
            # attach:<origin>：挂接条目（带 locator，前端可打开）
            atts = self._conn.execute(
                "SELECT e.id, e.title, e.locator, ec.origin FROM entry_categories ec"
                " JOIN entries e ON e.id=ec.entry_id AND e.status='active'"
                + _consumable("e") +
                " WHERE ec.category_id=? ORDER BY e.created_at DESC", (raw_id,)).fetchall()
            for r in atts[:per_channel]:
                add_node(f"e:{r['id']}", (r["title"] or r["locator"])[:40], "entry",
                         f"attach:{r['origin']}", locator=r["locator"])
                add_edge(f"e:{r['id']}", f"attach:{r['origin']}")
            cut("attach", len(atts))
            # parent：父分类
            parents = self._conn.execute(
                "SELECT c.id, c.name FROM category_parents cp"
                " JOIN categories c ON c.id=cp.parent_id WHERE cp.category_id=?"
                " ORDER BY c.name", (raw_id,)).fetchall()
            for r in parents[:per_channel]:
                add_node(f"c:{r['id']}", r["name"], "category", "parent")
                add_edge(f"c:{r['id']}", "parent")
            cut("parent", len(parents))
        elif kind == "entry":
            row = self._entry_row(raw_id)
            if row is None:
                return None
            focus = {"id": node_id, "name": (row["title"] or row["locator"])[:40],
                     "kind": "entry", "locator": row["locator"]}
            # attach:<origin>：直挂分类（带派生 path）
            atts = self._conn.execute(
                "SELECT ec.category_id, ec.origin FROM entry_categories ec"
                " WHERE ec.entry_id=?", (raw_id,)).fetchall()
            for r in atts[:per_channel]:
                paths = self.get_category_paths(r["category_id"])
                cname_row = self._conn.execute(
                    "SELECT name FROM categories WHERE id=?",
                    (r["category_id"],)).fetchone()
                add_node(f"c:{r['category_id']}", cname_row["name"] if cname_row else "?",
                         "category", f"attach:{r['origin']}", path=paths[0] if paths else "")
                add_edge(f"c:{r['category_id']}", f"attach:{r['origin']}")
            cut("attach", len(atts))
            # same_host:<host>
            host = urlsplit(row["locator"]).hostname or ""
            if host:
                peers = self.entries_by_host(host, limit=per_channel + 1)
                total = len([p for p in peers if p.id != raw_id])
                for p in [x for x in peers if x.id != raw_id][:per_channel]:
                    add_node(f"e:{p.id}", (p.title or p.locator)[:40], "entry",
                             f"same_host:{host}", locator=p.locator)
                    add_edge(f"e:{p.id}", f"same_host:{host}")
                cut("same_host", total)
            # thread:<线索名>：与串联工作区双向打通
            seen_thread_entries: set[str] = set()
            thread_total = 0
            for t in self.threads_for_entry(raw_id):
                full = self.get_thread(t["id"])
                if full is None:
                    continue
                members = [it for it in full.items if it.entry_id != raw_id]
                thread_total += len(members)
                for it in members[:per_channel]:
                    er = self._entry_row(it.entry_id)
                    if er is None or it.entry_id in seen_thread_entries:
                        continue
                    seen_thread_entries.add(it.entry_id)
                    add_node(f"e:{it.entry_id}", (er["title"] or er["locator"])[:40],
                             "entry", f"thread:{t['name']}", locator=er["locator"])
                    add_edge(f"e:{it.entry_id}", f"thread:{t['name']}")
            cut("thread", thread_total)
            # sim:<score>：语义相似边（迁移 006 向量邻域，第五十六批——db.py:844 挂账收口）。
            # 焦点条目有向量时取库内 top 邻域；无向量/无向量库则通道整体不出现（降级纪律）。
            self._sim_channel(raw_id, add_node, add_edge, cut, per_channel)
        elif kind == "point":
            # P4 点级图（2026-10-26）：点焦点一跳邻域，四类边——
            # attach（溯源条目→分类）、same_book、same_section、sim（点向量）；
            # 「引用/指涉」最贵，按 TODO 后置。每条边都带 reason，导航天条纪律不变。
            row = self._point_row(raw_id)
            if row is None:
                return None
            book, section = self._point_book_section(row["meta"])
            srcs = self._point_sources(raw_id, limit=6)
            focus = {
                "id": node_id,
                "name": self._point_label(row["summary"], row["text"]),
                "kind": "point",
                "text": row["text"],
                "path": self._point_path(row["meta"], srcs),
                "sources": srcs,
            }
            # attach:<origin>：点的溯源条目所在分类（按分类去重，origin 取首次出现）
            seen_cats: dict[str, str] = {}
            for s in srcs:
                for r in self._conn.execute(
                        "SELECT category_id, origin FROM entry_categories"
                        " WHERE entry_id=?", (s["entry_id"],)).fetchall():
                    seen_cats.setdefault(r["category_id"], r["origin"])
            for cid, origin in list(seen_cats.items())[:per_channel]:
                paths = self.get_category_paths(cid)
                crow = self._conn.execute(
                    "SELECT name FROM categories WHERE id=?", (cid,)).fetchone()
                add_node(f"c:{cid}", crow["name"] if crow else "?", "category",
                         f"attach:{origin}", path=paths[0] if paths else "")
                add_edge(f"c:{cid}", f"attach:{origin}")
            cut("attach", len(seen_cats))
            # same_book / same_section：kpe 产物自带 book + section_path；
            # section_path == book（整本一块）时不出章节通道，避免与同书重复。
            if book:
                total, peers = self._point_peers(book, "", raw_id, per_channel)
                for r in peers:
                    add_node(f"p:{r['id']}", self._point_label(r["summary"], r["text"]),
                             "point", f"same_book:{book}", text=r["text"],
                             path=self._point_path(r["meta"], []))
                    add_edge(f"p:{r['id']}", f"same_book:{book}")
                cut("same_book", total)
                if section and section != book:
                    total2, peers2 = self._point_peers(book, section, raw_id,
                                                       per_channel)
                    for r in peers2:
                        add_node(f"p:{r['id']}",
                                 self._point_label(r["summary"], r["text"]),
                                 "point", f"same_section:{book}/{section}",
                                 text=r["text"], path=self._point_path(r["meta"], []))
                        add_edge(f"p:{r['id']}", f"same_section:{book}/{section}")
                    cut("same_section", total2)
            # sim:<score>：点向量 top 邻域（无向量时整条通道缺席）
            self._point_sim_channel(raw_id, add_node, add_edge, cut, per_channel)
        else:  # domain
            host = raw_id.strip().lower()
            members = self.entries_by_host(host, limit=per_channel + 1)
            focus = {"id": node_id, "name": host, "kind": "domain"}
            for p in members[:per_channel]:
                add_node(f"e:{p.id}", (p.title or p.locator)[:40], "entry",
                         f"host_member:{host}", locator=p.locator)
                add_edge(f"e:{p.id}", f"host_member:{host}")
            cut("host_member", len(members))

        return {"focus": focus, "nodes": list(nodes.values()),
                "edges": list(edges.values()), "truncated": truncated}

    def reverse_reach(self, node_id: str, limit: int = 20) -> dict[str, Any] | None:
        """双向反查：哪些焦点能到达该节点。

        条目焦点 → 直挂分类（带 path）+ 同域名 + 同线索（kind=thread，带 thread.html url）；
        分类焦点 → 父分类 + 挂接条目 Top-N；点焦点 → 溯源条目（source:point，带 locator）
        + 这些条目挂的分类（attach:<origin>，P4 后置项，工单 变更工单-2026-10-26-P4点级反查.md）；
        域名节点不支持反查（返回 None）。
        """
        prefix, _, raw_id = node_id.partition(":")
        kind = self._RADIATE_KINDS.get(prefix)
        if kind is None or not raw_id or kind == "domain":
            return None

        items: list[dict[str, Any]] = []
        if kind == "entry":
            row = self._entry_row(raw_id)
            if row is None:
                return None
            for r in self._conn.execute(
                    "SELECT category_id, origin FROM entry_categories WHERE entry_id=?",
                    (raw_id,)).fetchall():
                paths = self.get_category_paths(r["category_id"])
                cname_row = self._conn.execute(
                    "SELECT name FROM categories WHERE id=?", (r["category_id"],)).fetchone()
                items.append({"kind": "category", "id": f"c:{r['category_id']}",
                              "name": cname_row["name"] if cname_row else "?",
                              "path": paths[0] if paths else "",
                              "reason": f"attach:{r['origin']}"})
            from urllib.parse import urlsplit
            host = urlsplit(row["locator"]).hostname or ""
            if host:
                items.append({"kind": "domain", "id": f"d:{host}", "name": host,
                              "reason": f"same_host:{host}"})
            for t in self.threads_for_entry(raw_id):
                items.append({"kind": "thread", "id": t["id"], "name": t["name"],
                              "url": f"/thread.html?id={t['id']}",
                              "reason": f"thread:{t['name']}"})
        elif kind == "point":
            point_items = self._point_reverse_items(raw_id, limit)
            if point_items is None:
                return None
            items = point_items
        else:  # category
            cat = self._conn.execute(
                "SELECT id, name FROM categories WHERE id=?", (raw_id,)).fetchone()
            if cat is None:
                return None
            parents = self._conn.execute(
                "SELECT c.id, c.name FROM category_parents cp"
                " JOIN categories c ON c.id=cp.parent_id WHERE cp.category_id=?"
                " ORDER BY c.name", (raw_id,)).fetchall()
            for r in parents:
                paths = self.get_category_paths(r["id"])
                items.append({"kind": "category", "id": f"c:{r['id']}", "name": r["name"],
                              "path": paths[0] if paths else "", "reason": "parent"})
            atts = self._conn.execute(
                "SELECT e.id, e.title, e.locator, ec.origin FROM entry_categories ec"
                " JOIN entries e ON e.id=ec.entry_id AND e.status='active'"
                + _consumable("e") +
                " WHERE ec.category_id=? ORDER BY e.created_at DESC LIMIT ?",
                (raw_id, limit)).fetchall()
            for r in atts:
                items.append({"kind": "entry", "id": f"e:{r['id']}",
                              "name": (r["title"] or r["locator"])[:40],
                              "reason": f"attach:{r['origin']}"})
        return {"focus": {"id": node_id, "kind": kind}, "items": items[:limit]}

    def get_tree(self) -> list[dict[str, Any]]:
        """返回多父 DAG 展平的树（按根展开；多父节点会在每个父下出现）。

        每个节点带 count = 该子树（含自身、含多父重复出现）的 active 条目数——
        供 UI 默认隐藏空枝：分类节点本身不删（可能只是条目被舍弃/归档后清空），
        但不再占视线；用户勾选「显示空分类」后可见。
        """
        cats = {r["id"]: dict(r) for r in
                self._conn.execute("SELECT * FROM categories").fetchall()}
        children: dict[str | None, list[str]] = {}
        has_parent: set[str] = set()
        for r in self._conn.execute("SELECT category_id, parent_id FROM category_parents"):
            children.setdefault(r["parent_id"], []).append(r["category_id"])
            has_parent.add(r["category_id"])
        paths = dict(self._all_paths())
        first_path: dict[str, str] = {}
        for cid, p in paths.items():
            first_path.setdefault(cid, p)

        # active 直挂映射（一次查询拿全，Python 侧自底向上聚合子树数）
        own: dict[str, set[str]] = {}
        for r in self._conn.execute(
                "SELECT ec.category_id, ec.entry_id FROM entry_categories ec"
                " JOIN entries e ON e.id=ec.entry_id WHERE e.status='active'"):
            own.setdefault(r["category_id"], set()).add(r["entry_id"])
        memo: dict[str, set[str]] = {}

        def subtree_entries(cid: str) -> set[str]:
            if cid in memo:
                return memo[cid]
            memo[cid] = set()  # 防环占位（多父 DAG 无环时可被后续覆盖）
            acc = set(own.get(cid, ()))
            for k in children.get(cid, []):
                acc |= subtree_entries(k)
            memo[cid] = acc
            return acc

        def build(cid: str) -> dict[str, Any]:
            c = cats[cid]
            return {
                "id": cid, "name": c["name"], "origin": c["origin"],
                "path": first_path.get(cid, c["name"]),
                "count": len(subtree_entries(cid)),
                "children": [build(k) for k in sorted(children.get(cid, []))],
            }

        roots = sorted(cid for cid in cats if cid not in has_parent)
        return [build(cid) for cid in roots]

    def subtree_category_ids(self, category_id: str) -> set[str]:
        """分类子树（含自身）的全部 id——自父链向下收集，多父去重。"""
        result = {category_id}
        down: dict[str, list[str]] = {}
        for r in self._conn.execute("SELECT category_id, parent_id FROM category_parents"):
            down.setdefault(r["parent_id"], []).append(r["category_id"])
        stack = [category_id]
        while stack:
            cur = stack.pop()
            for child in down.get(cur, []):
                if child not in result:
                    result.add(child)
                    stack.append(child)
        return result

    def get_entries_for_categories(self, category_ids: set[str], *,
                                   source_type: str | None = None,
                                   status: str = "active",
                                   limit: int = 200) -> list[Entry]:
        if not category_ids:
            return []
        marks = ",".join("?" for _ in category_ids)
        sql = (
            "SELECT DISTINCT e.* FROM entries e"
            f" JOIN entry_categories ec ON ec.entry_id = e.id"
            f" WHERE ec.category_id IN ({marks}) AND e.status=?" + _consumable("e")
        )
        params: list[Any] = [*category_ids, status]
        if source_type:
            sql += " AND e.source_type=?"
            params.append(source_type)
        sql += " ORDER BY e.exported_at DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_entry(r) for r in self._conn.execute(sql, params).fetchall()]

    def _sim_channel(self, entry_id: str, add_node, add_edge, cut,
                     per_channel: int) -> int:
        """radiate 条目焦点的 sim 通道：库内向量 top 邻域（阈值 0.5，纯标准库余弦）。

        数学在 semantic/embed.py（array 解码 + 点积；入库已归一化 → 余弦=点积）。
        本方法只在 db 层做数据搬运，避免 db → semantic 反向依赖：就地实现轻量解码。
        返回候选总数（供 cut 截断计数）。
        """
        import array as _array
        import math as _math

        focal = self.get_vector(entry_id)
        if focal is None:
            return 0
        fa = _array.array("f")
        fa.frombytes(focal["vector"])
        dim = focal["dim"]
        # 入库已归一化 → 余弦=点积；防脏数据按范数兜底
        fnorm = _math.sqrt(sum(x * x for x in fa)) or 1.0
        cands = self.all_vectors()
        scored: list[tuple[str, float]] = []
        for eid, blob in cands.items():
            if eid == entry_id:
                continue
            va = _array.array("f")
            va.frombytes(blob)
            if len(va) != dim:
                continue  # 换型残留的异维向量跳过（不报错，--embed-force 重算）
            vnorm = _math.sqrt(sum(x * x for x in va)) or 1.0
            dot = sum(x * y for x, y in zip(fa, va))
            scored.append((eid, dot / (fnorm * vnorm)))
        scored = [(eid, s) for eid, s in scored if s >= 0.5]
        scored.sort(key=lambda x: -x[1])
        for eid, score in scored[:per_channel]:
            er = self._entry_row(eid)
            if er is None:
                continue  # _entry_row 已滤 archived/不可消费条目
            add_node(f"e:{eid}", (er["title"] or er["locator"])[:40], "entry",
                     f"sim:{score:.2f}", locator=er["locator"])
            add_edge(f"e:{eid}", f"sim:{score:.2f}")
        cut("sim", len(scored))
        return len(scored)

    def _subtree_points(self, entry_ids: list[str], sub_ids: list[str],
                        fold_cats: set[str], point_limit: int
                        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        """子树第三层的点节点 + 点→分类边（P4，2026-10-26）。

        口径：只出可消费点（非 stale、非 dupe 副点、溯源条目 active+可消费），
        并按 `point_limit` 截断（created_at DESC，返回剩余数）；折叠分类
        （compact）下的挂接不计边——点若还挂非折叠分类仍可见。
        返回 (nodes, links, truncated)。
        """
        if not entry_ids or not sub_ids:
            return [], [], 0
        eph = ",".join("?" * len(entry_ids))
        cph = ",".join("?" * len(sub_ids))
        rows = self._conn.execute(
            "SELECT ps.point_id AS pid, ec.category_id AS cid,"
            " p.summary AS summary, substr(p.text,1,300) AS text, p.meta AS meta,"
            " e.id AS entry_id,"
            " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS entry_title,"
            " e.locator AS locator"
            " FROM point_sources ps"
            " JOIN points p ON p.id=ps.point_id"
            " JOIN entries e ON e.id=ps.entry_id AND e.status='active'"
            " JOIN entry_categories ec ON ec.entry_id=ps.entry_id"
            f" WHERE ps.entry_id IN ({eph}) AND ec.category_id IN ({cph})"
            "   AND p.aging_flag != 'stale'"
            "   AND COALESCE(json_extract(p.meta,'$.dupe_of'),'')=''"
            + _consumable("e") +
            " ORDER BY p.created_at DESC", (*entry_ids, *sub_ids)).fetchall()
        points: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for r in rows:
            if fold_cats and r["cid"] in fold_cats:
                continue    # 折叠分支的挂接边不进图（点层同口径）
            p = points.get(r["pid"])
            if p is None:
                p = points[r["pid"]] = {
                    "id": f"p:{r['pid']}",
                    "name": self._point_label(r["summary"], r["text"]),
                    "kind": "point",
                    "text": r["text"],
                    "path": self._point_path(r["meta"], []),
                    "sources": [],
                    "cats": set(),
                }
                order.append(r["pid"])
            p["cats"].add(r["cid"])
            if (len(p["sources"]) < 2
                    and r["entry_id"] not in {s["entry_id"] for s in p["sources"]}):
                p["sources"].append({"entry_id": r["entry_id"],
                                     "title": r["entry_title"],
                                     "locator": r["locator"]})
        total = len(order)
        kept = order[:max(1, point_limit)]
        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        for pid in kept:
            p = points[pid]
            cats = sorted(p.pop("cats"))
            if not p["path"] and p["sources"]:
                p["path"] = "溯源：" + "、".join(
                    str(s["title"] or "") for s in p["sources"])
            nodes.append(p)
            for cid in cats:
                links.append({"source": p["id"], "target": f"c:{cid}",
                              "kind": "point"})
        return nodes, links, max(0, total - len(kept))

