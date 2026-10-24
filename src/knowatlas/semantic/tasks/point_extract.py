"""point_extract：知识提炼的 LLM 层——形态判定 + 提炼产出（批次 92 重写，v2）。

批次 92 用户裁决（2026-10-23）：**入库=知识整理，不是切片复制**。点正文必须是
LLM 通读全文后整理出的知识文本（合并同类、剔除寒暄/口号/导航废话、保留命令/
代码/数字/版本号等硬信息），不是原文照抄或按段落机械切分；每点附 quote（原文
逐字引句）作溯源锚点——链接与原文保留以溯源，但产出必须是知识。

流水线（用户裁决第 3 条）：每个载体条目先判形态——
- integral（整条即点）：方案、论证、报告、单主题完整文档 → 一个点的完整知识陈述；
- split（集合型切点）：参考集、多主题清单、讨论记录、问答合集 → 2-8 个自包含点。
三种入口（forced_judge 由规则管线预判，省判定 token 且判定不再可能误切）：
- forced_judge="integral" → _INTEGRAL_REFINE_PROMPT（不判定，直接提炼单点）；
- forced_judge="split" → _SPLIT_ONLY_PROMPT（不判定，直接提炼切点）；
- 无 forced（杂烩目录）→ _SYSTEM_PROMPT（判定+提炼合一）。

纪律（62 批教训固化）：**宁全勿碎**——相邻内容同属一个观点必须合并，按段落/
章节/脑图节点机械切分是错误做法；点的边界=一个独立可复用的知识点。

降级纪律（与 delta_summarize 同构，可独立关闭）：
- ctx.llm 为 None（未启用 / key 未设）或条目无正文 → llm_used=false 不产出；
- LLM 调用失败（网络/限流/结构异常）→ 返回 llm_used=false + error，由调用方
  （pipeline/points.py）记 error 继续下一条，绝不阻塞、绝不臆造。

签名说明（对 §4.3 SemanticProcessor 批处理签名的 documented exception）：
输入是单条目（dict）——形态判定是条目级信号，批量会混淆理由归属；输出判定
+点列表。能力描述以 CapabilitySpec 的 input/output contract 为准。
"""

from __future__ import annotations

from typing import Any

from ...registry.capability import CapabilitySpec
from ..llm import LlmError, extract_json_object
from ..base import TaskContext

SPEC = CapabilitySpec(
    name="point_extract",
    input_contract={"item": "dict（entry_id/title/source_type/body/forced_judge?）"},
    output_contract={"judge": "integral|split", "reason": "一句话判定理由",
                     "summary": "整条一句话摘要",
                     "points": "list[{text, summary, quote?}]（可为空：确认无可独立成点的知识）",
                     "llm_used": "bool", "error": "str（可空）"},
    version="2.1.0",
    description="知识提炼（批次 92，裁决 12：入库=知识整理不是切片）：通读全文"
                "归纳为整理后的知识点，quote 留原文锚点；自洽性纪律（8.5）禁裸名词/"
                "残缺步骤、允许零产出；llm 不可用静默降级",
)

_MAX_POINTS = 8  # split 切点硬上限（防 LLM 失控刷点）

_REFINE_RULES = (
    "提炼规则（用户裁决 2026-10-23：入库=知识整理，产出必须是知识）：\n"
    "- **全部用简体中文输出**（用户裁决补充 2026-10-23：中文优先）——原文为英文等"
    "外语时译写为中文整理；命令/代码/API 名/版本号/专有名词/书名保留原文不译；\n"
    "- text 必须是**整理后的知识文本**：通读归纳后用整理过的语言重写——合并同类"
    "信息、剔除寒暄/口号/导航句/广告/重复表述；命令/代码/数字/版本号/结论等"
    "硬信息原样保留；\n"
    "- 相邻内容同属一个观点时必须合并——宁全勿碎，按段落/章节机械切分是错误做法；"
    "同一知识只产出一个点，不得在不同点里重复；\n"
    "- 每点带 quote：从原文逐字摘引一句能定位该点的原句（≤60 字），供溯源定位。"
)

