"""内置能力登记入口（完整方案 §4.4）。

登记纪律：所有 register 调用只允许出现在本文件；handler/task 实现文件不得自注册（防 import 副作用）。
新能力 = 新文件 + 本文件加一行，不改主流程。
"""

from __future__ import annotations

from ..fetchers import file_reader, http_simple
from ..semantic.tasks import (
    aging_judge, classify_coarse, classify_deep, delta_summarize, errata_check,
    point_aging, point_dupe_judge, point_errata, point_explain, point_extract,
    point_lifecycle, point_triage, synthesize, tag_keywords, thread_digest,
    thread_suggest, topic_recall,
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
    # 老化三级 L2（第六十三批，方案 §7.5）：suspect 时效复核，结论升级/否决/下沉人裁
    semantics.register(aging_judge.SPEC, aging_judge.run)
    # 点级老化 L2（批次 93，裁决 #14）：条目过时不连坐点，点级 stale 退出消费面
    semantics.register(point_aging.SPEC, point_aging.run)
    # 大白话释疑（批次 90）：点卡片 → LLM 解释+示例，结果缓存点 meta 零重复费用
    semantics.register(point_explain.SPEC, point_explain.run)
    # 知识梳理合成层（批次 69，§7.9）：勾选点 → LLM 生成方案文档，synthesized 回灌+隔离
    semantics.register(synthesize.SPEC, synthesize.run)
    # 勘误三级 L2（第六十四批，方案 §7.6）：事实一致性核查，error 必附依据否则降 suspect
    semantics.register(errata_check.SPEC, errata_check.run)
    # 点分诊（P0，2026-10-25 裁决）：hard/opinion/unjudgeable 三分诊，勘误与老化的领域闸门前置
    semantics.register(point_triage.SPEC, point_triage.run)
    # 点级勘误（P1，2026-10-25 裁决）：hard 点事实核查，wrong 必附依据否则降 suspect
    semantics.register(point_errata.SPEC, point_errata.run)
    # 点级老化两型（P2，2026-10-26 工单）：版本型走 EOL 表零 LLM；退场型按技术栈判，
    # retired 必附官方依据否则 keep
    semantics.register(point_lifecycle.SPEC, point_lifecycle.run)
    # 去重边界对裁定（R30，2026-10-29 工单）：余弦分不开「同模板不同事实」，规则挑对 + LLM 裁定
    semantics.register(point_dupe_judge.SPEC, point_dupe_judge.run)
    return locators, semantics
