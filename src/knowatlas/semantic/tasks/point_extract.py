"""point_extract：知识点抽取的 LLM 层——形态判定 + 切点（方案 §7.1，批次 61a）。

流水线（用户裁决第 3 条）：每个载体条目先判形态——
- integral（整条即点）：方案、论证、单主题文档 → 整条一个点；
- split（集合型切点）：参考集、多主题清单、讨论记录 → 切 2-8 个自包含点。
判定与切点合并为**单次调用**（实现口径：两步一请求省一半费用；判定理由必落
meta.judge_reason 供抽检——SOP §7.7 总纪律第 2 条）。

降级纪律（与 delta_summarize 同构，可独立关闭）：
- ctx.llm 为 None（未启用 / key 未设）或条目无正文 → llm_used=false 不产出；
- LLM 调用失败（网络/限流/结构异常）→ 返回 llm_used=false + error，由调用方
  （pipeline/points.py）记 error 继续下一条，绝不阻塞、绝不臆造。

签名说明（对 §4.3 SemanticProcessor 批处理签名的 documented exception）：
输入是单条目（dict）——形态判定是条目级信号，批量会混淆理由归属；输出判定
+点列表。能力描述以 CapabilitySpec 的 input/output contract 为准
（canary 覆盖 name@version）。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ..llm import LlmError, extract_json_object
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="point_extract",
    input_contract={"item": "dict（entry_id/title/source_type/body）"},
    output_contract={"judge": "integral|split", "reason": "一句话判定理由",
                     "summary": "整条一句话摘要", "points": "list[{text, summary}]",
                     "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="知识点抽取：先判 integral（整条即点）/split（集合型切点）再切点，"
                "判定理由随产出落 meta 抽检；llm 不可用静默降级（原文永在）",
)

_MAX_POINTS = 8  # split 切点硬上限（防 LLM 失控刷点）

_SYSTEM_PROMPT = (
    "你是个人知识库的知识点抽取助手。给定一个知识条目（标题+正文），先做形态判定，"
    "再按形态产出知识点。\n"
    "形态定义：\n"
    "- integral（整条即点）：方案、论证、报告、单主题完整文档——内容是一个不可拆的"
    "整体观点/方案，拆开会失真；\n"
    "- split（集合型切点）：参考集、多主题清单、讨论记录、问答合集——包含多个各自"
    "独立、可单独复用的知识点。\n"
    "规则：\n"
    '1. 只输出 JSON 对象：{"judge":"integral"或"split","reason":"一句话判定理由",'
    '"summary":"整条一句话摘要","points":[{"text":"点正文","summary":"一句话摘要"}]}。\n'
    "2. judge=integral 时 points 只给一个元素：text=结构化压缩正文（保留关键结论/"
    "步骤/数据/命令，≤800 字），不是逐字复制。\n"
    "3. judge=split 时 points 给 2-8 个点：每个点自包含（脱离原文可独立阅读，"
    "补齐必要主语与背景），text≤500 字；保留原文的命令/代码/数字/版本号等硬信息；"
    "寒暄、导航句、跨点重复内容丢弃。\n"
    "4. 点的边界=一个独立可复用的知识点；拿不准切不切时倾向切出并各给足背景。\n"
    "5. 不要输出 JSON 以外的任何文字。"
)


def _user_prompt(item: dict[str, Any], body: str) -> str:
    parts = [f"来源类型:{item.get('source_type', '')}",
             f"标题:{str(item.get('title') or '')[:100]}",
             f"正文:\n{body}"]
    return "\n".join(parts)


def run(item: dict[str, Any], ctx: TaskContext) -> dict[str, Any]:
    """返回 {"judge","reason","summary","points","llm_used"}（失败带 error）。

    points 恒为 list[{text, summary}]：integral 归一为单元素列表，调用方无需分支。
    """
    empty = {"judge": "", "reason": "", "summary": "", "points": [], "llm_used": False}
    body = str(item.get("body") or "").strip()
    if ctx.llm is None or not body:
        return empty
    try:
        obj = extract_json_object(ctx.llm.chat(_SYSTEM_PROMPT,
                                               _user_prompt(item, body)))
    except LlmError as exc:
        return {**empty, "error": str(exc)}
    judge = str(obj.get("judge", "")).strip()
    if judge not in ("integral", "split"):
        return {**empty, "error": f"LLM 形态判定非法：{judge!r}"}
    raw_points = obj.get("points")
    if not isinstance(raw_points, list) or not raw_points:
        return {**empty, "error": "LLM 未返回任何点"}
    points: list[dict[str, str]] = []
    for p in raw_points[:_MAX_POINTS]:
        if not isinstance(p, dict):
            continue
        text = str(p.get("text", "")).strip()
        if not text:
            continue
        points.append({"text": text,
                       "summary": str(p.get("summary", "")).strip()})
    if not points:
        return {**empty, "error": "LLM 返回的点全部为空"}
    return {"judge": judge,
            "reason": str(obj.get("reason", "")).strip(),
            "summary": str(obj.get("summary", "")).strip(),
            "points": points,
            "llm_used": True}
