"""先验映射表（完整方案 §9.2）：native_path 前缀 → 分类路径，最长前缀优先。

这是"先验结构信号优先"策略的落点：书签文件夹 / 邮件文件夹 / 脑图节点树 / 文件路径
都是免费的、比 LLM 更可靠的分类信号。conf 命中即 1.0、origin=prior。

0.2.0 收敛修订（2026-10-19，用户反馈"树不应是文件夹镜像"）：
- 只保留语义明确、类目命中的映射；碎片/随手文件夹（工具站、自学、综合、other）
  不再映射——放行给 L2 规则与 L3 LLM 语义分类。分类树节点由内容语义决定，
  不由文件夹命名决定。
- 「软件开发」并入「技术开发」（规则表 RULES 同步）。
弱信号路径（移动设备书签、裸"其他书签"、裸"书签栏"）依旧不映射、留暂存区。
"""

from __future__ import annotations

# (source_type, native_path 前缀, 分类路径)
PRIOR_MAP: list[tuple[str, str, str]] = [
    # ---- bookmark：语义明确的真实书签文件夹（最长前缀优先）----
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
