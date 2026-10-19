"""tag_keywords：jieba tf-idf 关键词（词云与关键词统计用，完整方案 §4.3）。"""

from __future__ import annotations

from ...registry.capability import CapabilitySpec
from ..base import SemanticInput, SemanticOutput, TaskContext

SPEC = CapabilitySpec(
    name="tag_keywords",
    input_contract={"SemanticInput": "list"},
    output_contract={"SemanticOutput.tags": "list[str]（tf-idf top 10）"},
    version="1.0.0",
    description="jieba tf-idf 关键词；jieba 缺失时输出空 tags（不阻塞主流程）",
)


def run(inputs: list[SemanticInput], ctx: TaskContext) -> list[SemanticOutput]:
    try:
        import jieba.analyse  # noqa: PLC0415 惰性导入
    except ImportError:
        return [SemanticOutput(classifications=[]) for _ in inputs]
    outputs: list[SemanticOutput] = []
    for inp in inputs:
        text = f"{inp.title}\n{inp.body or ''}"
        tags = jieba.analyse.extract_tags(text, topK=10)
        outputs.append(SemanticOutput(classifications=[], tags=tags))
    return outputs
