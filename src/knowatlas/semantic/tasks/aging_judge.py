"""aging_judge：老化三级 L2 层——对规则判 suspect 的条目做 LLM 时效复核
（方案 §7.5，0.2.0 第六十三批，Phase 7 批次 64a）。

L1 纯规则（semantic/freshness.py）只标记零费用；本任务对 suspect 逐条问
「是否过时 + 理由 + 建议」（batch 20 单次调用，降级纪律同 delta_summarize），
结论三值：
- stale：确证过时 → 升级 freshness_flag=stale（退出消费面）；
- ok：确证不过时（规则误报，如版权年份脚注）→ 否决置 freshness_flag=ok
  （规则此后不再标记，与用户否决同口径）；
- keep：判不了（如 LLM 知识截止之后才发布的新版本）→ 维持 suspect，
  自然下沉到人（与三级设计自洽，方案 §7.5）。

防幻觉纪律（§7.6 勘误同款口径）：stale 结论必须附可核查依据（技术事实/
版本号/官方口径）；给不出依据降级 keep——宁漏勿误，误杀正确知识比漏判
过时危害大。

降级纪律（与 delta_summarize 同构）：ctx.llm 为 None → llm_used=false；
调用失败/输出不可解析 → 返回 error 不写库不阻塞。

签名说明（对 §4.3 SemanticProcessor 批处理签名的 documented exception）：
输入是 suspect 条目列表（list[dict]），输出是 entry_id → 结论 dict；
能力描述以 CapabilitySpec 的 input/output contract 为准（canary 覆盖 name@version）。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="aging_judge",
    input_contract={"items": "list[dict]（entry_id/title/freshness_reason/body）"},
    output_contract={"verdicts": "dict[entry_id, {verdict: stale|ok|keep, reason, suggest}]",
                     "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="对 suspect 条目 LLM 时效复核：确证过时升级 stale（须附可核查依据）/ "
                "规则误报否决 ok / 判不了维持 suspect 下沉人裁；llm 不可用静默降级",
)

_VERDICTS = ("stale", "ok", "keep")

_SYSTEM_PROMPT = (
    "你是个人知识库的时效复核助手。规则层把若干条知识标为「疑似过时」（suspect），"
    "请你逐条复核：该知识在当下是否已过时、是否容易误导。\n"
    "规则：\n"
    "1. 只输出 JSON 数组，元素为 {\"i\": 原编号, \"verdict\": \"stale\"|\"ok\"|\"keep\", "
    "\"reason\": \"判定理由\", \"suggest\": \"一句处理建议（可为空）\"}。\n"
    "2. stale=确证过时（明确技术事实：已被取代/官方停止维护/废弃等），reason 必须"
    "附可核查依据（具体事实、版本号或官方口径）；给不出依据不要判 stale。\n"
    "3. ok=并不过时（规则误报：日期只是页面版权脚注/内容仍现行有效），reason 说明依据。\n"
    "4. keep=无法确证（如你的知识截止之后才有新版本、信息不足）——宁可 keep 交人工"
    "裁决，不要臆测。\n"
    "5. verdict 只能取三个值之一；必须覆盖全部编号；不要输出 JSON 以外的任何文字。"
)


def _item_line(idx: int, item: dict[str, Any]) -> str:
    parts = [f"{idx}."]
    title = str(item.get("title") or "").strip()
    if title:
        parts.append(f"标题:{title[:80]}")
    reason = str(item.get("freshness_reason") or "").strip()
    if reason:
        parts.append(f"规则信号:{reason}")
    body = str(item.get("body") or "").strip()
    parts.append(f"正文:{body[:3000] if body else '（空）'}")
    return " ".join(parts)


def run(items: list[dict[str, Any]], ctx: TaskContext) -> dict[str, Any]:
    """返回 {"verdicts": {entry_id: {verdict, reason, suggest}}, "llm_used": bool}。"""
    if ctx.llm is None or not items:
        return {"verdicts": {}, "llm_used": False}
    user = ("【候选列表】（编号 标题 规则信号 正文）\n"
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
            eid = str(items[i - 1].get("entry_id", ""))
            if eid:
                verdicts[eid] = {"verdict": verdict, "reason": reason,
                                 "suggest": str(x.get("suggest", "")).strip()}
    if not verdicts:
        return {"verdicts": {}, "llm_used": False,
                "error": "LLM 未返回可解析的结论数组"}
    return {"verdicts": verdicts, "llm_used": True}
