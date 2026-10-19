"""classify_coarse 三级流水线（完整方案 §9.1）。

M0.5 实现 L1 先验 + L2 规则；L3（embedding 聚类 + LLM 命名）在 M4 接入——
ctx.llm / ctx.embedder 为 None 时该级跳过，绝不硬猜（无结果 = 进暂存区）。
"""

from __future__ import annotations

from ...registry.capability import CapabilitySpec
from ..base import Classification, SemanticInput, SemanticOutput, TaskContext
from ..priors import match_prior
from ..rules import match_rule

SPEC = CapabilitySpec(
    name="classify_coarse",
    input_contract={"SemanticInput": "list（title/body/native_path/meta.source_type）"},
    output_contract={"SemanticOutput": "list；classifications 为空 = 无法归类"},
    version="1.0.0",
    description="三级流水线：L1 先验（native_path）→ L2 规则（关键词）→ L3 embedding+LLM（M4）",
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

        # L3（embedding + LLM）占位：M4 接入；ctx.llm/ctx.embedder 为 None 时跳过
        outputs.append(SemanticOutput(classifications=classifications))
    return outputs
