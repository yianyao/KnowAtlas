"""point_explain：大白话释疑（批次 90，方案 §9：点卡片 → LLM 解释+示例）。

用户读到一个知识点但不懂时，点「💬 释疑」按钮——LLM 用大白话解释这条知识
并给上手示例，结果缓存在点 meta（explain 字段），重复释疑零费用。

纪律：
- 输出全部简体中文；命令/代码/API 名/版本号/专有名词保留原文（中文优先裁决）；
- 解释**只基于该知识点文本本身**展开，不联网（本地 LlmClient 无搜索工具——
  诚实口径：模型自身知识解释，不编造来源）；知识文本里没有的细节不脑补；
- 签名说明：单点输入（dict）非批处理——释疑是用户逐点触发的交互动作，
  批量化无意义（documented exception，同 point_extract 口径）。
"""

from __future__ import annotations

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_object
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="point_explain",
    input_contract={"point": "dict（point_id/text/summary）"},
    output_contract={"explanation": "str", "examples": "str", "llm_used": "bool",
                     "error": "str（可空）"},
    version="1.0.0",
    description="知识点大白话释疑：解释这条知识在讲什么+给一个上手示例；"
                "简体中文，术语保留原文；只基于点文本不联网不脑补",
)

_SYSTEM_PROMPT = (
    "你是个人知识库的释疑助手。用户给你一条从文档提炼出的**知识点**，他没看懂，"
    "请你用大白话解释。要求：\n"
    "1. 只输出 JSON 对象：{\"explanation\": \"大白话解释\", \"examples\": \"上手示例\"}。\n"
    "2. explanation：用初中生能听懂的话讲清这条知识在说什么、为什么重要、"
    "和什么场景有关；不要堆砌术语；**只围绕知识点文本本身**，文本里没有的细节不要编。\n"
    "3. examples：给一个具体的小例子或类比（能上手最好；命令/代码/API 名/版本号/"
    "专有名词保留原文）；知识点是操作类就给操作示例，概念类就给类比。\n"
    "4. 全部用简体中文；不要输出 JSON 以外的任何文字；不要编造出处或联网信息。"
)


def run(point: dict, ctx: TaskContext) -> dict[str, str | bool]:
    """返回 {"explanation", "examples", "llm_used"}；LLM 不可用/失败 → llm_used=False。"""
    text = str(point.get("text") or "").strip()
    if ctx.llm is None or not text:
        return {"explanation": "", "examples": "", "llm_used": False}
    summary = str(point.get("summary") or "").strip()
    user = f"【知识点】{text[:2000]}" + (f"\n【点摘要】{summary[:400]}" if summary else "")
    try:
        obj = extract_json_object(ctx.llm.chat(_SYSTEM_PROMPT, user))
    except LlmError as exc:
        return {"explanation": "", "examples": "", "llm_used": False,
                "error": str(exc)}
    explanation = str(obj.get("explanation", "")).strip()
    examples = str(obj.get("examples", "")).strip()
    if not explanation:
        return {"explanation": "", "examples": "", "llm_used": False,
                "error": "LLM 未返回解释内容"}
    return {"explanation": explanation, "examples": examples, "llm_used": True}
