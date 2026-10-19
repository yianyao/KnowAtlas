"""先验映射表（完整方案 §9.2）：native_path 前缀 → 分类路径，最长前缀优先。

这是"先验结构信号优先"策略的落点：书签文件夹 / 邮件文件夹 / 脑图节点树 / 文件路径
都是免费的、比 LLM 更可靠的分类信号。conf 命中即 1.0、origin=prior。

bookmark 条目按 390 条真实书签的文件夹分布定稿初版（2026-10-19，M0.5 Gate
"10 大类经真实数据检验修订"）：AI绘图/AI/js/前端/php/rabbitmq/python/java/
git/api/后端/JS&TS/编程思想 → 技术开发与人工智能；Huawei/华为 → 华为云；
自学/综合/other/tools → 综合资料。弱信号路径（移动设备书签、裸"其他书签"、
裸"书签栏"）不映射——留在暂存区，绝不硬猜。
"""

from __future__ import annotations

# (source_type, native_path 前缀, 分类路径)
PRIOR_MAP: list[tuple[str, str, str]] = [
    # ---- bookmark：真实书签文件夹 → 分类树（最长前缀优先）----
    ("bookmark", "书签栏/AI绘图",       "人工智能/AI绘图"),
    ("bookmark", "书签栏/AI",           "人工智能"),
    ("bookmark", "其他书签/js",         "技术开发/前端"),
    ("bookmark", "书签栏/JS&TS",        "技术开发/前端"),
    ("bookmark", "书签栏/前端",         "技术开发/前端"),
    ("bookmark", "其他书签/php",        "技术开发/后端"),
    ("bookmark", "其他书签/rabbitmq",   "技术开发/后端"),
    ("bookmark", "其他书签/python",     "技术开发/后端"),
    ("bookmark", "其他书签/java",       "技术开发/后端"),
    ("bookmark", "其他书签/git",        "技术开发/后端"),
    ("bookmark", "其他书签/api",        "技术开发/后端"),
    ("bookmark", "书签栏/后端",         "技术开发/后端"),
    ("bookmark", "书签栏/编程思想",     "技术开发"),
    ("bookmark", "其他书签/Huawei",     "华为云"),
    ("bookmark", "书签栏/华为",         "华为云"),
    ("bookmark", "书签栏/自学",         "综合资料/自学"),
    ("bookmark", "书签栏/综合",         "综合资料"),
    ("bookmark", "其他书签/other",      "综合资料"),
    ("bookmark", "书签栏/tools",        "综合资料/工具站"),
    # ---- 其他源（随 M1 后续接入逐步填充）----
    ("folder",   "办公文档/ERP",        "软件与ERP"),
    ("emmx",     "文学创作",            "文学创作"),
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
