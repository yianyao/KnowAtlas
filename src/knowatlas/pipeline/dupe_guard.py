"""点级去重的边界对规则（R30，2026-10-29 工单 `变更工单-2026-10-29-dedupe误并裁定.md`）。

**为什么需要**：`pipeline/embed_index.py::dedup_points` 只看向量余弦（阈值 0.92）。真库实测
（2026-10-29，5,535 点）真重复最低 **0.9174**、误并最高 **0.9607**——区间重叠，阈值分不开；
而「数字/否定词差异就拒绝」会误伤既有 72 对合并里的 **28 对真重复**（`dp[i]` 初始值、不仅…也、
`[1..i-1]`）。所以把两件事拆开：

- 向量只负责**召回候选**（宁多勿漏）；
- 本模块负责**挑出需要裁定的边界对**（也宁多勿漏：多挑一对只多花一次判定，少挑一对就是误并）；
- 裁定交给 `semantic/tasks/point_dupe_judge.py`（或人工），**本模块不做合并决定**。

纪律：纯函数、零 IO、零 LLM、无全局状态；文本按 UTF-8 `str` 处理，空值安全。
"""

from __future__ import annotations

import re

#: 数字 token（整数/小数）。`k=1` / `k=2`、`O(k*2^n)` 的 `2`、`[1..i-1]` 的 `1` 都能抓到。
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")

#: 否定/禁用语（只取单字与常见词组，宁多不宁漏——命中越多判定面越大，成本仍可忽略）。
_NEG_WORDS: tuple[str, ...] = (
    "不", "没", "无", "非", "否", "未", "禁止", "避免", "切勿", "别",
)

#: 长度比阈值：一条是另一条的扩写（如 `dp[i]` 有无「初始值为 1」的补充说明）。
LENGTH_RATIO = 1.5


def _numbers(text: str) -> list[str]:
    return sorted(_NUM_RE.findall(text or ""))


def _negatives(text: str) -> set[str]:
    return {w for w in _NEG_WORDS if w in (text or "")}


def risk_signals(a: str, b: str, *, length_ratio: float = LENGTH_RATIO) -> list[str]:
    """两条点文本的「可能是不同事实」信号；空列表 = 不像，直接按余弦合并。

    三个信号彼此独立，命中任一即应进入裁定；不做「去掉数字/否定词后比对残文」的强规则——
    实测误并对的残文差异也很大（`从数字角度穷举` vs `从桶的角度穷举`），强规则挑不出来。
    """
    ta, tb = str(a or ""), str(b or "")
    out: list[str] = []
    na, nb = _numbers(ta), _numbers(tb)
    if na != nb:
        out.append("数字差异:" + ("+".join(na) or "∅") + "≠" + ("+".join(nb) or "∅"))
    ga, gb = _negatives(ta), _negatives(tb)
    if ga != gb:
        out.append("否定词差异:" + "、".join(sorted(ga ^ gb)))
    la, lb = len(ta), len(tb)
    if la and lb:
        ratio = max(la, lb) / min(la, lb)
        if ratio >= length_ratio:
            out.append(f"长度比{ratio:.2f}")
    return out


def is_risky(a: str, b: str, *, length_ratio: float = LENGTH_RATIO) -> bool:
    """是否需要裁定（= `risk_signals` 非空）。"""
    return bool(risk_signals(a, b, length_ratio=length_ratio))