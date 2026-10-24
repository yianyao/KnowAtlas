"""批 97a 通用清洗段单测：每条规则 + 双闸门 + 幂等 + 保护。

真实形态取自 `docs/design/样本验证-2026-10-24.md`（页码行 11%、目录点线行 3%、推广尾）。
"""

from __future__ import annotations

from knowatlas.pipeline.clean import (
    PAGE_BREAK,
    CleanThresholds,
    clean_common,
    clean_paged,
    clean_text,
    is_navigation_doc,
    redact,
)

# ---------------------------------------------------------------- 样本构造

def _body(n: int, prefix: str = "第") -> list[str]:
    """生成 n 行互不相同的正文（每行 ≥41 字符，避开所有清洗规则）。"""
    return [f"{prefix}{i}段：这一段是正常知识正文，用来验证清洗规则不会误删有实质内容的行，"
            f"编号 {i} 保证每行都不相同，也不含页码或推广标记。" for i in range(n)]


def _toc_doc() -> str:
    lines = ["智能体设计模式", "构建智能系统实战指南", "Antonio Gulli", "ii", "目录"]
    lines += ["第1章：提示词链 1", "提示词链模式概述 . . . . . . . . . . . . . . . . . 1",
              "提示词链示例 . . . . . . . . . . . . . . . . . . . . . . . 3",
              "第2章：路由模式 15", "路由模式概述 . . . . . . . . . . . . . . . . . . . 15",
              "路由模式示例 . . . . . . . . . . . . . . . . . . . . . . . 18"]
    lines += [""] + _body(45)
    return "\n".join(lines)


# ---------------------------------------------------------------- 页码行

def test_page_numbers_removed_when_ratio_high():
    text = "\n".join(_body(50) + ["12", "13"])
    result = clean_common(text)
    assert result.removed.get("page_number") == 2
    assert "\n12\n" not in result.text + "\n" and "13" not in result.text.splitlines()


def test_page_numbers_kept_when_ratio_low():
    # 100 行正文 + 1 个独立数字 = 1% < 2% 阈值 → 视为数据，不删
    text = "\n".join(_body(100) + ["42"])
    result = clean_common(text)
    assert result.removed.get("page_number") is None
    assert result.text.splitlines()[-1] == "42"


def test_roman_page_numbers_removed():
    text = "\n".join(_body(50) + ["ii", "III", "iv"])
    result = clean_common(text)
    assert result.removed.get("page_number") == 3
    assert not any(line in ("ii", "III", "iv") for line in result.text.splitlines())


def test_short_doc_skips_ratio_rules():
    # 30 行 < min_lines_for_ratio(40)：短文档不猜
    text = "\n".join(_body(28) + ["12", "13"])
    result = clean_common(text)
    assert result.removed.get("page_number") is None
    assert "12" in result.text.splitlines()


def test_table_rows_not_treated_as_page_numbers():
    lines = _body(50) + ["| 12 |", "| 13 |"]
    result = clean_common("\n".join(lines))
    assert result.removed.get("page_number") is None
    assert "| 12 |" in result.text


# ---------------------------------------------------------------- 目录

def test_toc_block_removed():
    result = clean_common(_toc_doc())
    assert result.removed.get("toc_line") == 4
    assert result.removed.get("toc_head") == 1
    assert "目录" not in result.text.splitlines()
    assert "提示词链模式概述" not in result.text
    assert "第1章：提示词链 1" in result.text  # 章标题本身保留


def test_single_dot_leader_not_removed():
    # 只有 1 条点线（< toc_min_dot_leaders=3）→ 不动
    lines = _body(50) + ["这一行有个省略号 . . . . . . . 3"]
    result = clean_common("\n".join(lines))
    assert result.removed.get("toc_line") is None


def test_chinese_ellipsis_without_page_number_kept():
    lines = _body(45) + ["他说：这件事……我没想到。"]
    result = clean_common("\n".join(lines))
    assert "他说：这件事……我没想到。" in result.text


# ---------------------------------------------------------------- 重复页眉页脚

def test_repeated_short_line_keeps_first():
    lines = _body(45)
    for at in (0, 10, 20, 30):
        lines.insert(at, "知道 KnowAtlas")
    result = clean_common("\n".join(lines))
    assert result.removed.get("repeated_line") == 3
    assert result.text.count("知道 KnowAtlas") == 1


