"""先验映射表（完整方案 §9.2）：native_path 前缀 → 分类路径，最长前缀优先。

这是"先验结构信号优先"策略的落点：书签文件夹 / 邮件文件夹 / 脑图节点树 / 文件路径
都是免费的、比 LLM 更可靠的分类信号。conf 命中即 1.0、origin=prior。
"""

from __future__ import annotations

# (source_type, native_path 前缀, 分类路径)
PRIOR_MAP: list[tuple[str, str, str]] = [
    ("bookmark", "书签栏/技术/数据库", "技术开发/数据库"),
    ("folder",   "办公文档/ERP",       "软件与ERP"),
    ("emmx",     "文学创作",           "文学创作"),
]


def match_prior(source_type: str, native_path: str | None) -> str | None:
    """返回命中的分类路径；未命中返回 None。最长前缀优先。"""
    if not native_path:
        return None
    best: tuple[int, str] | None = None
    for src, prefix, category in PRIOR_MAP:
        if src != source_type or not (native_path == prefix or native_path.startswith(prefix + "/")):
            continue
        if best is None or len(prefix) > best[0]:
            best = (len(prefix), category)
    return best[1] if best else None