# 自洽性纪律（TODO 8.5，用户裁决 1，2026-10-24）：点是"能自洽的完整内容"，
# 不是名词碎片或截断片段。三份 prompt 共用同一段（生成层），确定性守门在
# pipeline/point_gate.py（入库层）——两层口径必须一致，改这里要同步那边。
_SELF_CONSISTENCY_RULES = (
    "自洽性纪律（用户裁决 2026-10-24：每个点必须能脱离原文独立读懂）：\n"
    "- 只允许四种合格形态：带论据的观点/结论、概念解释或术语描述、"
    "独立完整的步骤、独立数据；\n"
    "- 禁裸名词（如「JavaScript 数组」不是点）：概念点必须带解释"
    "（是什么/怎么用/为什么），至少是一句有主谓的完整表述；\n"
    "- 禁无支撑的单句结论：观点要带理由、条件或例子，否则并入相邻点；\n"
    "- 步骤必须首尾完整、编号连续（第 1 步到最后一步）；原文本身残缺时只陈述"
    "可确认的内容，不得把中间步骤包装成完整流程；代码块必须闭合；\n"
    "- 独立数据必须带口径（条件/单位/来源）；\n"
    "- 一个文件只产出 1 个合格点是合法输出，不得为凑数碎切；确认没有可独立"
    "成点的知识时，points 输出空数组 []。"
)

_SYSTEM_PROMPT = (
    "你是个人知识库的知识提炼助手。给定一个知识条目（标题+正文），先通读全文"
    "理解内容，再做形态判定，最后产出整理后的知识——不是复制原文。\n"
    "形态定义：\n"
    "- integral（整条即点）：方案、论证、报告、单主题完整文档——内容围绕一个"
    "主题/方案展开，拆开会支离破碎；\n"
    "- split（集合型切点）：参考集、多主题清单、讨论记录、问答合集——包含多个"
    "各自独立、可单独复用的知识点。\n"
    "规则：\n"
    '1. 只输出 JSON 对象：{"judge":"integral"或"split","reason":"一句话判定理由",'
    '"summary":"整条一句话摘要","points":[{"text":"整理后的知识文本",'
    '"summary":"一句话摘要","quote":"原文逐字引句"}]}。\n'
    "2. judge=integral 时 points 只给一个元素：该主题的完整知识陈述（≤800 字，"
    "保留原文结构脉络：背景→方案→关键决策→结论），绝不逐字照抄。\n"
    "3. judge=split 时 points 给 2-8 个点：每个点自包含（脱离原文可独立阅读，"
    "补齐必要主语与背景），text≤500 字。\n"
    "4. " + _REFINE_RULES + "\n"
    "5. " + _SELF_CONSISTENCY_RULES + "\n"
    "6. 不要输出 JSON 以外的任何文字。"
)

# forced split（2026-10-22 用户口径）：形态已由确定性规则判定（文学创作类
# =知识点集合），LLM 只做提炼切点不做判定——省判定 token，且判定不再可能误切。
_SPLIT_ONLY_PROMPT = (
    "你是个人知识库的知识提炼助手。给定一个知识条目（标题+正文），它已确定为"
    "多知识点集合型文档（用户裁决），通读全文后提炼知识点——不是按段落复制。\n"
    "规则：\n"
    '1. 只输出 JSON 对象：{"summary":"整条一句话摘要",'
    '"points":[{"text":"整理后的知识文本","summary":"一句话摘要",'
    '"quote":"原文逐字引句"}]}。\n'
    "2. 切 2-8 个点：每个点 = 一个独立可复用的知识点，自包含（脱离原文可独立"
    "阅读，补齐必要主语与背景），text≤500 字。\n"
    "3. " + _REFINE_RULES + "\n"
    "4. " + _SELF_CONSISTENCY_RULES + "\n"
    "5. 不要输出 JSON 以外的任何文字。"
)

