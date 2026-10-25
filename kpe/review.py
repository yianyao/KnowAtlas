"""复核稿：按章分组，点 + quote + 页码。"""

from __future__ import annotations


def render_review(manifest: dict, points: list[dict],
                  with_sections: bool = False) -> str:
    book = manifest.get("book") or "未命名"
    n = len(points)
    qok = sum(1 for p in points if p.get("quote_ok"))
    model = points[0].get("model") if points else "-"
    lines = [f"# 《{book}》知识点复核", "",
             f"- 块数：{manifest.get('chunk_count')}；点：{n}；"
             f"quote 命中：{qok}/{n}",
             f"- 模型：{model}",
             f"- 源：`{manifest.get('source')}`", ""]
    groups: dict[str, list[dict]] = {}
    for p in sorted(points, key=lambda x: (x.get("chunk_index", 0),)):
        chapter = (p.get("section_path") or "").split(" > ")[0] or "未分章"
        groups.setdefault(chapter, []).append(p)
    for chapter, pts in groups.items():
        lines.append(f"## {chapter}")
        current = None
        idx = 0
        for p in pts:
            if with_sections and p.get("section_path") != current:
                current = p.get("section_path")
                if p.get("page_start"):
                    pages = (f"p{p.get('page_start')}" if p.get("page_start")
                             == p.get("page_end")
                             else f"p{p.get('page_start')}-{p.get('page_end')}")
                    lines.append(f"### {current}（{pages}）")
                else:
                    lines.append(f"### {current}")
                idx = 0
            idx += 1
            lines.append(f"{idx}. {p.get('text')}")
            quote = " ".join((p.get("quote") or "").split())
            if quote:
                mark = "" if p.get("quote_ok") else "  ⚠️quote未命中"
                lines.append(f"   > {quote}{mark}")
        lines.append("")
    return "\n".join(lines)