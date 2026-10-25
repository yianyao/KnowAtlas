"""point_errata：点级事实核查（P1，2026-10-25 裁决）。

为什么到点这一层：实测 37 条 wrong 全部是「把机制压成一句口诀」或「把特定实现说成
普遍事实」——一个条目里多数点是对的，条目级标记会连坐整篇（同点级老化裁决 #14）。
本 task 只看**点文本本身**判对错，前提是调用方已按 P0 分诊过滤 `kind=hard`
（opinion/unjudgeable/dupe 一律不判——没有客观对错）。

三值与纪律（复刻 `errata_check` §7.6）：
- wrong：明确错误，**必须**附可核查依据（规范名/版本/官方文档 URL）；给不出 → 降 suspect；
- suspect：可疑或证据不足——**不进裁决队列**，只做筛选视图（不到确认级不出队）；
- ok：成立，否决标记，后续不再标。

原因码 `reason_code`（实测 wrong 三大类）：
- `fact_error`：事实/机制/规格说错；
- `overclaim`：绝对化表述（必须/只能/始终/有且仅有…）且原文未给限定条件；
- `""`：未给出或 ok/suspect。

签名说明（§4.3 documented exception）：输入点列表、输出 point_id → 结论 dict。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="point_errata",
    input_contract={"items": "list[dict]（point_id/text）"},
    output_contract={"verdicts": "dict[point_id, {verdict, reason, evidence, reason_code}]",
                     "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="点级事实核查：hard 点判 wrong/suspect/ok，wrong 必附依据否则降 suspect；"
                "原因码 fact_error / overclaim；只标不删",
)

VERDICTS = ("wrong", "suspect", "ok")
REASON_CODES = ("fact_error", "overclaim")

_SYSTEM_PROMPT = (
    "你是技术事实核查员。逐条判断这段知识有没有硬事实错误。\n"
    "verdict：wrong=明确错误；suspect=可疑/证据不足；ok=成立。\n"
    "wrong 必须写清错在哪（reason）并给可核查依据（规范名/版本/官方文档 URL）；"
    "给不出依据只能判 suspect。\n"
    "reason_code 只对 wrong 使用：fact_error=事实/机制/规格说错；"
    "overclaim=绝对化表述（必须/只能/始终/有且仅有）且原文未给限定条件；"
    "其他情况留空字符串。\n"
    "只输出 JSON 数组：[{\"i\":编号,\"verdict\":\"...\",\"reason\":\"...\","
    "\"evidence\":\"...\",\"reason_code\":\"fact_error|overclaim|\"}]。"
)


def _item_line(idx: int, item: dict[str, Any]) -> str:
    return f"{idx}. {str(item.get('text') or '').strip()[:500]}"


def run(items: list[dict[str, Any]], ctx: TaskContext) -> dict[str, Any]:
    """返回 {"verdicts": {point_id: {verdict, reason, evidence, reason_code}}, "llm_used"}。"""
    if ctx.llm is None or not items:
        return {"verdicts": {}, "llm_used": False}
    user = "\n".join(_item_line(i + 1, it) for i, it in enumerate(items))
    try:
        arr = extract_json_array(ctx.llm.chat(_SYSTEM_PROMPT, user))
    except LlmError as exc:
        return {"verdicts": {}, "llm_used": False, "error": str(exc)}
    verdicts: dict[str, dict[str, Any]] = {}
    for x in arr:
        idx = x.get("i")
        verdict = str(x.get("verdict", "")).strip().lower()
        if not str(idx).lstrip("-").isdigit() or verdict not in VERDICTS:
            continue
        i = int(idx)
        if not 1 <= i <= len(items):
            continue
        reason = str(x.get("reason", "")).strip()
        evidence = str(x.get("evidence", "")).strip()
        code = str(x.get("reason_code", "")).strip().lower()
        if code not in REASON_CODES:
            code = ""
        # 防幻觉闸门：wrong 无可核查依据 → 降 suspect（宁漏勿误，复刻 errata_check）
        if verdict == "wrong" and not evidence:
            verdict = "suspect"
            code = ""
            reason = (reason + "｜LLM 判 wrong 但未给出可核查依据，自动降级 suspect"
                      "（防幻觉闸门）")[:400]
        pid = str(items[i - 1].get("point_id", ""))
        if pid:
            verdicts[pid] = {"verdict": verdict, "reason": reason[:400],
                             "evidence": evidence[:300], "reason_code": code}
    if not verdicts:
        return {"verdicts": {}, "llm_used": True}
    return {"verdicts": verdicts, "llm_used": True}


_CLASSIFY_PROMPT = (
    "你是技术事实核查员。下列每条知识都**已被判定为错误**，并给出了判错理由；"
    "你只需归类错误类型，不要重新判断对错、也不要改写理由。\n"
    "reason_code：fact_error=事实/机制/规格说错；"
    "overclaim=绝对化表述（必须/只能/始终/有且仅有）且原文未给限定条件。\n"
    "只输出 JSON 数组：[{\"i\":编号,\"reason_code\":\"fact_error|overclaim\"}]。"
)


def classify_codes(items: list[dict[str, Any]], ctx: TaskContext) -> dict[str, Any]:
    """只补原因码（P1b 回填）：输入点 + 已有判错理由，输出 {point_id: code}。

    为什么单独一条路径：种子产物只记了 verdict/reason/evidence，没记原因码；
    重跑 `run()` 会把结论重新判一遍（既费钱、又可能把种子结论洗掉）。这里只取
    `reason_code` 一列，verdict/reason/evidence 一律不动。
    非法或缺失码丢弃（调用方留空），宁缺勿滥。
    """
    if ctx.llm is None or not items:
        return {"codes": {}, "llm_used": False}
    lines = []
    for i, it in enumerate(items):
        text = str(it.get("text") or "").strip()[:300]
        reason = str(it.get("reason") or "").strip()[:200]
        lines.append(f"{i + 1}. 点：{text}\n   判错理由：{reason}")
    try:
        arr = extract_json_array(ctx.llm.chat(_CLASSIFY_PROMPT, "\n".join(lines)))
    except LlmError as exc:
        return {"codes": {}, "llm_used": False, "error": str(exc)}
    codes: dict[str, str] = {}
    for x in arr:
        idx = x.get("i")
        code = str(x.get("reason_code", "")).strip().lower()
        if not str(idx).lstrip("-").isdigit() or code not in REASON_CODES:
            continue
        i = int(idx)
        if not 1 <= i <= len(items):
            continue
        pid = str(items[i - 1].get("point_id", ""))
        if pid:
            codes[pid] = code
    return {"codes": codes, "llm_used": True}