"""point_triage：点级三分诊（P0，2026-10-25 裁决）。

勘误（P1）与老化（P2）要成为常驻机制，先得回答「这条点值不值得判对错/判过时」。
本 task 把点文本贴成三类 + 重复点（`dupe` 由调用方按 meta.dupe_of 直接判，不进 LLM）：

- hard：可判定的硬事实（技术机制、API/代码行为、复杂度、协议与标准、数学定义、
  语言规范、算法性质）——**唯一**进入勘误/老化的集合；
- opinion：观点/主张/经验/方法论/价值判断——没有客观对错；
- unjudgeable：特定系统内部实现细节、未来预测、脱离上下文无法核查。

口径来源：`temp/errata_full.py::TRIAGE_SYS` 的实跑 prompt（2026-10-25 覆盖 4,509 点，
分布 hard 1,579 / opinion 2,016 / unjudgeable 914，与 400 抽样一致），本文件与之逐字一致，
改动 prompt 需重跑分诊并同步本 docstring。

纪律：
- `ctx.llm is None` → `llm_used=false`，不抛异常；
- LLM 故障 → 返回 `error`，调用方整批不写库（不写半成品）；
- 非法 kind 值/越界编号直接丢弃（宁漏勿错）；
- 签名说明（对 §4.3 批处理签名的 documented exception）：输入点列表、输出 point_id → 结论。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="point_triage",
    input_contract={"items": "list[dict]（point_id/text）"},
    output_contract={"kinds": "dict[point_id, {kind: hard|opinion|unjudgeable, why}]",
                     "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="点级三分诊：hard（可判定硬事实，勘误/老化唯一入口）/ opinion（观点方法论）/ "
                "unjudgeable（内部实现·预测·无法核查）——领域闸门的前置",
)

KINDS = ("hard", "opinion", "unjudgeable")

_SYSTEM_PROMPT = (
    "你是知识分诊员。给每条知识贴一个类别：\n"
    "hard = 可判定的硬事实：技术机制、API/代码行为、复杂度、协议与标准、数学定义、"
    "语言规范、算法性质——有客观对错；\n"
    "opinion = 观点/主张/经验/方法论/价值判断——没有客观对错；\n"
    "unjudgeable = 描述某个特定系统的内部实现细节、未来预测、或脱离上下文无法核查。\n"
    "只输出 JSON 数组：[{\"i\":编号,\"kind\":\"hard|opinion|unjudgeable\",\"why\":\"一句话\"}]，"
    "覆盖全部编号，不要输出别的内容。"
)


def _item_line(idx: int, item: dict[str, Any]) -> str:
    return f"{idx}. {str(item.get('text') or '').strip()[:400]}"


def run(items: list[dict[str, Any]], ctx: TaskContext) -> dict[str, Any]:
    """返回 {"kinds": {point_id: {kind, why}}, "llm_used": bool}。"""
    if ctx.llm is None or not items:
        return {"kinds": {}, "llm_used": False}
    user = "\n".join(_item_line(i + 1, it) for i, it in enumerate(items))
    try:
        arr = extract_json_array(ctx.llm.chat(_SYSTEM_PROMPT, user))
    except LlmError as exc:
        return {"kinds": {}, "llm_used": False, "error": str(exc)}
    kinds: dict[str, dict[str, Any]] = {}
    for x in arr:
        idx = x.get("i")
        kind = str(x.get("kind", "")).strip().lower()
        if not str(idx).lstrip("-").isdigit() or kind not in KINDS:
            continue
        i = int(idx)
        if not 1 <= i <= len(items):
            continue
        pid = str(items[i - 1].get("point_id", ""))
        if pid:
            kinds[pid] = {"kind": kind, "why": str(x.get("why", "")).strip()[:200]}
    if not kinds:
        # 合法空结论（全漏判）不算 error：调用方按「未获结论」留待下次；
        # llm_used=True 表示调用成功，仅零结论。
        return {"kinds": {}, "llm_used": True}
    return {"kinds": kinds, "llm_used": True}