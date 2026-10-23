"""synthesize：知识梳理合成层（批次 69，方案 §7.9 用户裁决「回灌+隔离」）。

用户勾选若干知识点 → 可修改的提示词 → LLM 生成整理后的方案文档（Markdown）
→ 预览（不落库）→ 人确认后落为 source_type=synthesized 独立条目回灌知识库。

裁决纪律：
- 生成物**回灌**：synthesized 条目 active 可检索、可参与聚类——但与原始层
  **隔离**（source_type 独立标识，前端显式「合成」徽标，不混入原始源统计）；
- **强制溯源**：条目 meta.sources=[point_id...]（防幻觉闸门同款：无溯源不出库，
  API 层校验空 sources 拒绝落库）；
- 生成内容一律 Markdown、简体中文（命令/代码/API 名/版本号保留原文）；
- 只基于所选知识点梳理，不编造所选点之外的内容（防幻觉写进 system prompt）；
- 全自动重排固化、AI 配图明确不做（§7.9 边界）。
"""

from __future__ import annotations

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_object
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="synthesize",
    input_contract={"items": "list[dict]（point_id/text/summary/source_title）",
                    "instruction": "str（用户提示词，可空走默认）"},
    output_contract={"markdown": "str", "llm_used": "bool", "error": "str（可空）"},
    version="1.0.0",
    description="知识梳理合成：勾选知识点 → LLM 生成整理后的 Markdown 方案文档；"
                "只基于所选点不编造；回灌 synthesized 条目+强制溯源",
)

# 提示词面板预填默认模板（用户可改后提交；§7.9 设计 3）
DEFAULT_INSTRUCTION = (
    "请将下列知识点梳理成一篇结构化的方案文档（Markdown）："
    "提炼共性、归并重复、按主题组织小节；操作类知识给出步骤，"
    "概念类知识给出解释脉络；末尾附「来源知识点」一节列出要点索引。"
    "只基于给定知识点梳理，不要引入它们之外的内容。"
)

_SYSTEM_PROMPT = (
    "你是个人知识库的梳理助手。用户从库里勾选了若干**知识点**，请你把它们梳理成"
    "一篇整理后的方案文档。要求：\n"
    "1. 只输出 JSON 对象：{\"markdown\": \"完整的 Markdown 文档\"}。\n"
    "2. **只基于给定的知识点**梳理：提炼、归纳、组织、衔接；知识点里没有的内容"
    "不要编造，不联网，不虚构出处。\n"
    "3. 输出为规范的 Markdown（# 标题 / 小节 / 列表 / 代码块）；全部简体中文，"
    "命令/代码/API 名/版本号/专有名词保留原文。\n"
    "4. 忠实保留各知识点的关键信息，允许归并重复、调整组织，不允许丢要点。"
)


def run(items: list[dict], ctx: TaskContext,
        instruction: str = "") -> dict[str, str | bool]:
    """合成 Markdown 文档；返回 {"markdown", "llm_used"}。

    items 每项 {point_id, text, summary?, source_title?}；instruction 为用户在
    提示词面板修改后的要求（空则用 DEFAULT_INSTRUCTION）。预览/落库均走本任务，
    落库由 API 层在人确认后执行（预览不写库）。
    """
    clean = [it for it in items if str(it.get("text") or "").strip()]
    if ctx.llm is None or not clean:
        return {"markdown": "", "llm_used": False}
    req = (instruction or "").strip() or DEFAULT_INSTRUCTION
    lines = []
    for i, it in enumerate(clean, 1):
        src = str(it.get("source_title") or "").strip()
        line = f"{i}. {str(it['text']).strip()[:2000]}"
        if src:
            line += f"（来源：《{src}》）"
        lines.append(line)
    user = f"【梳理要求】\n{req[:2000]}\n\n【知识点清单】\n" + "\n".join(lines)
    try:
        obj = extract_json_object(ctx.llm.chat(_SYSTEM_PROMPT, user))
    except LlmError as exc:
        return {"markdown": "", "llm_used": False, "error": str(exc)}
    markdown = str(obj.get("markdown", "")).strip()
    if not markdown:
        return {"markdown": "", "llm_used": False, "error": "LLM 未返回文档内容"}
    return {"markdown": markdown, "llm_used": True}
