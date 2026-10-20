"""thread_suggest：LLM 建议线索初始排序（完整方案 §9.4，0.2.0 第三十二批）。

定位：用户把跨源条目串成一条线索后，「先看什么后看什么」交给 LLM 给初始建议
（概念 → 步骤 → 注意事项），用户可调——建议只落 position，不锁死编辑。

降级纪律（与 Phase 4「关闭 LLM 后系统仍可运行」同构）：
- ctx.llm 为 None（未启用 / key 未设）→ 按原序返回，llm_used=false；
- LLM 调用失败（网络/限流/结构异常）→ 同样按原序返回并带 error，绝不阻塞保存。

签名说明（对 §4.3 SemanticProcessor 批处理签名的 documented exception）：
输入是线索条目集（list[dict]）+ 线索名，输出是建议顺序 dict；
能力描述以 CapabilitySpec 的 input/output contract 为准（canary 覆盖 name@version）。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="thread_suggest",
    input_contract={"items": "list[dict]（entry_id/title/body/native_path）",
                    "thread_name": "str"},
    output_contract={"order": "list[entry_id]（建议顺序，覆盖全部条目）",
                     "rationale": "str（逐位理由，可空）", "llm_used": "bool"},
    version="1.0.0",
    description="LLM 建议线索初始排序（概念→步骤→注意事项）；llm 不可用按原序降级，不阻塞",
)

_SYSTEM_PROMPT = (
    "你是个人知识库的阅读路径规划助手。给定一个主题线索及其条目（编号、标题、摘要），"
    "按「概念 → 步骤 → 注意事项」的学习顺序重排。\n"
    "规则：\n"
    "1. 只输出 JSON 数组，元素为 {\"i\": 原编号, \"why\": 一句话理由}，按建议顺序排列。\n"
    "2. 必须包含全部编号，不重复不遗漏；拿不准时保持原序。\n"
    "3. 不要输出 JSON 以外的任何文字。"
)


def _entry_line(idx: int, item: dict[str, Any]) -> str:
    parts = [f"{idx}. 标题:{str(item.get('title', ''))[:60]}"]
    body = str(item.get("body") or "").strip()
    if body:
        parts.append(f"摘要:{body[:100]}")
    native = str(item.get("native_path") or "").strip()
    if native:
        parts.append(f"路径:{native[:60]}")
    return " | ".join(parts)


def run(items: list[dict[str, Any]], thread_name: str, ctx: TaskContext) -> dict[str, Any]:
    """返回 {"order": [...], "rationale": str, "llm_used": bool}（失败带 error）。"""
    order = [str(it.get("entry_id", "")) for it in items]
    if ctx.llm is None or not items:
        return {"order": order, "rationale": "", "llm_used": False}
    user = (f"【线索主题】{thread_name}\n\n【条目列表】\n"
            + "\n".join(_entry_line(i + 1, it) for i, it in enumerate(items)))
    try:
        arr = extract_json_array(ctx.llm.chat(_SYSTEM_PROMPT, user))
    except LlmError as exc:
        return {"order": order, "rationale": "", "llm_used": False, "error": str(exc)}
    by_idx: dict[int, str] = {}
    for x in arr:
        idx = x.get("i")
        if str(idx).lstrip("-").isdigit():
            by_idx[int(idx)] = str(x.get("why", ""))
    # 按 LLM 数组顺序（= 建议顺序）收集；漏号/越界/重复号按原序补齐（不丢条目）
    final: list[str] = []
    notes: list[str] = []
    used: set[int] = set()
    for x in arr:
        idx = x.get("i")
        if not str(idx).lstrip("-").isdigit():
            continue
        i = int(idx)
        if not (1 <= i <= len(items)) or i in used:
            continue
        final.append(str(items[i - 1].get("entry_id", "")))
        if by_idx.get(i):
            notes.append(f"#{i} {by_idx[i]}")
        used.add(i)
    for i, it in enumerate(items, 1):  # LLM 漏号 → 按原序补齐（不丢条目）
        if i not in used:
            final.append(str(it.get("entry_id", "")))
    return {"order": final, "rationale": "；".join(notes), "llm_used": True}
