"""内置能力登记入口（完整方案 §4.4）。

登记纪律：所有 register 调用只允许出现在本文件；handler/task 实现文件不得自注册（防 import 副作用）。
新能力 = 新文件 + 本文件加一行，不改主流程。
"""

from __future__ import annotations

from ..fetchers import file_reader, http_simple
from ..semantic.tasks import (
    classify_coarse, classify_deep, delta_summarize, point_extract, tag_keywords,
    thread_digest, thread_suggest, topic_recall,
)
from .capability import CapabilitySpec, LocatorRegistry, SemanticRegistry


def build_registries(config) -> tuple[LocatorRegistry, SemanticRegistry]:
    """构建两个注册表并登记内置能力（v1）。"""
    locators = LocatorRegistry()
    locators.register(
        CapabilitySpec("https", {"locator": "https URL"}, {"text": "str", "title": "str"},
                       "1.0.0", "simple 网页正文抓取（readability-lxml）"),
        http_simple.fetch_page,
    )
    locators.register(
        CapabilitySpec("http", {"locator": "http URL"}, {"text": "str", "title": "str"},
                       "1.0.0", "simple 网页正文抓取（readability-lxml）"),
        http_simple.fetch_page,
    )
    locators.register(
        CapabilitySpec("file", {"locator": "file://<配置根相对路径>"}, {"text": "str", "title": "str"},
                       "1.0.0", "本地文件读取（txt/md 直读；Office/PDF 走 markitdown）"),
        file_reader.fetch_file,
    )

    semantics = SemanticRegistry()
    semantics.register(classify_coarse.SPEC, classify_coarse.run)
    semantics.register(classify_deep.SPEC, classify_deep.run)
    semantics.register(tag_keywords.SPEC, tag_keywords.run)
    # 串联工作区（完整方案 §9.4）：召回型/建议型任务，查询驱动签名（见各自模块 docstring）
    semantics.register(topic_recall.SPEC, topic_recall.run)
    semantics.register(thread_suggest.SPEC, thread_suggest.run)
    # 线程语义压缩（第五十五批，§9.4）：quote_strip 后置 LLM 层，可独立关闭
    semantics.register(delta_summarize.SPEC, delta_summarize.run)
    semantics.register(thread_digest.SPEC, thread_digest.run)
    # 知识点抽取（第六十二批，方案 §7.1）：形态判定 + 切点，查询独立演进
    semantics.register(point_extract.SPEC, point_extract.run)
    return locators, semantics
