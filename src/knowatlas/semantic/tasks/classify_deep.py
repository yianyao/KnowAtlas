"""classify_deep（L3）：LLM 语义分类（0.2.0 提前落，原计划 M4）。

定位：L1 先验 / L2 规则都未命中时，按**内容语义**（标题 + URL + 文件夹路径）
判类——分类树节点由知识内容决定，不由文件夹命名决定（2026-10-19 用户定调）。

约束：
- ctx.llm 为 None（未启用 / key 未设）→ 全部返回空 classifications（进暂存区），
  行为退化为 M0.5，绝不硬猜；
- 候选路径 = 现有分类路径（known_paths，优先归并），允许 LLM 提议新路径；
- 批量请求（llm.max_batch，默认 20）控成本；单批失败只损失该批（进暂存区），不中断。
"""

from __future__ import annotations

import math

from ...registry.capability import CapabilitySpec
from ...semantic.llm import LlmError, extract_json_array
from ..base import Classification, SemanticInput, SemanticOutput, TaskContext

SPEC = CapabilitySpec(
    name="classify_deep",
    input_contract={"SemanticInput": "list（title/body/native_path/meta.source_type）"},
    output_contract={"SemanticOutput": "list；classifications 为空 = 无法归类"},
    version="1.0.0",
    description="L3 LLM 语义分类：标题+域名+路径 → 分类路径（conf 自评，origin=llm）",
)

_SYSTEM_PROMPT = (
    "你是个人知识库的分类器。根据条目的标题、URL 域名和文件夹路径判断它属于哪个分类，"
    "并判断它是否一条具体的知识内容。\n"
    "规则：\n"
    "1. 一级分类必须从【候选分类路径】的一级中选，不得自造一级。\n"
    "2. 二级分类按内容判断：优先逐字使用候选中的完整路径；都不贴切时提议新的二级，"
    "格式「一级/二级」。不要把不相关的条目塞进宽泛的「杂项/工具/综合」类——"
    "按条目实际内容给出最贴切的技术或领域类目。\n"
    "3. kind 判断条目性质：knowledge = 指向具体、自洽的知识内容（文章/教程/文档页/工具）；"
    "non = 只是指向站点门户/导航首页/资源列表/纯资源文件本身（音乐、安装包）等，"
    "作为知识条目没有保留价值。\n"
    "4. path 无法判断时输出 \"?\"；conf 为 0 到 1 的置信度。\n"
    '只输出 JSON 数组，格式：[{"i":1,"path":"技术开发/数据库","conf":0.9,"kind":"knowledge"}]，'
    "不要输出任何其他文字。"
)


def _entry_line(idx: int, inp: SemanticInput) -> str:
    from urllib.parse import urlsplit

    url = str(inp.meta.get("locator", "")) or ""
    host = ""
    if url.startswith(("http://", "https://")):
        try:
            host = urlsplit(url).hostname or ""
        except ValueError:
            host = ""  # 非 ASCII 全角字符等非法 netloc——域名信号放弃，不丢条目
    parts = [f"{idx}. 标题:{inp.title[:60]}"]
    if host:
        parts.append(f"域名:{host}")
    if not host and url.startswith("file://"):
        parts.append(f"文件:{url.removeprefix('file://')[:60]}")
    if inp.native_path:
        parts.append(f"文件夹:{inp.native_path}")
    if inp.body:
        parts.append(f"摘要:{inp.body[:120]}")
    return " | ".join(parts)


def classify_batch(inputs: list[SemanticInput], known_paths: frozenset[str],
                   llm: Any, max_batch: int = 20) -> list[SemanticOutput]:
    """批量 LLM 分类；返回与 inputs 等长的 SemanticOutput 列表。"""
    outputs: list[SemanticOutput] = [SemanticOutput(classifications=[]) for _ in inputs]
    batches = math.ceil(len(inputs) / max_batch) if inputs else 0
    candidates = "\n".join(sorted(known_paths)) or "（暂无，可自由提议「一级/二级」路径）"
    for b in range(batches):
        chunk = inputs[b * max_batch:(b + 1) * max_batch]
        user = ("【候选分类路径】\n" + candidates + "\n\n【条目列表】\n"
                + "\n".join(_entry_line(i + 1, inp) for i, inp in enumerate(chunk)))
        try:
            arr = extract_json_array(llm.chat(_SYSTEM_PROMPT, user))
        except LlmError:
            continue  # 该批失败 → 保持空分类（暂存区），其余批继续
        by_idx = {int(x.get("i", 0)): x for x in arr if str(x.get("i", "")).lstrip("-").isdigit()}
        for i, inp in enumerate(chunk):
            hit = by_idx.get(i + 1)
            if not hit:
                continue
            path = str(hit.get("path", "")).strip().strip("/")
            conf = hit.get("conf", 0.6)
            try:
                conf = min(1.0, max(0.0, float(conf)))
            except (TypeError, ValueError):
                conf = 0.6
            tags = ["not_knowledge"] if str(hit.get("kind", "knowledge")) == "non" else []
            if path and path != "?":
                outputs[b * max_batch + i] = SemanticOutput(
                    classifications=[Classification(path, conf, "llm")], tags=tags)
            elif tags:
                # 非知识但无类目：也把性质结论带出（进暂存区 + 待清理候选）
                outputs[b * max_batch + i] = SemanticOutput(classifications=[], tags=tags)
    return outputs


def run(inputs: list[SemanticInput], ctx: TaskContext) -> list[SemanticOutput]:
    if ctx.llm is None:
        return [SemanticOutput(classifications=[]) for _ in inputs]
    max_batch = 20
    if ctx.config is not None:
        try:
            max_batch = int(ctx.config.get("llm.max_batch", 20))
        except (TypeError, ValueError):
            max_batch = 20
    return classify_batch(inputs, ctx.known_paths, ctx.llm, max_batch)