# forced integral（批次 92）：形态已由规则/用户覆盖判定，LLM 只做整条提炼。
_INTEGRAL_REFINE_PROMPT = (
    "你是个人知识库的知识提炼助手。给定一个条目（标题+正文），它已确定为整体型"
    "文档（方案/论证/单主题，整条即一个知识点），通读全文后产出**整理后的知识"
    "陈述**——不是复制或压缩原文。\n"
    "规则：\n"
    '1. 只输出 JSON 对象：{"summary":"整条一句话摘要","points":[{"text":'
    '"整理后的知识陈述","summary":"一句话摘要","quote":"原文核心句逐字引句"}]}，'
    "points 恰好一个元素。\n"
    "2. text = 该主题的完整知识陈述（≤800 字）：保留结构脉络（背景→方案→关键"
    "决策→结论），合并重复、剔除寒暄与废话；命令/代码/数字/版本号等硬信息原样"
    "保留；用整理后的语言重写，不逐字照抄；全部用简体中文输出（外语原文译写为"
    "中文，代码/命令/专有名词保留原文）。\n"
    "3. quote 从原文逐字摘引一句核心句（≤60 字）。\n"
    "4. " + _SELF_CONSISTENCY_RULES + "\n"
    "5. 不要输出 JSON 以外的任何文字。"
)

_FORCED_SPLIT_REASON = "用户口径 2026-10-22：文学创作类=知识点集合（规则判定，非 LLM）"
_FORCED_INTEGRAL_REASON = ("用户口径 2026-10-23：整体型文档整条即点（规则判定/覆盖），"
                           "LLM 提炼为整理后的知识陈述")


def _user_prompt(item: dict[str, Any], body: str) -> str:
    parts = [f"来源类型:{item.get('source_type', '')}",
             f"标题:{str(item.get('title') or '')[:100]}",
             f"正文:\n{body}"]
    return "\n".join(parts)


def run(item: dict[str, Any], ctx: TaskContext) -> dict[str, Any]:
    """返回 {"judge","reason","summary","points","llm_used"}（失败带 error）。

    points 为 list[{text, summary, quote?}]：integral 归一为单元素列表，调用方
    无需分支；**允许空列表**（LLM 明确判定无可独立成点的知识，llm_used=True，
    2026-10-24 自洽性裁决）——调用方据此阻断重抽，不当故障。forced_judge
    （item 键）："split"/"integral" 跳过 LLM 判定直接提炼，judge 与 reason
    固定口径理由——形态已由规则判定；缺省走判定+提炼合一。
    """
    empty = {"judge": "", "reason": "", "summary": "", "points": [], "llm_used": False}
    body = str(item.get("body") or "").strip()
    if ctx.llm is None or not body:
        return empty
    forced = str(item.get("forced_judge") or "").strip().lower()
    if forced == "split":
        prompt = _SPLIT_ONLY_PROMPT
    elif forced == "integral":
        prompt = _INTEGRAL_REFINE_PROMPT
    else:
        prompt = _SYSTEM_PROMPT
    try:
        obj = extract_json_object(ctx.llm.chat(prompt,
                                               _user_prompt(item, body)))
    except LlmError as exc:
        return {**empty, "error": str(exc)}
    if forced in ("split", "integral"):
        judge = forced
        reason = _FORCED_SPLIT_REASON if forced == "split" else _FORCED_INTEGRAL_REASON
    else:
        judge = str(obj.get("judge", "")).strip()
        if judge not in ("integral", "split"):
            return {**empty, "error": f"LLM 形态判定非法：{judge!r}"}
        reason = str(obj.get("reason", "")).strip()
    raw_points = obj.get("points")
    if not isinstance(raw_points, list):
        return {**empty, "error": "LLM 返回的 points 不是数组"}
    if not raw_points:
        # 自洽性纪律允许 LLM 明确判定"没有可独立成点的知识"（TODO 8.5）：
        # 这不是故障——由 pipeline 记 points_gate 阻断重抽，避免反复花钱。
        return {"judge": judge,
                "reason": reason or "无可独立成点的知识",
                "summary": str(obj.get("summary", "")).strip(),
                "points": [], "llm_used": True}
    points: list[dict[str, str]] = []
    for p in raw_points[:_MAX_POINTS]:
        if not isinstance(p, dict):
            continue
        text = str(p.get("text", "")).strip()
        if not text:
            continue
        points.append({"text": text,
                       "summary": str(p.get("summary", "")).strip(),
                       "quote": str(p.get("quote", "")).strip()})
    if not points:
        return {**empty, "error": "LLM 返回的点全部为空"}
    return {"judge": judge,
            "reason": reason,
            "summary": str(obj.get("summary", "")).strip(),
            "points": points,
            "llm_used": True}
