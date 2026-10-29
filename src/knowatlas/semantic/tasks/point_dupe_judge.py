"""point_dupe_judge：点级去重的边界对裁定（R30，2026-10-29 工单 `变更工单-2026-10-29-dedupe误并裁定.md`）。

**为什么要有这一层**：`dedup_points` 的余弦阈值在真库上分不开真重复（最低 0.9174）与误并
（最高 0.9607）——`k=1` vs `k=2`、`碎了` vs `没碎`、`O(k^n)` vs `O(k*2^n)` 这类「同模板不同事实」
余弦 0.92–0.96。规则（`pipeline/dupe_guard.py`）只负责把这类边界对挑出来，本 task 只回答
一个问题：这两条是不是**同一条知识**。

纪律（与 `point_triage` 一致）：
- `ctx.llm is None` → `llm_used=false`，不抛异常，调用方按「未获结论」保守处理（不合并）；
- LLM 故障 → 返回 `error`，调用方整批不写库（不写半成品）；
- 非法编号/非法 `same` 值直接丢弃（宁漏勿错）；
- 签名说明（对 §4.3 批处理签名的 documented exception）：输入对列表、输出 `pair_id → 结论`。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="point_dupe_judge",
    input_contract={"items": "list[dict]（pair_id / a / b）"},
    output_contract={"verdicts": "dict[pair_id, {same: bool, why: str}]",
                     "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="点级去重边界对裁定：只判「两条是否同一条知识」，向量只负责召回候选",
)

#: 单条文本截断（点文本中位 66 字；判定不需要全文，控 prompt 体积）。
_TEXT_MAX = 400

_SYSTEM_PROMPT = (
    "你是知识去重审核员。给你若干对「疑似重复」的知识点，每对两条（A/B）。\n"
    "判断每对是否表达**同一条知识**：\n"
    "- same=true：同一条事实/机制/结论的不同措辞（同义改写、语序调整、"
    "数字只是书写格式差异，例如「[1..i-1] 共 i-1 层」与「i-1 层」、"
    "「dp[i] 初始值为 1」与只写「dp[i] 定义」）；\n"
    "- same=false：两条陈述的事实不同——限定条件不同（k=1 vs k=2、k 为正无穷 vs 固定值）、"
    "分支不同（鸡蛋碎了 vs 没碎）、结论或复杂度不同（O(k^n) vs O(k*2^n)）、肯定与否定相反。\n"
    "只输出 JSON 数组：[{\"i\":编号,\"same\":true|false,\"why\":\"一句话\"}]，"
    "覆盖全部编号，不要输出别的内容。"
)


def _as_bool(value: Any) -> bool | None:
    """宽松解析 `same`（LLM 可能回 true/false/"是"/"否"），无法判定返回 None。"""
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in {"true", "1", "yes", "y", "是", "同一", "同一条"}:
        return True
    if text in {"false", "0", "no", "n", "否", "不同", "不同一"}:
        return False
    return None


def _pair_lines(idx: int, item: dict[str, Any]) -> str:
    a = str(item.get("a") or "").strip()[:_TEXT_MAX]
    b = str(item.get("b") or "").strip()[:_TEXT_MAX]
    return f"{idx}. A: {a}\n   B: {b}"


def run(items: list[dict[str, Any]], ctx: TaskContext) -> dict[str, Any]:
    """返回 {"verdicts": {pair_id: {same, why}}, "llm_used": bool[, "error": str]}。"""
    if ctx.llm is None or not items:
        return {"verdicts": {}, "llm_used": False}
    user = "\n".join(_pair_lines(i + 1, it) for i, it in enumerate(items))
    try:
        arr = extract_json_array(ctx.llm.chat(_SYSTEM_PROMPT, user))
    except LlmError as exc:
        return {"verdicts": {}, "llm_used": False, "error": str(exc)}
    verdicts: dict[str, dict[str, Any]] = {}
    for x in arr:
        idx = x.get("i")
        same = _as_bool(x.get("same"))
        if not str(idx).lstrip("-").isdigit() or same is None:
            continue
        i = int(idx)
        if not 1 <= i <= len(items):
            continue
        pid = str(items[i - 1].get("pair_id", ""))
        if pid:
            verdicts[pid] = {"same": same, "why": str(x.get("why", "")).strip()[:200]}
    if not verdicts:
        # 合法空结论（全漏判）不算 error：调用方按「未获结论」保守不合并；
        # llm_used=True 表示调用成功，仅零结论。
        return {"verdicts": {}, "llm_used": True}
    return {"verdicts": verdicts, "llm_used": True}