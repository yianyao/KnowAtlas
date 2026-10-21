"""关键词工具：噪音词准入 + 成员共享词提取（词云与知识集组头共用）。

噪音表原在 web/api.py 词云节内（第五十八批定稿），第六十批知识集组头
需要同一套准入规则，故移入共用模块——行为逐字保留，词云端点改为引用。
"""

from __future__ import annotations

# 词元噪音停用词（真实库冒烟 2026-10-21：markdown 残片/数据导出占位符；
# 第五十八批按用户定调扩充「非知识性词汇」——网页/技术样板词 + 通用
# 虚词，这类词在词云里只有噪音价值，取舍原则：几乎不承载知识区分度）
NOISE_WORDS = frozenset({
    "nan", "pass", "unnamed", "null", "none", "undefined", "na",
    "true", "false", "nbsp", "utf", "utf8", "utf-8",
    # URL / HTML / 文件类型样板
    "http", "https", "html", "htm", "www", "com", "org", "net", "cn",
    "php", "png", "jpg", "jpeg", "gif", "svg", "ico", "css", "js",
    "json", "xml", "url", "uri", "api", "localhost", "host", "server",
    "web", "site", "page", "index", "main", "default", "title",
    "content", "file", "files", "image", "images", "download",
    "version", "install", "setup", "config", "support", "help",
    "docs", "example", "examples", "test", "user", "users", "name",
    "value", "values", "type", "types", "data", "list", "item",
    "items", "error", "errors", "warning", "info", "note", "notes",
    # 英文高频虚词 / 通用 UI 词
    "your", "you", "the", "and", "for", "with", "this", "that",
    "from", "are", "was", "will", "can", "all", "not", "have",
    "one", "out", "how", "what", "when", "more", "use", "used",
    "using", "new", "home", "menu", "search", "click", "here",
    "please", "faq", "guide", "guides",
    # 中文高频虚词 / 通用泛词（保留具体技术名词如 内核/控制台/重启）
    "点击", "这里", "我们", "他们", "可以", "如果", "这个", "那个",
    "一个", "没有", "或者", "以及", "关于", "相关", "内容", "使用",
    "进行", "通过", "以下", "上面", "下面", "当前", "选择", "操作",
    "方法", "问题", "情况", "时间", "需要", "不能", "出现", "显示",
    "查看", "打开", "关闭", "进入", "完成", "开始", "支持", "并且",
    "但是", "然后", "例如",
})


def word_ok(kw: str) -> bool:
    """词元准入：至少一个字母（滤纯数字/「2024年」类）、非纯符号/标点
    （##、--- 类 markdown 残片）、非噪音停用词、长度 ≥2（md/py 类英文短词
    反映库构成，保留）。"""
    import re  # noqa: PLC0415 热路径外沿导入，避免模块级 re 依赖面
    if len(kw) < 2:
        return False
    if not re.search(r"[^\W\d_]", kw):       # 无任何字母
        return False
    if re.fullmatch(r"[\W_]+", kw):          # 纯符号/标点
        return False
    if kw.lower() in NOISE_WORDS:
        return False
    return True


def shared_words(texts: list[str], cap: int = 4) -> list[str]:
    """成员间真实共享词（第六十批知识集组头，禁发明性命名的落点）。

    jieba 抽词后，只保留**在每个成员文本中都子串出现**（大小写不敏感）的词
    ——组头词因此可在组内任一条目验证（TODO Phase 7 探针），LLM 不参与、
    无编造空间。输出按「最好抽取序」（成员内 tf-idf 排名靠前优先）取前 cap 个。
    """
    real = [t for t in texts if t and t.strip()]
    if len(real) < 2:
        return []
    try:
        import jieba.analyse  # noqa: PLC0415 惰性导入（jieba 是 main 依赖）
    except ImportError:
        return []
    lowers = [t.lower() for t in real]
    best_rank: dict[str, int] = {}
    for t in real:
        for pos, kw in enumerate(jieba.analyse.extract_tags(t[:2000], topK=12)):
            k = kw.lower()
            if not word_ok(k):
                continue
            if not all(k in low for low in lowers):   # 可验证性硬闸
                continue
            if pos < best_rank.get(k, 1 << 30):
                best_rank[k] = pos
    return sorted(best_rank, key=lambda k: (best_rank[k], k))[:cap]
