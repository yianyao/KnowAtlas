"""classify_coarse 三级流水线（完整方案 §9.1）。

L0 价值守卫 + L1 先验 + L2 规则 + L3 LLM（0.2.0 提前接入，classify_deep）：
- L0（value_guard）：URL 结构一眼可判的非知识内容（资源直链/站点首页/列表子页）
  ——零成本短路，不占 L1/L2/L3，更不调 LLM（2026-10-20 用户定调：不需要 LLM
  做语义判断的部分不花 token）；
- ctx.llm 为 None（未启用 / key 未设）时 L3 跳过，未命中进暂存区，绝不硬猜；
- L1/L2 命中不消耗 LLM 调用（成本纪律）。
"""

from __future__ import annotations

from ...registry.capability import CapabilitySpec
from ..base import Classification, SemanticInput, SemanticOutput, TaskContext
from ..priors import match_prior
from ..rules import match_rule
from ..value_guard import judge_value
from .classify_deep import run as run_deep

SPEC = CapabilitySpec(
    name="classify_coarse",
    input_contract={"SemanticInput": "list（title/body/native_path/meta.source_type）"},
    output_contract={"SemanticOutput": "list；classifications 为空 = 无法归类"},
    version="1.2.0",
    description="L0 价值守卫（URL 结构）+ 三级流水线：L1 先验（native_path）→ L2 规则（关键词）→ L3 LLM（classify_deep）",
)


def run(inputs: list[SemanticInput], ctx: TaskContext) -> list[SemanticOutput]:
    outputs: list[SemanticOutput] = []
    flagged: set[int] = set()  # L0 已短路的条目索引——不再进 L3（tags 免被覆盖）
    for i, inp in enumerate(inputs):
        # L0 价值守卫：结构可判的非知识内容直接短路（tags 与 LLM kind=non 同构）；
        # 用户已否决（value_flag=ok）的条目不短路，正常走分类
        if str(inp.meta.get("value_flag", "")) != "ok":
            reason = judge_value(str(inp.meta.get("locator", "")))
            if reason is not None:
                outputs.append(SemanticOutput(
                    classifications=[],
                    tags=["not_knowledge", f"value_reason:{reason}"]))
                flagged.add(i)
                continue

        classifications: list[Classification] = []

        prior = match_prior(str(inp.meta.get("source_type", "")), inp.native_path)
        if prior:
            classifications.append(Classification(prior, 1.0, "prior"))
        else:
            rule = match_rule(inp.title, inp.body)
            if rule:
                classifications.append(Classification(rule, 0.8, "rule"))

        outputs.append(SemanticOutput(classifications=classifications))

    # L3：对 L1/L2 未命中的条目批量走 LLM（llm 不可用时 run_deep 原样返回空）
    pending = [i for i, out in enumerate(outputs)
               if not out.classifications and i not in flagged]
    if pending and ctx.llm is not None:
        deep = run_deep([inputs[i] for i in pending], ctx)
        for i, out in zip(pending, deep):
            if out.classifications:
                outputs[i] = out
    return outputs
