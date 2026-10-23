"""point_aging：点级老化 L2 复核（批次 93，裁决 #14「只老化确实过时的部分点」）。

输入是「疑似过时信号下沉」的点（其溯源条目被 L1 规则/条目级 L2 标
suspect/stale），LLM 只读**点文本**判定该点本身是否过时——条目过时≠点过时
（条目里可能大部分知识仍现行，裁决 #14 正是打掉整篇连坐）。

结论三值（与 aging_judge 同纪律）：
- stale：点确证过时 → 退出消费面（aging_flag=stale，溯源条目保留）；
- ok：点仍有效 → aging_flag=ok（免疫复扫）；
- keep：判不了 → 只记游标留观（不写 flag，不连坐）。

防幻觉纪律（§7.6 同款）：stale 必须附可核查依据，给不出降级 keep——宁漏勿误。
降级纪律：ctx.llm 为 None → llm_used=false；失败/不可解析 → error 不写库。
签名说明（对 §4.3 SemanticProcessor 批处理签名的 documented exception）：
输入是点列表（list[dict]），输出是 point_id → 结论 dict。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="point_aging",
    input_contract={"items": "list[dict]（point_id/text/entry_signal）"},
    output_contract={"verdicts": "dict[point_id, {verdict: stale|ok|keep, reason}]",
                     "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="对疑似过时点 LLM 复核：确证过时点级 stale（退出消费面，须附依据）/ "
                "仍有效 ok / 判不了 keep 留观；条目过时不连坐点（裁决 #14）",
)

_VERDICTS = ("stale", "ok", "keep")

_SYSTEM_PROMPT = (
    "你是个人知识库的时效复核助手。下面是若干条**知识点**（从文档提炼的整理后知识），"
    "它们所在的来源文档被标了「疑似过时」，但**文档过时不代表每条知识都过时**——"
    "请你逐条只针对知识点本身判断：这条知识在当下是否已过时、是否容易误导。\n"
    "规则：\n"
    "1. 只输出 JSON 数组，元素为 {\"i\": 原编号, \"verdict\": \"stale\"|\"ok\"|\"keep\", "
    "\"reason\": \"判定理由\"}。\n"
    "2. stale=该知识点本身确证过时（明确技术事实：所述 API/版本/口径已被取代或废弃），"
    "reason 必须附可核查依据（具体事实、版本号或官方口径）；给不出依据不要判 stale。\n"
    "3. ok=该知识点仍现行有效（来源文档的过时信号与这条知识无关，如版权年份、"
    "页脚日期），reason 说明依据。\n"
    "4. keep=无法确证（知识截止后才有新版本、信息不足）——宁可 keep 交人工，不要臆测。\n"
    "5. verdict 只能取三个值之一；必须覆盖全部编号；不要输出 JSON 以外的任何文字。"
)


def _item_line(idx: int, item: dict[str, Any]) -> str:
    signal = str(item.get("entry_signal") or "").strip()
    return (f"{idx}. 来源信号:{signal[:120] or '（无）'} "
            f"知识点:{str(item.get('text') or '').strip()[:600]}")


def run(items: list[dict[str, Any]], ctx: TaskContext) -> dict[str, Any]:
    """返回 {"verdicts": {point_id: {verdict, reason}}, "llm_used": bool}。"""
    if ctx.llm is None or not items:
        return {"verdicts": {}, "llm_used": False}
    user = ("【候选知识点列表】\n"
            + "\n".join(_item_line(i + 1, it) for i, it in enumerate(items)))
    try:
        arr = extract_json_array(ctx.llm.chat(_SYSTEM_PROMPT, user))
    except LlmError as exc:
        return {"verdicts": {}, "llm_used": False, "error": str(exc)}
    verdicts: dict[str, dict[str, Any]] = {}
    for x in arr:
        idx = x.get("i")
        verdict = str(x.get("verdict", "")).strip().lower()
        if not str(idx).lstrip("-").isdigit() or verdict not in _VERDICTS:
            continue
        reason = str(x.get("reason", "")).strip()
        # 防幻觉闸门：stale 无可核查依据 → 降级 keep（宁漏勿误）
        if verdict == "stale" and not reason:
            verdict = "keep"
            reason = "LLM 判 stale 但未给出可核查依据，自动降级 keep（防幻觉闸门）"
        i = int(idx)
        if 1 <= i <= len(items):
            pid = str(items[i - 1].get("point_id", ""))
            if pid:
                verdicts[pid] = {"verdict": verdict, "reason": reason}
    if not verdicts:
        # 合法空结论（全漏判）不算 error——调用方按漏判走 keep 留观；
        # llm_used=True 表示调用成功，仅零结论。
        return {"verdicts": {}, "llm_used": True}
    return {"verdicts": verdicts, "llm_used": True}
