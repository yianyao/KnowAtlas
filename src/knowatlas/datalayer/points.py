"""知识点域：points 存取、分诊/老化/事实核查队列、point_sources、点级图助手。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Sequence

from ._common import _consumable, _meta_json, _now


class _PointsMixin:
    # ---- 知识点（迁移 007，第六十二批；点 text 是抽取产物可重抽重建，原文永在
    #      entries/content_store；content_hash 去重，一点多溯源走 point_sources） ----

    def put_point(self, point: dict[str, Any], source: dict[str, Any]) -> str:
        """写一个点 + 一条溯源；content_hash 已存在 → 只补溯源（一点多溯源）。

        point: {content_hash, text, summary, source_type, judge, meta}；
        source: {entry_id, char_offset, anchor}。
        返回 "created"（新点）或 "linked"（既有点新增溯源指针）。
        """
        now = _now()
        meta = point.get("meta") or {}
        with self.transaction() as conn:
            row = conn.execute("SELECT id FROM points WHERE content_hash=?",
                               (point["content_hash"],)).fetchone()
            if row is None:
                pid = point["content_hash"][:16]  # 确定性 id：与去重键同源
                conn.execute(
                    "INSERT INTO points (id, content_hash, text, summary,"
                    " source_type, judge, created_at, meta) VALUES (?,?,?,?,?,?,?,?)",
                    (pid, point["content_hash"], point["text"],
                     point.get("summary", ""), point["source_type"],
                     point["judge"], now, _meta_json(meta)))
                status = "created"
            else:
                pid = row["id"]
                status = "linked"
            conn.execute(
                "INSERT OR IGNORE INTO point_sources"
                " (point_id, entry_id, char_offset, anchor, created_at)"
                " VALUES (?,?,?,?,?)",
                (pid, source["entry_id"], source.get("char_offset"),
                 source.get("anchor"), now))
        self.log_task(now, "points", "put", pid,
                      {"judge": point["judge"], "result": status,
                       "entry_id": source["entry_id"]})
        return status

    def count_points(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]

    def merge_meta_of_point(self, point_id: str, patch: dict[str, Any]) -> None:
        """点 meta 局部合并（批次 90：释疑结果缓存 explain；条目层 merge_meta
        的点层对应物，浅合并语义一致）。"""
        with self.transaction() as conn:
            row = conn.execute("SELECT meta FROM points WHERE id=?",
                               (point_id,)).fetchone()
            if row is None:
                return
            meta = json.loads(row["meta"] or "{}")
            meta.update(patch)
            conn.execute("UPDATE points SET meta=? WHERE id=?",
                         (json.dumps(meta, ensure_ascii=False), point_id))

    def points_without_kind(self, limit: int = 0, *,
                            include_dupes: bool = False) -> list[dict[str, Any]]:
        """待分诊点（meta.kind 为空），P0「点分诊」的取数入口。

        默认排除 `meta.dupe_of` 非空的重复点：重复点由调用方直接标 `dupe`，
        不进 LLM（与消费面去重口径一致，见文件头 dupe_of 守卫说明）。
        `limit=0` 表示不限；按 created_at 升序（知识形成顺序）稳定排序。
        """
        sql = ("SELECT id, text, content_hash, meta FROM points"
               " WHERE COALESCE(json_extract(meta,'$.kind'),'') = ''")
        if not include_dupes:
            sql += " AND COALESCE(json_extract(meta,'$.dupe_of'),'') = ''"
        sql += " ORDER BY created_at, id"
        params: tuple[Any, ...] = ()
        if limit and limit > 0:
            sql += " LIMIT ?"
            params = (limit,)
        out = []
        for r in self._conn.execute(sql, params).fetchall():
            d = dict(r)
            try:
                d["meta"] = json.loads(d["meta"] or "{}")
            except ValueError:
                d["meta"] = {}
            out.append(d)
        return out

    def point_kind_counts(self) -> dict[str, int]:
        """分诊分布（P0 验收口径）：hard/opinion/unjudgeable/dupe，未分诊记 '(none)'。"""
        rows = self._conn.execute(
            "SELECT COALESCE(json_extract(meta,'$.kind'),'') AS kind,"
            " COUNT(*) AS n FROM points GROUP BY kind ORDER BY kind").fetchall()
        return {(r["kind"] or "(none)"): r["n"] for r in rows}

    def points_of_kind(self, kind: str, limit: int = 0) -> list[dict[str, Any]]:
        """按分诊类别取点（P1 勘误 / P2 老化的领域闸门入口）；meta 已解析。"""
        sql = ("SELECT id, content_hash, text, aging_flag, meta FROM points"
               " WHERE COALESCE(json_extract(meta,'$.kind'),'') = ?"
               " ORDER BY created_at, id")
        params: list[Any] = [kind]
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        out = []
        for r in self._conn.execute(sql, params).fetchall():
            d = dict(r)
            try:
                d["meta"] = json.loads(d["meta"] or "{}")
            except ValueError:
                d["meta"] = {}
            out.append(d)
        return out

    def hard_points_without_fact_check(self, limit: int = 0) -> list[dict[str, Any]]:
        """P1 点级勘误候选：kind=hard 且未落 fact_check 的点（meta 已解析）。

        领域闸门写进 SQL（与 pipeline/triage.py::is_hard 同口径）：opinion /
        unjudgeable / dupe 永不成候选——没有客观对错，不判。
        """
        sql = ("SELECT id, content_hash, text, meta FROM points"
               " WHERE COALESCE(json_extract(meta,'$.kind'),'') = 'hard'"
               "   AND COALESCE(json_extract(meta,'$.fact_check.at'),'') = ''"
               " ORDER BY created_at, id")
        params: list[Any] = []
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        out = []
        for r in self._conn.execute(sql, params).fetchall():
            d = dict(r)
            try:
                d["meta"] = json.loads(d["meta"] or "{}")
            except ValueError:
                d["meta"] = {}
            out.append(d)
        return out

    def points_fact_check_counts(self) -> dict[str, int]:
        """点级勘误分布（P1 验收口径，只统计 hard 点）：wrong/suspect/ok/(none)。"""
        rows = self._conn.execute(
            "SELECT COALESCE(json_extract(meta,'$.fact_check.verdict'),'') AS v,"
            " COUNT(*) AS n FROM points"
            " WHERE COALESCE(json_extract(meta,'$.kind'),'') = 'hard'"
            " GROUP BY v ORDER BY v").fetchall()
        return {(r["v"] or "(none)"): r["n"] for r in rows}

    def points_wrong_queue(self, limit: int = 500) -> list[dict[str, Any]]:
        """点级勘误裁决队列：hard 且 verdict=wrong 且人裁未否决（fact_check.dismissed），
        按结论时间倒序。suspect 不到确认级，不进队列（§7.6 纪律）。meta 已解析。"""
        rows = self._conn.execute(
            "SELECT id, content_hash, text, meta FROM points"
            " WHERE COALESCE(json_extract(meta,'$.kind'),'') = 'hard'"
            "   AND COALESCE(json_extract(meta,'$.fact_check.verdict'),'') = 'wrong'"
            "   AND COALESCE(json_extract(meta,'$.fact_check.dismissed'), 0) = 0"
            " ORDER BY COALESCE(json_extract(meta,'$.fact_check.at'), '') DESC, id"
            " LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["meta"] = json.loads(d["meta"] or "{}")
            except ValueError:
                d["meta"] = {}
            out.append(d)
        return out

    def get_point_meta(self, point_id: str) -> dict[str, Any] | None:
        """按 id 取单点（id/text/meta；meta 已解析），**不过**消费面过滤。

        勘误裁决与原因码回填要看得到任何点（含老化 stale / 去重副点），所以不能复用
        `get_point_hit`（它按消费面口径过滤）；不存在返回 None。
        """
        r = self._conn.execute(
            "SELECT id, text, meta FROM points WHERE id=?", (point_id,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        try:
            d["meta"] = json.loads(d["meta"] or "{}")
        except ValueError:
            d["meta"] = {}
        return d

    def points_wrong_without_reason_code(self, limit: int = 0) -> list[dict[str, Any]]:
        """P1b 原因码回填候选：hard + verdict=wrong + reason_code 空 + 人裁未否决。

        与 `points_wrong_queue` 同一域（队列里人看得到的才补码），只多一个空码条件；
        幂等口径同源——已补过码的点自动不再入选。
        """
        sql = ("SELECT id, content_hash, text, meta FROM points"
               " WHERE COALESCE(json_extract(meta,'$.kind'),'') = 'hard'"
               "   AND COALESCE(json_extract(meta,'$.fact_check.verdict'),'') = 'wrong'"
               "   AND COALESCE(json_extract(meta,'$.fact_check.reason_code'),'') = ''"
               "   AND COALESCE(json_extract(meta,'$.fact_check.dismissed'), 0) = 0"
               " ORDER BY id")
        params: list[Any] = []
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        out = []
        for r in self._conn.execute(sql, params).fetchall():
            d = dict(r)
            try:
                d["meta"] = json.loads(d["meta"] or "{}")
            except ValueError:
                d["meta"] = {}
            out.append(d)
        return out

    def set_point_aging(self, point_id: str, flag: str, reason: str) -> None:
        """点级老化结论落列（批次 93，裁决 #14）：stale 退出消费面 / ok 免疫复扫 /
        keep 只记游标留观（flag 传 '' 表示维持未判）。永不物理删除点。"""
        with self.transaction() as conn:
            conn.execute(
                "UPDATE points SET aging_flag=?, aging_reason=?, aging_checked_at=? "
                "WHERE id=?",
                (flag, reason, _now(), point_id),
            )
        self.log_task(_now(), "kaging", "point_verdict", point_id,
                      {"flag": flag, "reason": reason[:200]})

    def list_points(self, limit: int = 200) -> list[dict[str, Any]]:
        """点列表（created_at 升序=知识形成顺序），附溯源数与最早溯源；meta 已解析。"""
        rows = self._conn.execute(
            "SELECT p.*, COUNT(ps.entry_id) AS source_count,"
            " MIN(ps.created_at) AS first_seen"
            " FROM points p LEFT JOIN point_sources ps ON ps.point_id = p.id"
            " GROUP BY p.id ORDER BY p.created_at, p.id LIMIT ?",
            (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["meta"] = json.loads(d["meta"] or "{}")
            except ValueError:
                d["meta"] = {}
            out.append(d)
        return out

    def point_sources_of(self, point_id: str) -> list[dict[str, Any]]:
        """一点的全部溯源指针（entry_id/char_offset/anchor/created_at）。"""
        rows = self._conn.execute(
            "SELECT ps.*, e.title, e.source_type AS entry_source_type"
            " FROM point_sources ps JOIN entries e ON e.id = ps.entry_id"
            " WHERE ps.point_id=? ORDER BY ps.created_at", (point_id,)).fetchall()
        return [dict(r) for r in rows]

    def point_source_entry_ids(self) -> set[str]:
        """已抽取过点的条目 id 集合（流水线幂等游标：重跑自动跳过）。"""
        rows = self._conn.execute(
            "SELECT DISTINCT entry_id FROM point_sources").fetchall()
        return {r["entry_id"] for r in rows}

    def point_source_map(self, point_ids: Sequence[str] | None = None
                         ) -> dict[str, list[str]]:
        """点 → 溯源条目 id 列表（只读；老化域闸门要按条目分类判点）。

        point_ids=None 取全表（点量级 5k，一次查询比逐点查快两个数量级）；
        显式给 id 时按 400/片分批（SQLite 变量上限 999）。
        """
        out: dict[str, list[str]] = {}
        if point_ids is None:
            rows = self._conn.execute(
                "SELECT point_id, entry_id FROM point_sources ORDER BY point_id"
            ).fetchall()
            for r in rows:
                out.setdefault(r["point_id"], []).append(r["entry_id"])
            return out
        ids = [p for p in point_ids if p]
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            marks = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                "SELECT point_id, entry_id FROM point_sources"
                f" WHERE point_id IN ({marks}) ORDER BY point_id", chunk).fetchall()
            for r in rows:
                out.setdefault(r["point_id"], []).append(r["entry_id"])
        return out

    def points_of_entries(self, entry_ids: list[str],
                          text_cap: int = 500) -> dict[str, list[dict[str, Any]]]:
        """批量取条目挂的点（③默认聚合呈现，批次 67）：entry_id → 点列表。

        两层形态共存的消费面：条目（方案级）照常检索，点级收进可展开区。
        text 截 text_cap 字符（点全文走条目原文/后续点详情，检索页不背 20K
        整图大纲）；返回键恒存在（无点条目 → 空列表）。
        """
        out: dict[str, list[dict[str, Any]]] = {eid: [] for eid in entry_ids}
        if not entry_ids:
            return out
        marks = ",".join("?" * len(entry_ids))
        rows = self._conn.execute(
            "SELECT ps.entry_id, p.id, p.summary, p.text, p.judge, p.content_hash,"
            " p.created_at, p.meta FROM point_sources ps"
            " JOIN points p ON p.id = ps.point_id"
            f" WHERE ps.entry_id IN ({marks}) ORDER BY ps.entry_id, p.created_at, p.id",
            entry_ids).fetchall()
        for r in rows:
            d = dict(r)
            text = d.pop("text") or ""
            d["text_len"] = len(text)
            d["text"] = text if len(text) <= text_cap else text[:text_cap] + "…[截断]"
            # 释疑缓存透出（批次 90：已释疑的点前端直接展示，零重复费用）
            try:
                explain = (json.loads(d.pop("meta") or "{}").get("explain") or {})
            except json.JSONDecodeError:
                explain = {}
            if explain.get("explanation"):
                d["explain"] = explain
            out[d["entry_id"]].append(d)
        return out

    def purge_points(self, *, reason: str, task_name: str = "kpoints") -> int:
        """清空点层（points + point_sources）——形态判定口径变更后的推倒重来
        （2026-10-22 用户口径：LLM 判定 → 确定性规则，旧点全部作废）。

        只动点层：entries/content_store/向量等全部不受影响（点 text 是抽取
        产物，原文永在）。写 task_log 审计。
        """
        with self.transaction() as conn:
            n_points = conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]
            conn.execute("DELETE FROM point_sources")
            conn.execute("DELETE FROM points")
            conn.execute(
                "INSERT INTO task_log (at, task_name, action, target, detail)"
                " VALUES (datetime('now'),?,?,?,?)",
                (task_name, "purge_points", "points",
                 json.dumps({"reason": reason, "purged_points": n_points},
                            ensure_ascii=False)))
        return n_points

    def purge_entry_points(self, entry_id: str, *, reason: str,
                           task_name: str = "kpoints") -> int:
        """清单条目的点溯源（批次 70 条目级形态覆盖的配套）。

        删该条目全部 point_sources 行；失去全部溯源的点（孤儿）一并删——
        一点多溯源口径下仍被其他条目引用的共享点保留。游标 point_source_entry_ids
        派生自 point_sources → 溯源清即游标清，重抽自动视为新候选。写 task_log 审计。
        """
        with self.transaction() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM point_sources WHERE entry_id=?",
                (entry_id,)).fetchone()[0]
            conn.execute("DELETE FROM point_sources WHERE entry_id=?", (entry_id,))
            conn.execute(
                "DELETE FROM points WHERE id NOT IN"
                " (SELECT DISTINCT point_id FROM point_sources)")
            conn.execute(
                "INSERT INTO task_log (at, task_name, action, target, detail)"
                " VALUES (datetime('now'),?,?,?,?)",
                (task_name, "purge_entry_points", entry_id,
                 json.dumps({"reason": reason, "purged_sources": n},
                            ensure_ascii=False)))
        return n

    # ---- 点级图（P4，2026-10-26：点成为一等节点） ----
    # 口径纪律：点节点只在「可消费」时露面——非 stale、非 dupe 副点、至少一条
    # 溯源条目 active 且过 _consumable('e')。与 search_points/get_point_hit 同源，
    # 不另立消费面口径（改一处必须同步另一处）。
    _POINT_SIM_THRESHOLD = 0.5   # 与条目 sim 通道同阈值

    def _point_row(self, point_id: str) -> sqlite3.Row | None:
        """点的消费面行（id/summary/text[:300]/meta）；不满足消费面即 None。"""
        return self._conn.execute(
            "SELECT p.id, p.summary, substr(p.text,1,300) AS text, p.meta"
            " FROM points p"
            " WHERE p.id=? AND p.aging_flag != 'stale'"
            "   AND COALESCE(json_extract(p.meta,'$.dupe_of'),'')=''"
            "   AND EXISTS (SELECT 1 FROM point_sources ps"
            "               JOIN entries e ON e.id=ps.entry_id"
            "               WHERE ps.point_id=p.id AND e.status='active'"
            + _consumable("e") + ")",
            (point_id,)).fetchone()

    def _point_sources(self, point_id: str, limit: int = 6) -> list[dict[str, Any]]:
        """点的溯源条目（display_name 覆盖层 + 消费面守卫，get_point_hit 同口径）。"""
        rows = self._conn.execute(
            "SELECT e.id AS entry_id,"
            " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS title,"
            " e.locator"
            " FROM point_sources ps JOIN entries e ON e.id=ps.entry_id"
            " WHERE ps.point_id=? AND e.status='active'" + _consumable("e") +
            " ORDER BY ps.created_at LIMIT ?", (point_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def _point_reverse_items(self, point_id: str,
                             limit: int) -> list[dict[str, Any]] | None:
        """点反查项：溯源条目（source:point）+ 这些条目挂的分类（attach:<origin>）。

        消费面闸门与 radiate 点焦点同源（`_point_row`：stale / dupe_of / 溯源条目全回收
        即不在消费面），不满足返回 None → API 404。只出**非对称**关系：同书 / 同章节 /
        语义近邻都是对称边，反向枚举等于把放射视图再列一遍，故不出。
        条目在前、分类在后，合并后统一 items[:limit]（与既有 reverse 口径一致）。
        """
        if self._point_row(point_id) is None:
            return None
        items: list[dict[str, Any]] = []
        seen_cats: dict[str, str] = {}
        for s in self._point_sources(point_id, limit=limit):
            items.append({"kind": "entry", "id": f"e:{s['entry_id']}",
                          "name": (s["title"] or s["locator"] or "")[:40],
                          "locator": s["locator"],
                          "reason": "source:point"})
            for r in self._conn.execute(
                    "SELECT category_id, origin FROM entry_categories WHERE entry_id=?",
                    (s["entry_id"],)).fetchall():
                seen_cats.setdefault(r["category_id"], r["origin"])
        for cid, origin in seen_cats.items():
            crow = self._conn.execute(
                "SELECT name FROM categories WHERE id=?", (cid,)).fetchone()
            paths = self.get_category_paths(cid)
            items.append({"kind": "category", "id": f"c:{cid}",
                          "name": crow["name"] if crow else "?",
                          "path": paths[0] if paths else "",
                          "reason": f"attach:{origin}"})
        return items[:limit]

    @staticmethod
    def _point_book_section(meta_raw: Any) -> tuple[str, str]:
        """从点 meta 取 (book, section_path)；坏 JSON 按空处理（不抛）。"""
        try:
            meta = json.loads(meta_raw or "{}")
        except (TypeError, ValueError):
            meta = {}
        return (str(meta.get("book") or "").strip(),
                str(meta.get("section_path") or "").strip())

    @staticmethod
    def _point_label(summary: Any, text: Any) -> str:
        """点节点名：摘要优先，退化正文前 40 字（与词云点卡同口径）。"""
        return str(summary or text or "")[:40]

    @classmethod
    def _point_path(cls, meta_raw: Any, srcs: list[dict[str, Any]]) -> str:
        """点节点路径：有 book 出《书名》/章节；否则退化为「溯源：条目名」。"""
        book, section = cls._point_book_section(meta_raw)
        if book:
            return f"《{book}》 / {section}" if section and section != book else f"《{book}》"
        if srcs:
            return "溯源：" + "、".join(str(s.get("title") or "") for s in srcs[:3])
        return ""

    def _point_peers(self, book: str, section: str, exclude: str,
                     limit: int) -> tuple[int, list[sqlite3.Row]]:
        """同书/同章节的点（created_at DESC）；返回 (总数, 前 limit 行) 供截断计数。"""
        where = (" FROM points p"
                 " WHERE json_extract(p.meta,'$.book')=?"
                 "   AND p.id != ?"
                 "   AND p.aging_flag != 'stale'"
                 "   AND COALESCE(json_extract(p.meta,'$.dupe_of'),'')=''"
                 "   AND EXISTS (SELECT 1 FROM point_sources ps"
                 "               JOIN entries e ON e.id=ps.entry_id"
                 "               WHERE ps.point_id=p.id AND e.status='active'"
                 + _consumable("e") + ")")
        params: list[Any] = [book, exclude]
        if section:
            where += " AND json_extract(p.meta,'$.section_path')=?"
            params.append(section)
        total = self._conn.execute("SELECT COUNT(*)" + where, params).fetchone()[0]
        rows = self._conn.execute(
            "SELECT p.id, p.summary, substr(p.text,1,300) AS text, p.meta" + where +
            " ORDER BY p.created_at DESC LIMIT ?", (*params, limit)).fetchall()
        return total, rows

    def _point_sim_channel(self, point_id: str, add_node, add_edge, cut,
                           per_channel: int) -> int:
        """radiate 点焦点的 sim 通道：点向量 top 邻域（阈值 0.5，纯标准库余弦）。

        与 `_sim_channel` 同构（数学在 semantic/embed.py，此处就地轻量解码以
        避免 db → semantic 反向依赖）；4,552 点 × 1024 维实测约 0.2 s。
        """
        import array as _array
        import math as _math

        focal = self._conn.execute(
            "SELECT vector FROM point_vectors WHERE point_id=?",
            (point_id,)).fetchone()
        if focal is None:
            return 0
        fa = _array.array("f")
        fa.frombytes(focal["vector"])
        dim = len(fa)
        fnorm = _math.sqrt(sum(x * x for x in fa)) or 1.0
        scored: list[tuple[str, float]] = []
        for pid, blob in self.all_point_vectors().items():
            if pid == point_id:
                continue
            va = _array.array("f")
            va.frombytes(blob)
            if len(va) != dim:
                continue  # 换型残留的异维向量跳过（不报错，--embed-force 重算）
            vnorm = _math.sqrt(sum(x * x for x in va)) or 1.0
            dot = sum(x * y for x, y in zip(fa, va))
            score = dot / (fnorm * vnorm)
            if score >= self._POINT_SIM_THRESHOLD:
                scored.append((pid, score))
        scored.sort(key=lambda x: -x[1])
        emitted = 0
        for pid, score in scored:
            if emitted >= per_channel:
                break
            r = self._point_row(pid)   # 消费面内才出节点（截断计数仍按候选总数）
            if r is None:
                continue
            add_node(f"p:{pid}", self._point_label(r["summary"], r["text"]), "point",
                     f"sim:{score:.2f}", text=r["text"],
                     path=self._point_path(r["meta"], []))
            add_edge(f"p:{pid}", f"sim:{score:.2f}")
            emitted += 1
        cut("sim", len(scored))
        return len(scored)

