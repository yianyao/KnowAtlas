"""point_lifecycle：退场型老化判定（P2，2026-10-26 工单 `P2点级老化两型`）。

为什么按**技术栈分组**而不是逐点：判的是「这套技术/产品还在不在被维护」——同一技术下
几十个点答案是同一个，逐点判等于把同一笔钱付几十遍；分组的代价是结论共享，
所以必须附**官方依据**（弃用公告 URL / 版本与日期），给不出只能 keep（宁漏勿误）。

三值（与 point_aging 同纪律）：
- retired：已停止维护或被官方弃用 → 调用方落点级 stale（退出消费面，不删）；
- active：仍在维护；
- keep：判不了（信息不足/只有社区印象）——不落 stale，交人工。

签名说明（§4.3 documented exception）：输入技术列表，输出 tech → 结论 dict。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="point_lifecycle",
    input_contract={"items": "list[dict]（tech/sample）"},
    output_contract={"verdicts": "dict[tech, {verdict: retired|active|keep, evidence}]",
                     "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="退场型老化：按技术栈判「是否已停止维护」，retired 必附官方依据否则降 keep；"
                "只标不删，与版本型 EOL 表互补",
)

_VERDICTS = ("retired", "active", "keep")

_SYSTEM_PROMPT = (
    "你是技术选型的时效判断助手。下面列出若干技术/产品名，每项附一条来自知识库的"
    "上下文片段（可能只是提及，不要被片段带偏）。请逐项判断：这项技术在**当下**"
    "是否已停止维护、或已官方宣布弃用/退役。\n"
    "规则：\n"
    "1. 只输出 JSON 数组，元素为 {\"i\": 原编号, \"verdict\": \"retired\"|\"active\"|\"keep\", "
    "\"evidence\": \"可核查依据\"}。\n"
    "2. retired=确证已停止维护/官方弃用；evidence 必须写官方依据（弃用公告、EOL 页面 URL、"
    "或明确的版本号与日期）。给不出官方依据就不要判 retired。\n"
    "3. active=仍在维护（仍在发版或官方明确支持），evidence 可写官方版本页/发布记录。\n"
    "4. keep=无法确证（知识不足、只有社区印象、或该名称含义不明）——宁可 keep，不要臆测。\n"
    "5. 必须覆盖全部编号；不要输出 JSON 以外的任何文字。"
)


def _item_line(idx: int, item: dict[str, Any]) -> str:
    sample = str(item.get("sample") or "").strip().replace("\n", " ")[:160]
    return f"{idx}. {str(item.get('tech') or '').strip()}｜上下文：{sample or '（无）'}"


def run(items: list[dict[str, Any]], ctx: TaskContext) -> dict[str, Any]:
    """返回 {"verdicts": {tech: {verdict, evidence}}, "llm_used": bool}。"""
    if ctx.llm is None or not items:
        return {"verdicts": {}, "llm_used": False}
    user = "\n".join(_item_line(i + 1, it) for i, it in enumerate(items))
    try:
        arr = extract_json_array(ctx.llm.chat(_SYSTEM_PROMPT, user))
    except LlmError as exc:
        return {"verdicts": {}, "llm_used": False, "error": str(exc)}
    verdicts: dict[str, dict[str, str]] = {}
    for x in arr:
        idx = x.get("i")
        verdict = str(x.get("verdict", "")).strip().lower()
        if not str(idx).lstrip("-").isdigit() or verdict not in _VERDICTS:
            continue
        i = int(idx)
        if not 1 <= i <= len(items):
            continue
        tech = str(items[i - 1].get("tech") or "").strip()
        if not tech:
            continue
        evidence = str(x.get("evidence", "")).strip()[:300]
        # 防幻觉闸门：retired 无可核查依据 → 降 keep（宁漏勿误，同 point_aging）
        if verdict == "retired" and not evidence:
            verdict = "keep"
            evidence = "LLM 判 retired 但未给出官方依据，自动降级 keep（防幻觉闸门）"
        verdicts[tech] = {"verdict": verdict, "evidence": evidence}
    return {"verdicts": verdicts, "llm_used": True}