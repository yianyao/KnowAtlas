"""知识点自洽性闸门（TODO 8.5，用户裁决 1，2026-10-24）。

点是"能自洽的完整内容"，合格形态只有四种——带论据的观点/结论、概念解释或
术语描述、独立完整的步骤、独立数据。生成层由 `point_extract` 的 prompt 纪律
保证；本模块是**确定性守门**：零费用、可回归，只拦四类硬伤——裸名词、步骤
缺首/跳号/缺尾、省略号截断、代码块未闭合、过短碎片。

设计纪律（宁漏勿误，与清洗层一致）：
- **不判**"一句干巴巴结论" vs "一句完整术语定义"——没有句法分析时两者长度与
  标点完全相同，机器不可分；这一类交给 prompt 纪律 + Phase 8 的 20 点人工抽检；
- 任何一类不确定的疑似不合格都**放行**（阈值保守），误杀代价=一条真知识消失，
  远高于漏放一条待抽检的点；
- 判定只决定"是否落库"，不改写点正文、不写库、无副作用。

原因码（进 `kpoints` 统计与条目 meta.points_gate，便于抽检归因）：
`too_short` / `bare_noun` / `steps_head_missing` / `steps_gap` /
`steps_tail_missing` / `truncated_tail` / `code_fence_unclosed`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 长度下限：只拦空点/碎片。真实"独立数据"通常 ≥12 字，短于此的合格点由
# bare_noun 之外的规则兜（宁可放行，抽样再判）。
MIN_POINT_CHARS = 10

# 句末/分句标点：裸名词判定用（有冒号也算"有结构"，放行）
_PUNCT = "。！？；!?;：:\n"
# 步骤列表的"收尾标点"：比 _PUNCT 严——步骤必须以整句结束
_SENTENCE_END = "。！？；!?;"

# 步骤标记：必须出现在行首或分句标点之后（防 "Gemini 3、Claude 4.8" 这类
# 产品枚举误判）；数字后不能紧跟数字（防 "3.13" / "2026.10" 误判）。
_STEP_MARK = re.compile(
    r"(?:^|[\n；;。:：，,])"
    r"(?:第\s*([一二三四五六七八九十百\d]{1,3})\s*[步条点]"
    r"|[（(]?(\d{1,2})[)）.、](?!\d)"
    r"|([①-⑳]))"
)
_TRUNC_TAIL = re.compile(r"(?:…|\.{3,}|\[截断\]|（略）|\(略\)|此处省略|以下省略)\s*$")

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

GATE_REASONS = ("too_short", "bare_noun", "steps_head_missing", "steps_gap",
                "steps_tail_missing", "truncated_tail", "code_fence_unclosed")


@dataclass(frozen=True)
class GateResult:
    """闸门结论：`ok=False` 时 `reason` 为 GATE_REASONS 之一，`ok=True` 时为空串。"""

    ok: bool
    reason: str = ""


def _step_indexes(text: str) -> list[int]:
    """抽步骤序号（出现顺序）：`1）`/`（2）`/`3.`/`第4步`/`①`；非步骤的 0 丢弃。"""
    out: list[int] = []
    for m in _STEP_MARK.finditer(text):
        raw = m.group(1) or m.group(2)
        if raw:
            out.append(int(raw) if raw.isdigit() else _CN_NUM.get(raw, 0))
        else:  # 圈码 ①..⑳
            out.append(ord(m.group(3)) - ord("①") + 1)
    return [i for i in out if i > 0]


def gate_point(text: str) -> GateResult:
    """复核一个点正文能否作为自洽知识单元落库（纯函数）。

    检查顺序=代价从低到高；`truncated_tail` 先于步骤检查（尾部省略号既可能
    是截断步骤也可能是一般截断，统一按截断处理）。
    """
    t = (text or "").strip()
    if len(t) < MIN_POINT_CHARS:
        return GateResult(False, "too_short")
    if "```" in t and t.count("```") % 2 == 1:
        return GateResult(False, "code_fence_unclosed")
    if _TRUNC_TAIL.search(t):
        return GateResult(False, "truncated_tail")
    steps = _step_indexes(t)
    if len(steps) >= 2:
        if min(steps) > 1:
            return GateResult(False, "steps_head_missing")
        if steps != list(range(steps[0], steps[0] + len(steps))):
            return GateResult(False, "steps_gap")
        if not t.endswith(tuple(_SENTENCE_END)):
            return GateResult(False, "steps_tail_missing")
    if (not any(c in t for c in _PUNCT) and not re.search(r"\d", t)
            and "```" not in t and len(t) < 40):
        # 无标点、无数字、无代码的短串 = 裸名词（"JavaScript 数组"）
        return GateResult(False, "bare_noun")
    return GateResult(True, "")