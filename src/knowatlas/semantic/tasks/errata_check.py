"""errata_check：勘误三级 L2 层——对条目正文做事实一致性核查
（方案 §7.6，0.2.0 第六十四批，Phase 7 批次 65a）。

问「该说法在当前版本是否仍然成立」，结论三值：
- error：确认错误（说法在当前版本已不成立/官方已改）→ 进裁决队列；
- ok：成立 → 否决不再标；
- suspect：疑似但证据不足 → **不进裁决队列**（探针：疑似错误不到确认级
  不出裁决队列——防 LLM 幻觉直接废掉正确知识）。

防幻觉闸门（§7.5 aging 同款口径、§7.6 定稿纪律）：error 结论必须附可核查
依据（官方文档 URL / 具体版本号）；给不出依据自动降级 suspect——宁漏勿误。

降级纪律（与 aging_judge 同构）：ctx.llm 为 None → llm_used=false；
调用失败/输出不可解析 → 返回 error 不写库不阻塞。

签名说明（对 §4.3 SemanticProcessor 批处理签名的 documented exception）：
输入是条目列表（list[dict]），输出是 entry_id → 结论 dict；能力描述以
CapabilitySpec 的 input/output contract 为准（canary 覆盖 name@version）。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="errata_check",
    input_contract={"items": "list[dict]（entry_id/title/body）"},
    output_contract={"verdicts": "dict[entry_id, {verdict: error|ok|suspect, "
                                  "reason, evidence}]",
                     "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="勘误 L2 事实一致性核查：确认错误必须附可核查依据（官方文档/"
                "版本号）否则降级 suspect；llm 不可用静默降级",
)

_VERDICTS = ("error", "ok", "suspect")

_SYSTEM_PROMPT = (
    "你是个人知识库的勘误核查助手。请逐条核查下列知识条目：其中的关键说法在"
    "当前版本（最新正式发布版）是否仍然成立、是否容易误导。\n"
    "规则：\n"
    "1. 只输出 JSON 数组，元素为 {\"i\": 原编号, \"verdict\": \"error\"|\"ok\"|"
    "\"suspect\", \"reason\": \"判定理由\", \"evidence\": \"可核查依据\"}。\n"
    "2. error=确认错误（明确技术事实：API 已移除/官方口径已改/做法已失效），"
    "evidence 必须附可核查依据（官方文档 URL 或具体版本号）；给不出依据不要判 "
    "error。\n"
    "3. ok=成立（说法现行有效；规则信号是误报）。\n"
    "4. suspect=疑似有误但证据不足（如你的知识截止之后才有变更、信息不足）——"
    "宁可 suspect 交人工，不要臆测。\n"
    "5. verdict 只能取三个值之一；必须覆盖全部编号；不要输出 JSON 以外的任何文字。"
)


def _item_line(idx: int, item: dict[str, Any]) -> str:
    parts = [f"{idx}."]
    title = str(item.get("title") or "").strip()
    if title:
        parts.append(f"标题:{title[:80]}")
    body = str(item.get("body") or "").strip()
    parts.append(f"正文:{body[:4000] if body else '（空）'}")
    return " ".join(parts)


def run(items: list[dict[str, Any]], ctx: TaskContext) -> dict[str, Any]:
    """返回 {"verdicts": {entry_id: {verdict, reason, evidence}}, "llm_used": bool}。"""
    if ctx.llm is None or not items:
        return {"verdicts": {}, "llm_used": False}
    user = ("【核查列表】（编号 标题 正文）\n"
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
        evidence = str(x.get("evidence", "")).strip()
        # 防幻觉闸门：error 无可核查依据 → 降级 suspect（不到确认级，不出裁决队列）
        if verdict == "error" and not evidence:
            verdict = "suspect"
            reason = (f"LLM 判 error 但未给出可核查依据，自动降级 suspect"
                      f"（防幻觉闸门）；原理由：{reason}")
        i = int(idx)
        if 1 <= i <= len(items):
            eid = str(items[i - 1].get("entry_id", ""))
            if eid:
                verdicts[eid] = {"verdict": verdict, "reason": reason,
                                 "evidence": evidence}
    if not verdicts:
        return {"verdicts": {}, "llm_used": False,
                "error": "LLM 未返回可解析的结论数组"}
    return {"verdicts": verdicts, "llm_used": True}
