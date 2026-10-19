"""L2 关键词/正则/域名规则（完整方案 §9.1 的规则级）。

命中 confidence=0.8、origin=rule。规则清单随人工校正回路逐步沉淀（SOP-C）。
"""

from __future__ import annotations

import re

# (分类路径, 关键词元组)——顺序即优先级，先命中先得
# 0.2.0 收敛：「软件开发」并入「技术开发」（用户反馈：碎片顶层类应合并）
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("技术开发/数据库", ("数据库", "sqlite", "sql", "postgres", "mysql", "redis")),
    ("技术开发", ("python", "代码", "api", "框架", "重构", "正则", "javascript", "typescript")),
    ("软件与ERP", ("erp", "进销存", "仓存", "材料入库", "出库")),
    ("文学创作", ("写作", "小说", "对话描写", "文笔", "散文")),
    ("人工智能", ("llm", "大模型", "提示词", "agent", "人工智能", "深度学习")),
]

_WORD_RE = re.compile(r"[a-z0-9]+")


def match_rule(title: str, body: str | None) -> str | None:
    """标题优先、正文兜底的关键词匹配；未命中返回 None。"""
    title_l = (title or "").lower()
    body_l = (body or "").lower()
    words = set(_WORD_RE.findall(title_l)) | set(_WORD_RE.findall(body_l))
    for category, keywords in RULES:
        for kw in keywords:
            if kw.isascii():
                if kw in words or kw in title_l or kw in body_l:
                    return category
            else:
                if kw in title_l or kw in body_l:
                    return category
    return None
