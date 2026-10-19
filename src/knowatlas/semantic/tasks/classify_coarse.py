"""classify_coarse 三级流水线（完整方案 §9.1）。

L1 先验 + L2 规则 + L3 LLM（0.2.0 提前接入，classify_deep）：
- ctx.llm 为 None（未启用 / key 未设）时 L3 跳过，未命中进暂存区，绝不硬猜；
- L1/L2 命中不消耗 LLM 调用（成本纪律）。
"""

from __future__ import annotations

from ...registry.capability import CapabilitySpec
from ..base import Classification, SemanticInput, SemanticOutput, TaskContext
from ..priors import match_prior
from ..rules import match_rule
from .classify_deep import run as run_deep

SPEC = CapabilitySpec(
    name="classify_coarse",
    input_contract={"SemanticInput": "list（title/body/native_path/meta.source_type）"},
    output_contract={"SemanticOutput": "list；classifications 为空 = 无法归类"},
    version="1.1.0",
    description="三级流水线：L1 先验（native_path）→ L2 规则（关键词）→ L3 LLM（classify_deep）",
)


def run(inputs: list[SemanticInput], ctx: TaskContext) -> list[SemanticOutput]:
    outputs: list[SemanticOutput] = []
    for inp in inputs:
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
    pending = [i for i, (inp, out) in enumerate(zip(inputs, outputs))
               if not out.classifications]
    if pending and ctx.llm is not None:
        deep = run_deep([inputs[i] for i in pending], ctx)
        for i, out in zip(pending, deep):
            if out.classifications:
                outputs[i] = out
    return outputs