def test_repeated_long_line_kept():
    long_line = "这是一条很长的、超过四十个字符的正文行，即使重复出现也不该被当成页眉删掉，因为它更像正文。" * 2
    lines = _body(45)
    for at in (0, 10, 20):
        lines.insert(at, long_line)
    result = clean_common("\n".join(lines))
    assert result.removed.get("repeated_line") is None
    assert result.text.count(long_line) == 3


def test_code_fence_protected():
    code = ["```python", "x = 1", "x = 1", "x = 1", "2", "3", "```"]
    text = "\n".join(_body(50) + code)
    result = clean_common(text)
    assert "x = 1" in result.text
    assert result.text.count("x = 1") == 3
    assert "```python" in result.text


def test_code_tokens_not_treated_as_furniture():
    # 真实形态（Hello-Agents 实测）：`)` 出现 235 次、`}` 180 次、`"""` 216 次
    tokens = [")", "}", '"""', "try:", "else:", "})"] * 20
    text = "\n".join(_body(60) + tokens)
    result = clean_common(text)
    assert result.removed.get("repeated_line") is None
    assert result.text.count(")") >= 20


def test_non_periodic_repeat_kept():
    # 同一行出现 3 次但行距悬殊（35 行 / 1 行）→ 不是页眉，保留
    lines = _body(60)
    for at in (5, 40, 41):
        lines.insert(at, "第三章 记忆与知识")
    result = clean_common("\n".join(lines))
    assert result.removed.get("repeated_line") is None
    assert result.text.count("第三章 记忆与知识") == 3


def test_structural_repeat_skipped():
    # 出现次数超过全篇 2% → 结构性重复（如每章都有的小节名），不动
    lines: list[str] = []
    for i in range(60):
        lines.append(_body(1, prefix=f"第{i}")[0])
        lines.append("小结与要点回顾")
    result = clean_common("\n".join(lines))
    assert result.removed.get("repeated_line") is None
    assert result.text.count("小结与要点回顾") == 60


# ---------------------------------------------------------------- 推广尾

def test_promo_tail_removed():
    tail = ["本文作者：花叔", "公众号：AI 进化论", "知识星球：https://t.zsxq.com/xxx"]
    text = "\n".join(_body(50) + tail)
    result = clean_common(text)
    assert result.removed.get("promo_line") == 2
    assert "公众号" not in result.text
    assert "本文作者：花叔" in result.text  # 不含推广关键词，保留


def test_promo_outside_window_kept():
    # 推广行在开头（不在末尾 25 行窗口内）→ 不动
    text = "\n".join(["公众号：AI 进化论"] + _body(50))
    result = clean_common(text)
    assert result.removed.get("promo_line") is None


def test_promo_cap_applies():
    # 50 行正文，末尾 25 行全塞推广 → 上限 5%（≈2 行）
    promo = [f"公众号推广第{i}条" for i in range(25)]
    text = "\n".join(_body(50) + promo)
    result = clean_common(text)
    assert result.removed.get("promo_line", 0) <= 5


# ---------------------------------------------------------------- 空白与幂等

def test_blank_and_separator_normalized():
    text = "标题\n\n\n\n\n正文第一行\n---\n---\n---\n正文第二行   \n"
    result = clean_common(text)
    assert "\n\n\n" not in result.text
    assert result.text.count("---") == 1
    assert result.text.endswith("正文第二行")


def test_zero_width_removed():
    result = clean_common("正常\ufeff文本\u200b内容")
    assert "\ufeff" not in result.text and "\u200b" not in result.text


def test_idempotent():
    once = clean_common(_toc_doc()).text
    twice = clean_common(once).text
    assert once == twice


# ---------------------------------------------------------------- 闸门与脱敏

def test_abandoned_when_too_aggressive():
    # 10 行正文 + 90 行页码 → 保留率 10% < 90% → 整篇放弃，原文返回
    text = "\n".join(_body(10) + [str(i) for i in range(90)])
    result = clean_common(text, CleanThresholds(page_number_ratio=0.5))
    assert result.abandoned is True
    assert result.text.count("\n") >= 99


