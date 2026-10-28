"""检索域：FTS5、LIKE 兜底、点检索、/api/stats 统计。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..models import PointHit, SearchHit
from ._common import _consumable


class _SearchMixin:
    # ---- 检索 ----

    def search_fts(self, query: str, limit: int = 50) -> list[SearchHit]:
        """混合入口的 FTS 级。

        trigram 分词器对 <3 字符查询零命中（H2 返工定稿），两字词走 LIKE 兜底；
        有会红的测试钉住（tests/test_datalayer.py::test_two_char_query_finds_content）。
        """
        q = query.strip()
        if not q:
            return []
        # display_name 匹配（2026-10-23 用户裁决「display_name 入 FTS 索引」的落地形态）：
        # 不重建 external content 表（正会双倍存储 + snippet 错乱 + 迁移成本）。
        # ⚠ FTS5 MATCH 不可与 OR 组合（`unable to use function MATCH in the
        # requested context`）——首版 WHERE MATCH OR dn-LIKE 每查必抛 OperationalError
        # 静默落兜底（330ms，FTS 索引报废）。改 UNION 两段：FTS 段（bm25 毫秒级）
        # + display_name 段（instr 粗筛零 JSON 解析 + json_extract 精筛，rank 5.0
        # 排后），Python 合并去重。十万条量级若 dn 段成瓶颈，升级路径 = display_name
        # 物化为 entries 生成列 + 索引。
        like = f"%{self._escape_like(q)}%"
        if len(q) >= 3:
            match = '"' + q.replace('"', '""') + '"'
            try:
                rows = self._conn.execute(
                    "SELECT e.id,"
                    " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS title,"
                    " e.locator,"
                    " snippet(entries_fts, 0, '[', ']', '…', 12) AS snip,"
                    " bm25(entries_fts) AS rank"
                    " FROM entries_fts JOIN entries e ON e.rowid = entries_fts.rowid"
                    " WHERE entries_fts MATCH ? AND e.status='active'"
                    + _consumable("e") +
                    " ORDER BY rank LIMIT ?",
                    (match, limit),
                ).fetchall()
                dn = self._conn.execute(
                    "SELECT e.id,"
                    " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS title,"
                    " e.locator,"
                    " substr(COALESCE(e.inline_content,''),1,80) AS snip,"
                    " 5.0 AS rank"
                    " FROM entries e"
                    " WHERE e.status='active'" + _consumable("e") +
                    "   AND instr(e.meta,'display_name')>0"
                    "   AND json_extract(e.meta,'$.display_name') LIKE ? ESCAPE '\\'"
                    " LIMIT ?",
                    (like, limit),
                ).fetchall()
                seen = {r["id"] for r in rows}
                rows = list(rows) + [r for r in dn if r["id"] not in seen]
                return [SearchHit(r["id"], r["title"], r["locator"], r["snip"], r["rank"])
                        for r in rows]
            except sqlite3.OperationalError:
                pass  # 语法不兼容等异常 → 落到 LIKE 兜底
        return self._search_like(q, limit)

    @staticmethod
    def _escape_like(q: str) -> str:
        return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _search_like(self, q: str, limit: int) -> list[SearchHit]:
        """两字词 LIKE 兜底（第五十八批重写：拆双查询 + Python 去重）。

        原实现把两路 LIKE 用 UNION 合成一条 SQL——真实库（约 1809 条 /
        content_fts 约 130MB）上过期统计使 planner 选出灾难计划：entries 当
        外层 × content_fts 虚表全扫当内层（条目数 × 130MB），单查询卡 1h+
        且近乎 0 CPU；再叠加 /api/recall 在事件循环同步执行，整个 serve
        冻结（UI「聚合中…」永转圈）。现拆两条计划安全的查询：
        ① entries 三列 LIKE（走 idx_entries_status，小库毫秒级）；
        ② content_fts LIKE 子查询 → idx_entries_hash 回表（见 `_content_like_rows`：
        2026-10-28 追加 `AS MATERIALIZED`，否则 planner 仍会选「entries 外层 ×
        虚表全扫内层」，实测 1,540 ms → 21 ms）。语义与原 UNION 等价（Python 去重 + LIMIT）。
        """
        like = f"%{self._escape_like(q)}%"
        # title 显示走 display_name 覆盖层（批次 71 追修：检索/聚合视图曾显示旧名——
        # SQL 直读 e.title 绕过 _row_to_entry）；WHERE 匹配仍按原文 title（FTS 索引同）。
        dn_match = ("(instr(e.meta,'display_name')>0"
                    " AND json_extract(e.meta,'$.display_name') LIKE ? ESCAPE '\\')")
        sel = ("SELECT e.id,"
               " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS title,"
               " e.locator,"
               " substr(COALESCE(e.inline_content,''),1,80) AS snip, 1.0 AS rank")
        rows = self._conn.execute(
            f"{sel} FROM entries e"
            " WHERE e.status='active'" + _consumable("e") +
            "   AND (e.title LIKE ? ESCAPE '\\'"
            "      OR e.native_path LIKE ? ESCAPE '\\'"
            "      OR e.inline_content LIKE ? ESCAPE '\\'"
            "      OR " + dn_match + ") LIMIT ?",
            (like, like, like, like, limit),
        ).fetchall()
        if len(rows) < limit:
            rows += self._content_like_rows(sel, like, limit)
        out: list[SearchHit] = []
        seen: set[str] = set()
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            out.append(SearchHit(r["id"], r["title"], r["locator"],
                                 r["snip"], r["rank"]))
            if len(out) >= limit:
                break
        return out

    def _content_like_rows(self, sel: str, like: str, limit: int) -> list[Any]:
        """正文级 LIKE 段（`_search_like` 的第二条 SQL）：先物化正文命中再回表。

        2026-10-28 现场实测（真库 368 条目 / content_fts 77 条正文，"雪花"）：
        派生表写法 `JOIN (SELECT content_hash FROM content_fts WHERE text LIKE ?)`
        被 SQLite 选成 `SCAN e USING idx_entries_status` 外层 × `SCAN content_fts
        VIRTUAL TABLE` 内层（无 join 索引）——每条 active 条目重扫一遍 FTS 影子表，
        **1,540–1,745 ms**（`search_fts("雪花")` 整体 3.0–3.4 s 的主因）。
        加 `AS MATERIALIZED` 强制先物化命中集合（77 行）再走索引连接：
        **21 ms**，结果集 id 逐一相同。`MATERIALIZED` 需 SQLite ≥ 3.35（本机 3.53.1）；
        更老的版本触发 OperationalError → 退回原派生表写法（慢但不报错）。
        """
        sql = (f"WITH c AS MATERIALIZED (SELECT content_hash FROM content_fts"
               "  WHERE text LIKE ? ESCAPE '\\')"
               f" {sel} FROM entries e JOIN c ON c.content_hash = e.content_hash"
               " WHERE e.status='active'" + _consumable("e") +
               " LIMIT ?")
        try:
            return self._conn.execute(sql, (like, limit)).fetchall()
        except sqlite3.OperationalError:
            # 老 SQLite 不认 MATERIALIZED：退回派生表（计划可能灾难，但不失败）
            return self._conn.execute(
                f"{sel} FROM entries e"
                " JOIN (SELECT content_hash FROM content_fts"
                "        WHERE text LIKE ? ESCAPE '\\') c"
                "   ON c.content_hash = e.content_hash"
                " WHERE e.status='active'" + _consumable("e") +
                " LIMIT ?",
                (like, limit),
            ).fetchall()

    def search_entries_direct(self, q: str, limit: int = 20) -> list[SearchHit]:
        """条目标题/路径直击（批次 92，裁决 #13：条目区=命中点溯源反查为主，
        直击为补充）。

        只匹配 title / display_name 覆盖层 / native_path——正文级命中由点层
        承接（词越精确条目越少；全文命中不再单独出条目卡，经点卡溯源 chips
        反查条目）。rank 固定 0.5 排在点反查条目之后。
        """
        like = f"%{self._escape_like(q)}%"
        dn = ("(instr(e.meta,'display_name')>0"
              " AND json_extract(e.meta,'$.display_name') LIKE ? ESCAPE '\\')")
        rows = self._conn.execute(
            "SELECT e.id,"
            " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS title,"
            " e.locator,"
            " substr(COALESCE(e.inline_content,''),1,80) AS snip, 0.5 AS rank"
            " FROM entries e"
            " WHERE e.status='active'" + _consumable("e") +
            "   AND (e.title LIKE ? ESCAPE '\\'"
            "      OR e.native_path LIKE ? ESCAPE '\\'"
            "      OR " + dn + ") LIMIT ?",
            (like, like, like, limit),
        ).fetchall()
        return [SearchHit(r["id"], r["title"], r["locator"], r["snip"], r["rank"])
                for r in rows]

    def search_points(self, query: str, limit: int = 20) -> list[PointHit]:
        """知识点检索（批次 86：点升格为检索主体）。

        points_fts（迁移 008，trigram external content + 触发器同步）为主，
        <3 字 trigram 零命中 → points 表 LIKE 兜底；两路都过滤可消费溯源——
        点只随其可消费条目出现（溯源全不可消费的点不露面）。每点带溯源条目
        （display_name 覆盖层标题），rank：FTS 用 bm25、兜底 1.0。
        """
        q = query.strip()
        if not q:
            return []
        like = f"%{self._escape_like(q)}%"
        cons = _consumable("e")
        rows = []
        if len(q) >= 3:
            match = '"' + q.replace('"', '""') + '"'
            try:
                rows = self._conn.execute(
                    "SELECT p.id, substr(p.text,1,200) AS text, p.summary,"
                    " bm25(points_fts) AS rank"
                    " FROM points_fts JOIN points p ON p.rowid = points_fts.rowid"
                    " WHERE points_fts MATCH ?"
                    "   AND p.aging_flag != 'stale'"      # 点级老化退出消费面（批次 93）
                    "   AND COALESCE(json_extract(p.meta,'$.dupe_of'),'')=''"  # 语义去重副点（批次 94）
                    "   AND EXISTS (SELECT 1 FROM point_sources ps"
                    "               JOIN entries e ON e.id = ps.entry_id"
                    "               WHERE ps.point_id = p.id AND e.status='active'" + cons + ")"
                    " ORDER BY rank LIMIT ?",
                    (match, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                pass  # 语法异常 → LIKE 兜底
        if len(rows) < limit:
            rows += self._conn.execute(
                "SELECT p.id, substr(p.text,1,200) AS text, p.summary, 1.0 AS rank"
                " FROM points p"
                " WHERE (p.text LIKE ? ESCAPE '\\' OR p.summary LIKE ? ESCAPE '\\')"
                "   AND p.aging_flag != 'stale'"      # 点级老化退出消费面（批次 93）
                "   AND COALESCE(json_extract(p.meta,'$.dupe_of'),'')=''"  # 语义去重副点（批次 94）
                "   AND EXISTS (SELECT 1 FROM point_sources ps"
                "               JOIN entries e ON e.id = ps.entry_id"
                "               WHERE ps.point_id = p.id AND e.status='active'" + cons + ")"
                " LIMIT ?",
                (like, like, limit),
            ).fetchall()
        seen: set[str] = set()
        out: list[PointHit] = []
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            srcs = self._conn.execute(
                "SELECT e.id AS entry_id,"
                " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS title,"
                " e.locator"
                " FROM point_sources ps JOIN entries e ON e.id = ps.entry_id"
                " WHERE ps.point_id = ? AND e.status='active'" + cons +
                " ORDER BY ps.created_at LIMIT 6",
                (r["id"],),
            ).fetchall()
            out.append(PointHit(r["id"], r["text"], r["summary"],
                                tuple(dict(x) for x in srcs), r["rank"]))
            if len(out) >= limit:
                break
        return out

    def get_point_hit(self, point_id: str) -> PointHit | None:
        """单点检索视图（批次 87：点向量融合时补全向量独有点；search_points 同
        口径——溯源全不可消费的点返回 None 不露面）。"""
        r = self._conn.execute(
            "SELECT id, substr(text,1,200) AS text, summary FROM points"
            " WHERE id=? AND aging_flag != 'stale'"   # 点级老化退出消费面（批次 93）
            "   AND COALESCE(json_extract(meta,'$.dupe_of'),'')=''",  # 语义去重副点（批次 94）
            (point_id,),
        ).fetchone()
        if r is None:
            return None
        cons = _consumable("e")
        srcs = self._conn.execute(
            "SELECT e.id AS entry_id,"
            " COALESCE(json_extract(e.meta,'$.display_name'), e.title) AS title,"
            " e.locator"
            " FROM point_sources ps JOIN entries e ON e.id = ps.entry_id"
            " WHERE ps.point_id = ? AND e.status='active'" + cons +
            " ORDER BY ps.created_at LIMIT 6",
            (point_id,),
        ).fetchall()
        if not srcs:
            return None
        return PointHit(r["id"], r["text"], r["summary"],
                        tuple(dict(x) for x in srcs), 1.0)

    # ---- 统计（web /api/stats 用） ----

    def get_stats(self) -> dict[str, Any]:
        by_source = {
            r["source_type"]: r["n"] for r in self._conn.execute(
                "SELECT source_type, COUNT(*) AS n FROM entries"
                " WHERE status='active' GROUP BY source_type"
            )
        }
        uncategorized = self._conn.execute(
            "SELECT COUNT(*) AS n FROM entries e"
            " LEFT JOIN entry_categories ec ON ec.entry_id = e.id"
            " WHERE ec.entry_id IS NULL AND e.status='active'"
        ).fetchone()["n"]
        archived = self._conn.execute(
            "SELECT COUNT(*) AS n FROM entries WHERE status='archived'"
        ).fetchone()["n"]
        contents = self._conn.execute("SELECT COUNT(*) AS n FROM content_store").fetchone()["n"]
        return {"by_source": by_source, "uncategorized": uncategorized,
                "archived": archived, "contents": contents,
                "recent_runs": self.recent_runs(5)}

