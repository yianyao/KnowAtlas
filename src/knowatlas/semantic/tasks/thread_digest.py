"""thread_digest：thread 层跑一次的累积式摘要（完整方案 §9.4，0.2.0 第五十五批）。

定位：给定一条线索/会话线程按时间排序的各轮增量正文，LLM 组织成
「问题 → 关键进展 → 当前结论/待办」结构化摘要。**不拼接各轮摘要**——
它读全量轮次重新组织；各轮「新增了什么」是 delta_summarize 的职责，两者互不依赖。

产物落 threads.digest（迁移 005，组装后的纯文本，节标记行格式），
可作簇节点挂分类树/放射图（视图衔接）。可重复生成=重算覆盖，原始层永在。

降级纪律（与 thread_suggest/delta_summarize 同构，可独立关闭）：
- ctx.llm 为 None → 返回空 digest，llm_used=false（关闭不影响检索与线程视图）；
- LLM 调用失败 → 同样返回空 digest 并带 error，不写库不阻塞。

签名说明（documented exception，同 thread_suggest）：输入是按时间序的轮次列表
+ 线索名，输出是摘要文本 dict。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="thread_digest",
    input_contract={"items": "list[dict]（按时间序：sender/sent_at/title/delta）",
                    "thread_name": "str"},
    output_contract={"digest": "str（问题→关键进展→当前结论/待办，节标记行）",
                     "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="thread 层累积式摘要（问题→关键进展→当前结论/待办），不拼接各轮摘要；"
                "llm 不可用返回空摘要（不影响检索与线程视图）",
)

_SYSTEM_PROMPT = (
    "你是个人知识库的会话总结助手。给定一条会话线程按时间排序的各轮消息"
    "（谁、何时、增量正文），把整条线程组织成累积式摘要，按三节输出：\n"
    "问题（讨论什么）、关键进展（分歧/决策/证据）、当前结论/待办。\n"
    "规则：\n"
    "1. 只输出 JSON 数组，元素为 {\"problem\": \"...\", \"progress\": \"...\","
    " \"conclusion\": \"...\"}，恰好一个元素。\n"
    "2. 每节用简洁段落或「- 」列表行；进度按时间组织，不复述引用。\n"
    "3. 信息不足的节照实短写（如「未见明确结论」）；不要输出 JSON 以外的任何文字。"
)


def _turn_line(idx: int, item: dict[str, Any]) -> str:
    parts = [f"轮次{idx}."]
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
    parts.append(f"增量正文:{delta[:1500] if delta else '（空）'}")
    return " ".join(parts)


def _assemble(body: dict[str, Any]) -> str:
    """LLM 三节 → 带节标记行的纯文本（落库格式；节间空行分隔）。"""
    sections = [("问题", body.get("problem")), ("关键进展", body.get("progress")),
                ("当前结论/待办", body.get("conclusion"))]
    out: list[str] = []
    for head, val in sections:
        text = str(val or "").strip()
        if text:
            out.append(f"【{head}】\n{text}")
    return "\n\n".join(out).strip()


def run(items: list[dict[str, Any]], thread_name: str, ctx: TaskContext) -> dict[str, Any]:
    """返回 {"digest": str, "llm_used": bool}（失败带 error，digest 为空串）。"""
    if ctx.llm is None or not items:
        return {"digest": "", "llm_used": False}
    user = (f"【线程主题】{thread_name}\n\n【轮次列表】\n"
            + "\n".join(_turn_line(i + 1, it) for i, it in enumerate(items)))
    try:
        arr = extract_json_array(ctx.llm.chat(_SYSTEM_PROMPT, user))
    except LlmError as exc:
        return {"digest": "", "llm_used": False, "error": str(exc)}
    if not arr:
        return {"digest": "", "llm_used": False, "error": "LLM 未返回可解析的摘要"}
    digest = _assemble(arr[0])
    if not digest:
        return {"digest": "", "llm_used": False, "error": "LLM 摘要三节全空"}
    return {"digest": digest, "llm_used": True}