def test_redact_sensitive():
    raw = "联系 13812345678 或 a.b@example.com，key sk-abcdefghijklmnopqrst，证件 110101199001011234"
    cleaned, n = redact(raw)
    assert "13812345678" not in cleaned and "[手机]" in cleaned
    assert "a.b@example.com" not in cleaned and "[邮箱]" in cleaned
    assert "sk-abcdefghijklmnopqrst" not in cleaned and "[密钥]" in cleaned
    assert "110101199001011234" not in cleaned and "[证件]" in cleaned
    assert n >= 4


def test_redact_can_be_disabled():
    text = "\n".join(_body(50) + ["电话 13812345678"])
    result = clean_common(text, redact_enabled=False)
    assert "13812345678" in result.text


# ---------------------------------------------------------------- 导航文件

def test_navigation_doc_detected():
    nav = "- [首页](/)\n- [指南](/guide)\n* [API](/api)\n- [关于](/about)"
    assert is_navigation_doc(nav) is True
    result = clean_common(nav)
    assert result.is_navigation is True
    assert result.text == ""


def test_navigation_doc_not_matched_for_prose():
    assert is_navigation_doc("\n".join(_body(5))) is False


def test_empty_text():
    result = clean_common("")
    assert result.text == "" and result.removed == {}


# ---------------------------------------------------------------- 综合

def test_toc_sample_keeps_body_and_reports_ratio():
    result = clean_common(_toc_doc())
    assert result.abandoned is False
    assert result.keep_ratio > 0.90
    assert len(result.text.splitlines()) >= 45  # 45 行正文都还在
    assert result.as_meta()["removed"]["toc_line"] == 4


# ---------------------------------------------------------------- 页边界（97b）

def _paged(pages: list[list[str]]) -> str:
    return PAGE_BREAK.join("\n".join(page) for page in pages)


def _page(n: int, header: str | None = None, footer: str | None = None) -> list[str]:
    lines = [header] if header else []
    lines += _body(n, prefix=f"P{n}-第")
    lines += [footer] if footer else []
    return lines


def test_paged_drops_edge_page_numbers():
    pages = [_page(3, footer=str(i + 1)) for i in range(4)]
    result = clean_paged(_paged(pages))
    assert result.abandoned is False
    assert result.removed.get("page_number_edge") == 4
    for number in ("1", "2", "3", "4"):
        assert f"\n{number}\n" not in f"\n{result.text}\n"


def test_paged_drops_repeated_header():
    pages = [_page(3, header="某某手册 · 内部资料") for _ in range(4)]
    result = clean_paged(_paged(pages))
    assert result.removed.get("page_furniture") == 4
    assert "某某手册" not in result.text


def test_paged_keeps_one_off_top_line():
    """只在某一页顶部出现一次的标题不是页眉，必须保留。"""
    pages = [_page(3), _page(3), _page(3)]
    pages[1][0] = "第二章 路由模式"
    result = clean_paged(_paged(pages))
    assert "第二章 路由模式" in result.text
    assert result.removed.get("page_furniture") is None


def test_paged_strips_page_break_from_output():
    result = clean_paged(_paged([_page(2), _page(2)]))
    assert PAGE_BREAK not in result.text


def test_paged_falls_back_without_page_break():
    text = "\n".join(_body(50))
    paged = clean_paged(text)
    common = clean_common(text)
    assert paged.text == common.text


def test_clean_text_dispatches_on_page_break():
    with_breaks = _paged([_page(3), _page(3), _page(3)])
    assert clean_text(with_breaks).removed.get("page_number_edge") is None  # 无页码时不报
    assert PAGE_BREAK not in clean_text(with_breaks).text
    assert clean_text("\n".join(_body(10))).text == clean_common("\n".join(_body(10))).text


def test_paged_gate_counts_edge_removals():
    """页边删除也算进保留率：删太狠整篇放弃，且放弃时也不能把 \\f 落库。"""
    pages = [[f"页眉 {i}", "正文一行"] for i in range(40)]   # 每页 2 行，页边删除占一半
    result = clean_paged(_paged(pages), thresholds=CleanThresholds(page_edge_lines=1))
    assert result.abandoned is True
    assert PAGE_BREAK not in result.text
