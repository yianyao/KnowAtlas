"""视图聚合域：词云（scoped cloud）与时间线（scoped timeline + 陈旧分支提醒）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import Entry
from ._common import _consumable


class _ViewsMixin:
    def cloud_data(self, category_id: str | None, *,
                   sample: int = 800) -> dict[str, Any]:
        """词云聚合数据源：focus 子树（None=全库）的分类词元 + 内容词元样本。

        返回：
        - focus: {id, name} | None（None=全库）；
        - categories: focus 的直接子分类及可消费条目数（focus=None 时顶层大类；
          空类剪枝——无可消费条目的不出）——「分类词元」，点击进入子分类；
        - entries: [(entry_id, title, body, top_cat_id)] 样本（子树内可消费
          条目 DISTINCT 近 sample 条；top_cat_id=直挂分类的顶层根，多父多根
          取最小 id 保确定性——显示口径非事实口径）。

        词元提取（jieba tf-idf）在 api 层做：SQL 与 NLP 分治，jieba 惰性导入。
        消费面口径与 _consumable 一致（不判 dead/value_flag/dedupe/freshness）。
        """
        if category_id:
            sub_ids = self._cat_descendants(category_id)
            if category_id not in sub_ids:
                return {"focus": None, "categories": [], "entries": []}
        else:
            sub_ids = [r["id"] for r in self._conn.execute("SELECT id FROM categories")]
        if not sub_ids:
            # 键名必须与正常路径一致（/api/cloud 读 categories，批次 60 发现空库 500）
            return {"focus": None, "categories": [], "entries": []}
        # 分类词元：focus 直接子分类（focus=None 时顶层）
        if category_id:
            kids = self._conn.execute(
                "SELECT c.id, c.name FROM category_parents cp"
                " JOIN categories c ON c.id=cp.category_id WHERE cp.parent_id=?"
                " ORDER BY c.name", (category_id,)).fetchall()
        else:
            kids = self._conn.execute(
                "SELECT id, name FROM categories"
                " WHERE id NOT IN (SELECT category_id FROM category_parents)"
                " ORDER BY name").fetchall()
        children = [{"id": r["id"], "name": r["name"],
                     "count": self._consumable_count(self._cat_descendants(r["id"]))}
                    for r in kids]
        children = [c for c in children if c["count"] > 0]
        # 内容词元样本：子树内可消费条目（去重，近 sample 条）
        marks = ",".join("?" * len(sub_ids))
        rows = self._conn.execute(
            "SELECT DISTINCT e.id, e.title, COALESCE(e.inline_content,'') AS body"
            " FROM entries e JOIN entry_categories ec ON ec.entry_id=e.id"
            f" WHERE ec.category_id IN ({marks}) AND e.status='active'"
            + _consumable("e") + " ORDER BY e.exported_at DESC LIMIT ?",
            (*sub_ids, sample)).fetchall()
        has_parent = {r["category_id"]
                      for r in self._conn.execute("SELECT category_id FROM category_parents")}
        entries: list[tuple[str, str, str, str | None]] = []
        for r in rows:
            cats = [x["category_id"] for x in self._conn.execute(
                "SELECT category_id FROM entry_categories WHERE entry_id=?", (r["id"],))]
            roots = []
            for cid in cats:
                anc = self._cat_ancestors(cid)
                roots.extend([a for a in anc if a not in has_parent] or ([cid] if cid not in has_parent else []))
            entries.append((r["id"], r["title"], r["body"],
                            min(roots) if roots else None))
        focus = None
        if category_id:
            frow = self._conn.execute("SELECT id, name FROM categories WHERE id=?",
                                      (category_id,)).fetchone()
            if frow is not None:
                focus = {"id": frow["id"], "name": frow["name"]}
        return {"focus": focus, "categories": children, "entries": entries}

    def cloud_point_data(self, category_id: str | None, *,
                         sample: int = 800) -> list[tuple[str, str | None]]:
        """词云点词元样本（批次 89，词云点化：点层是知识主体后词云反映知识分布）。

        focus 子树内可消费条目（_consumable 同口径）的**非 stale 点**；
        返回 [(point_text, top_cat_id)]（top 口径与 cloud_data.entries 同——
        溯源条目直挂分类的顶层根，多根取最小 id；一点多溯源取第一条）。
        """
        if category_id:
            sub_ids = self._cat_descendants(category_id)
            if category_id not in sub_ids:
                return []
        else:
            sub_ids = [r["id"] for r in self._conn.execute("SELECT id FROM categories")]
        if not sub_ids:
            return []
        marks = ",".join("?" * len(sub_ids))
        rows = self._conn.execute(
            "SELECT DISTINCT p.id, p.text,"
            " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS title,"
            " e.id AS entry_id"
            " FROM points p"
            " JOIN point_sources ps ON ps.point_id = p.id"
            " JOIN entries e ON e.id = ps.entry_id AND e.status='active'"
            " JOIN entry_categories ec ON ec.entry_id = e.id"
            f" WHERE ec.category_id IN ({marks}) AND e.status='active'"
            "   AND p.aging_flag != 'stale'"      # 点级老化退出消费面（批次 93）
            "   AND COALESCE(json_extract(p.meta,'$.dupe_of'),'')=''"  # 语义去重副点（批次 94）
            + _consumable("e") +
            " ORDER BY ps.created_at DESC LIMIT ?",
            (*sub_ids, sample)).fetchall()
        has_parent = {r["category_id"]
                      for r in self._conn.execute("SELECT category_id FROM category_parents")}
        out: list[tuple[str, str | None]] = []
        for r in rows:
            cats = [x["category_id"] for x in self._conn.execute(
                "SELECT category_id FROM entry_categories WHERE entry_id=?",
                (r["entry_id"],))]
            roots = []
            for cid in cats:
                anc = self._cat_ancestors(cid)
                roots.extend([a for a in anc if a not in has_parent]
                             or ([cid] if cid not in has_parent else []))
            out.append((r["text"], min(roots) if roots else None))
        return out

    def cloud_facet_points(self, category_id: str | None, word: str,
                           limit: int = 30) -> list[dict[str, Any]]:
        """词云点 facet（批次 89）：子树内非 stale 点 text 含该词 → 点卡列表
        （词云点词元点击出知识点而非条目——裁决 #13 检索漏斗同构）。"""
        if category_id:
            sub_ids = self._cat_descendants(category_id)
            if category_id not in sub_ids:
                return []
        else:
            sub_ids = [r["id"] for r in self._conn.execute("SELECT id FROM categories")]
        if not sub_ids:
            return []
        marks = ",".join("?" * len(sub_ids))
        like = f"%{self._escape_like(word)}%"
        rows = self._conn.execute(
            "SELECT DISTINCT p.id AS point_id, substr(p.text,1,200) AS text, p.summary,"
            " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS title,"
            " e.id AS entry_id, e.locator"
            " FROM points p"
            " JOIN point_sources ps ON ps.point_id = p.id"
            " JOIN entries e ON e.id = ps.entry_id AND e.status='active'"
            " JOIN entry_categories ec ON ec.entry_id = e.id"
            f" WHERE ec.category_id IN ({marks}) AND e.status='active'"
            "   AND p.aging_flag != 'stale'"
            "   AND COALESCE(json_extract(p.meta,'$.dupe_of'),'')=''"  # 语义去重副点（批次 94）
            + _consumable("e") +
            "   AND (p.text LIKE ? ESCAPE '\\' OR p.summary LIKE ? ESCAPE '\\')"
            " ORDER BY p.created_at LIMIT ?",
            (*sub_ids, like, like, limit)).fetchall()
        return [dict(r) for r in rows]

    def cloud_facet(self, category_id: str | None, word: str,
                    limit: int = 50) -> list[Entry]:
        """词云 facet：focus 子树内可消费且标题/内联正文含该词的条目
        （内容词元点击 = facet 过滤当前范围；第四十三批）。"""
        if category_id:
            sub_ids = self._cat_descendants(category_id)
            if category_id not in sub_ids:
                return []
        else:
            sub_ids = [r["id"] for r in self._conn.execute("SELECT id FROM categories")]
        if not sub_ids:
            return []
        marks = ",".join("?" * len(sub_ids))
        rows = self._conn.execute(
            "SELECT DISTINCT e.* FROM entries e"
            " JOIN entry_categories ec ON ec.entry_id=e.id"
            f" WHERE ec.category_id IN ({marks}) AND e.status='active'"
            + _consumable("e")
            + " AND (e.title LIKE ? ESCAPE '\\' OR e.inline_content LIKE ? ESCAPE '\\')"
            " ORDER BY e.exported_at DESC LIMIT ?",
            (*sub_ids, self._like_pattern(word), self._like_pattern(word), limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    # ---- 时间线视图（第四十四批：scoped timeline + 陈旧分支提醒） ----

    def timeline_data(self, category_id: str | None, *, granularity: str | None = None,
                      bucket: str | None = None, stale_years: int = 2,
                      bucket_limit: int = 100) -> dict[str, Any]:
        """时间线聚合数据源：focus 子树（None=全库）按 created_at 分桶 +
        陈旧叶子分支提醒（长期无新内容）+ bucket 下钻条目。

        时间口径：created_at = 内容时间（书签收藏/文件创建时间）；exported_at
        是入库时间（全批同时刻，无分布意义）不用作轴。created_at 缺失的条目
        只进 unknown_count，不编造时间。

        granularity: "year"|"month"|None（None=自适应：跨度 >24 个月→year）。
        bucket: 传 key（如 "2020" / "2020-07"）时返回该桶条目列表 entries。
        stale_years: 叶子分支最新条目早于该年数 → 进 stale_branches（只提醒，
        不改任何数据；用户否决/清理走既有管理入口）。

        返回：{focus, granularity, buckets, unknown_count, span,
        stale_branches, unknown_branches, threshold_years, entries?}
        """
        if category_id:
            sub_ids = self._cat_descendants(category_id)
            if category_id not in sub_ids:
                return {"focus": None, "granularity": granularity or "year",
                        "buckets": [], "unknown_count": 0, "span": None,
                        "stale_branches": [], "unknown_branches": [],
                        "threshold_years": stale_years}
        else:
            sub_ids = [r["id"] for r in self._conn.execute("SELECT id FROM categories")]
        if not sub_ids:
            return {"focus": None, "granularity": granularity or "year",
                    "buckets": [], "unknown_count": 0, "span": None,
                    "stale_branches": [], "unknown_branches": [],
                    "threshold_years": stale_years}
        marks = ",".join("?" * len(sub_ids))
        base = (" FROM entries e JOIN entry_categories ec ON ec.entry_id=e.id"
                f" WHERE ec.category_id IN ({marks}) AND e.status='active'"
                + _consumable("e"))
        focus = None
        if category_id:
            frow = self._conn.execute("SELECT id, name FROM categories WHERE id=?",
                                      (category_id,)).fetchone()
            if frow is not None:
                focus = {"id": frow["id"], "name": frow["name"]}
        # 时间未知计数（created_at 缺失——不编造时间、不判陈旧）
        unknown_count = self._conn.execute(
            "SELECT count(DISTINCT e.id) AS n" + base
            + " AND (e.created_at IS NULL OR e.created_at='')",
            tuple(sub_ids)).fetchone()["n"]
        # 跨度与分桶粒度
        span_row = self._conn.execute(
            "SELECT min(substr(e.created_at,1,10)) AS lo, max(substr(e.created_at,1,10)) AS hi"
            + base + " AND e.created_at IS NOT NULL AND e.created_at != ''",
            tuple(sub_ids)).fetchone()
        span = {"min": span_row["lo"], "max": span_row["hi"]} if span_row["lo"] else None
        if granularity not in ("year", "month"):
            granularity = "year"
            if span and span["min"] and span["max"]:
                lo_y, lo_m = int(span["min"][:4]), int(span["min"][5:7])
                hi_y, hi_m = int(span["max"][:4]), int(span["max"][5:7])
                if (hi_y - lo_y) * 12 + (hi_m - lo_m) <= 24:
                    granularity = "month"
        width = 4 if granularity == "year" else 7
        counts: dict[str, int] = {}
        if span:
            for r in self._conn.execute(
                    "SELECT substr(e.created_at,1,?) AS k, count(DISTINCT e.id) AS n"
                    + base + " AND e.created_at IS NOT NULL AND e.created_at != ''"
                    " GROUP BY k", (width, *sub_ids)):
                counts[r["k"]] = r["n"]
            buckets = self._fill_buckets(span, granularity, counts)
        else:
            buckets = []
        out: dict[str, Any] = {
            "focus": focus, "granularity": granularity, "buckets": buckets,
            "unknown_count": unknown_count, "span": span,
            "threshold_years": stale_years,
        }
        if bucket:
            # bucket 前缀匹配（长度自适应）：month 粒度下传 "2020" 得全年，
            # 传 "2020-07" 得单月——前端传当前图桶 key，直调也不会因粒度落空
            rows = self._conn.execute(
                "SELECT DISTINCT e.*" + base
                + " AND e.created_at IS NOT NULL AND e.created_at != ''"
                + " AND substr(e.created_at,1,?) = ?"
                " ORDER BY e.exported_at DESC LIMIT ?",
                (*sub_ids, len(bucket), bucket, bucket_limit)).fetchall()
            out["entries"] = [self._row_to_entry(r) for r in rows]
        # 陈旧分支提醒：子树内叶子分类（无子节点），各自 max(created_at)
        out["stale_branches"], out["unknown_branches"] = self._stale_branches(
            sub_ids, stale_years=stale_years)
        return out

    @staticmethod
    def _fill_buckets(span: dict[str, str], granularity: str,
                      counts: dict[str, int]) -> list[dict[str, Any]]:
        """连续区间补齐空桶（柱状图轴均匀；稀疏年份不出空洞误导）。"""
        lo_y, lo_m = int(span["min"][:4]), int(span["min"][5:7])
        hi_y, hi_m = int(span["max"][:4]), int(span["max"][5:7])
        keys: list[str] = []
        if granularity == "year":
            keys = [str(y) for y in range(lo_y, hi_y + 1)]
        else:
            y, m = lo_y, lo_m
            while (y, m) <= (hi_y, hi_m):
                keys.append(f"{y:04d}-{m:02d}")
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return [{"key": k, "label": k, "count": counts.get(k, 0)} for k in keys]

    def _stale_branches(self, sub_ids: list[str], *,
                        stale_years: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """子树内叶子分类的陈旧判定（第四十四批）。叶子 = 无子节点的分类
        （category_parents.parent_id 列里从不出现的分类；该表一行
        (category_id, parent_id) 表示 category_id 的父是 parent_id）。

        只提醒不改数据（只标不删可逆模型）：latest 超 stale_years 年 →
        stale_branches；created_at 全缺 → unknown_branches（时间未知 ≠ 陈旧）。
        """
        leaves = [r["id"] for r in self._conn.execute(
            "SELECT id FROM categories"
            " WHERE id NOT IN (SELECT parent_id FROM category_parents)"
            "   AND id IN (%s)" % ",".join("?" * len(sub_ids)),
            tuple(sub_ids))]
        stale: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []
        for cid in leaves:
            ids = self._cat_descendants(cid)
            if cid not in ids:
                ids.append(cid)
            marks = ",".join("?" * len(ids))
            row = self._conn.execute(
                "SELECT count(DISTINCT e.id) AS n, max(e.created_at) AS latest"
                " FROM entries e JOIN entry_categories ec ON ec.entry_id=e.id"
                f" WHERE ec.category_id IN ({marks}) AND e.status='active'"
                + _consumable("e"), tuple(ids)).fetchone()
            if not row["n"]:
                continue  # 空叶子不提醒（可能条目被舍弃/归档后清空）
            name = self._conn.execute("SELECT name FROM categories WHERE id=?",
                                      (cid,)).fetchone()["name"]
            item = {"id": cid, "name": name, "latest": row["latest"], "count": row["n"]}
            if not row["latest"]:
                unknown.append(item)
                continue
            latest = datetime.fromisoformat(row["latest"])
            if latest.tzinfo is None:  # 统一到 aware 再比（created_at 带时区偏移）
                latest = latest.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - latest).days / 365.25
            item["age_years"] = round(age, 1)
            if age >= stale_years:
                stale.append(item)
        stale.sort(key=lambda x: -x["age_years"])
        return stale, unknown

