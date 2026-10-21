"""delta_summarize：对 quote_strip 剥出的增量正文压缩为 1-3 句「本轮新增了什么」
（完整方案 §9.4，0.2.0 第五十五批）。

定位：邮件/AI 会话多轮消息正文大量重复引用，quote_strip（规则，不调 LLM）已剥出
增量正文落 entries.inline_content；本任务把增量正文再压缩为 1-3 句摘要，
产物落 entries.meta.delta_summary（原文指针保留——摘要只是压缩表示，原始层永在，
剥错/摘错也不丢信息）。

降级纪律（与 thread_suggest 同构，可独立关闭）：
- ctx.llm 为 None（未启用 / key 未设）→ 返回空 summaries，llm_used=false；
- LLM 调用失败（网络/限流/结构异常）→ 同样返回空 summaries 并带 error，
  不写库不阻塞——线程视图照常显示原始增量正文。

签名说明（对 §4.3 SemanticProcessor 批处理签名的 documented exception）：
输入是增量条目列表（list[dict]），输出是 entry_id → 摘要 dict；
能力描述以 CapabilitySpec 的 input/output contract 为准（canary 覆盖 name@version）。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="delta_summarize",
    input_contract={"items": "list[dict]（entry_id/title/delta/sender/sent_at）"},
    output_contract={"summaries": "dict[entry_id, str]（1-3 句「本轮新增了什么」）",
                     "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="对 quote_strip 剥出的增量正文压缩为 1-3 句「本轮新增了什么」；"
                "llm 不可用静默降级（原始增量正文永在，摘要是压缩表示）",
)

_SYSTEM_PROMPT = (
    "你是个人知识库的会话摘要助手。给定一次多轮会话中若干条消息的**增量正文**"
    "（已剥离历史引用，即该轮真正新增的内容），逐条压缩为 1-3 句「本轮新增了什么」。\n"
    "规则：\n"
    "1. 只输出 JSON 数组，元素为 {\"i\": 原编号, \"summary\": \"1-3 句摘要\"}。\n"
    "2. 摘要只说该轮新增的信息（结论/数据/承诺/变更），不复述引用内容。\n"
    "3. 增量正文过短或无实义时，summary 照实短写（如「仅确认收到，无新信息」）。\n"
    "4. 必须覆盖全部编号；不要输出 JSON 以外的任何文字。"
)


def _item_line(idx: int, item: dict[str, Any]) -> str:
    parts = [f"{idx}."]
    sender = str(item.get("sender") or "").strip()
    if sender:
        parts.append(f"谁:{sender[:40]}")
    sent = str(item.get("sent_at") or "").strip()
    if sent:
        parts.append(f"何时:{sent[:30]}")
    title = str(item.get("title") or "").strip()
    if title:
        parts.append(f"标题:{title[:60]}")
    delta = str(item.get("delta") or "").strip()
    parts.append(f"增量正文:{delta[:1200] if delta else '（空）'}")
    return " ".join(parts)


def run(items: list[dict[str, Any]], ctx: TaskContext) -> dict[str, Any]:
    """返回 {"summaries": {entry_id: 摘要}, "llm_used": bool}（失败带 error）。"""
    if ctx.llm is None or not items:
        return {"summaries": {}, "llm_used": False}
    user = ("【消息列表】（编号 谁何时 标题 增量正文）\n"
            + "\n".join(_item_line(i + 1, it) for i, it in enumerate(items)))
    try:
        arr = extract_json_array(ctx.llm.chat(_SYSTEM_PROMPT, user))
    except LlmError as exc:
        return {"summaries": {}, "llm_used": False, "error": str(exc)}
    summaries: dict[str, str] = {}
    for x in arr:
        idx = x.get("i")
        text = str(x.get("summary", "")).strip()
        if not str(idx).lstrip("-").isdigit() or not text:
            continue
        i = int(idx)
        if 1 <= i <= len(items):
            eid = str(items[i - 1].get("entry_id", ""))
            if eid:
                summaries[eid] = text
    if not summaries:
        return {"summaries": {}, "llm_used": False,
                "error": "LLM 未返回可解析的摘要数组"}
    return {"summaries": summaries, "llm_used": True}
