"""时效守卫（freshness guard）：纯规则信号标记「过期的、容易误导的知识」——零费用。

定位（2026-10-20 用户需求，TODO 时效/可信守卫步骤）：与 L0 价值守卫同构——
只标记不自动删（meta.freshness_flag），保留决定权在用户；「易误导」的语义判定
成本高，LLM 后置（YAGNI，规则信号不够再上）。

两类信号（判定结论进 meta.freshness_flag / freshness_reason）：

| flag    | reason | 规则                                                             |
|---------|--------|------------------------------------------------------------------|
| stale   | keyword  | 标题含废弃类关键词（已废弃/已过时/不再维护/deprecated 等），或   |
|         |          | 正文自述（「本文已过期」「This page is outdated」句式）          |
| suspect | date_old | 正文可提取的最新日期（发布/更新/版权年份）早于 stale_years 年前  |
| suspect | newer_version | 同 host 同主题（title_key 聚类）≥2 条且本条更旧——新旧并存时旧版易误导 |

防误杀设计：
- 「过期」类词单独出现在正文不算（缓存过期时间、token 过期等技术语义常见）——
  keyword 的正文通道只认「本文/此页面 … 已过期」式自述句；
- 裸 deprecated/obsolete 只在标题判（正文提及 deprecated API 是正常内容）；
- date_old 取正文**最新**年份（最后更新时间）而非最早——老页面近年更新过不算旧；
- 用户否决（freshness_flag=ok）后规则不再标记，与 value_flag=ok 同口径。

后置不实现：死链比例超阈值的 host 级批量标记（单条死链已有 link_status=dead
承接；比例阈值与批量标范围待真实需求定义，规则信号不够再上）。

边界：纯函数、无 IO；跨条目的 newer_version 聚类由 sync._freshness_scan 编排
（需要全库视图），本模块只提供单条判定与聚类键。
"""

from __future__ import annotations

import re

# 废弃类关键词（标题通道；case-insensitive）
_KEYWORD_RE = re.compile(
    r"已废弃|已过时|已过期|已淘汰|不再维护|停止维护|不再更新|已停止更新"
    r"|deprecated|obsolete|outdated|no longer maintained",
    re.IGNORECASE,
)

# 正文自述句式：主语（本文/此页面/This page…）+ 短间隔 + 废弃陈述
_SELF_DECLARE_RE = re.compile(
    r"(?:本文|此(?:页面|文档|文章|教程|内容)|本(?:页面|文档|文章|教程)"
    r"|this (?:page|document|article|tutorial)|the (?:page|article))[^.。\n]{0,15}"
    r"(?:已(?:经)?(?:过期|过时|废弃|停止维护|不再维护|不再更新)"
    r"|is (?:outdated|obsolete|deprecated)"
    r"|has been (?:deprecated|archived)"
    r"|no longer (?:maintained|updated))",
    re.IGNORECASE,
)

# 日期提取：显式「最后更新/发布」引导 + 通用日期模式（年份捕获组）
_YEAR_PATTERNS = (
    re.compile(r"最后(?:更新|修订)(?:于|时间|日期)?[:：]?\s*(20\d{2})", re.IGNORECASE),
    re.compile(r"(?:发布|更新|发表于)(?:于|时间|日期)?[:：]?\s*(20\d{2})", re.IGNORECASE),
    re.compile(r"(20\d{2})[-/年.]\s*\d{1,2}[-/月.]\s*\d{1,2}"),
)
# 版权年份：预检命中（防裸四位数字误报）才提取
_COPYRIGHT_PRECHECK = re.compile(r"©|\bcopyright\b", re.IGNORECASE)
_COPYRIGHT_YEAR = re.compile(r"(?:©|\(c\)|\bcopyright\b(?:\s*\(c\))?)\s*(20\d{2})", re.IGNORECASE)

_YEAR_TOKEN_RE = re.compile(r"\d+(?:\.\d+)+")


def extract_latest_year(text: str, *, scan_limit: int = 5000) -> int | None:
    """提取正文中可判定的最新年份（最后更新时间）；提不到返回 None。

    只扫前 scan_limit 字符（内联正文上限 4000，余量足够）。返回最大年份——
    老页面近年更新过不算旧。
    """
    if not text:
        return None
    sample = text[:scan_limit]
    years: list[int] = []
    for pat in _YEAR_PATTERNS:
        years.extend(int(m) for m in pat.findall(sample))
    # 版权年份：预检到 ©/Copyright 才提（裸四位数字误报太多，不单独收）
    if _COPYRIGHT_PRECHECK.search(sample):
        m = _COPYRIGHT_YEAR.search(sample)
        if m:
            years.append(int(m.group(1)))
    return max(years) if years else None


def title_key(title: str | None) -> str:
    """同主题聚类键：小写、去版本号（3.6/v2 这类点分号）、去非文字字符。

    「Python 3.6 教程」与「Python 3.12 教程」聚成同键——新旧版本并存场景的
    聚类入口。仅用于同 host 组内比较（跨站同键不聚，误合成本高）。
    """
    t = (title or "").lower()
    t = _YEAR_TOKEN_RE.sub(" ", t)
    t = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", t)
    return t


def judge_text(
    title: str | None,
    body: str | None,
    *,
    stale_years: int = 3,
    now_year: int | None = None,
) -> tuple[str, str] | None:
    """单条文本时效判定；返回 (flag, reason)，无信号返回 None。

    flag: "stale"（明确过期，退出消费面）/ "suspect"（疑似过旧，保留可见进候选）。
    now_year 默认取当前年份（测试显式传入保证确定性）。
    """
    t = str(title or "")
    b = str(body or "")
    if not t and not b:
        return None

    # 规则一：废弃关键词——标题命中即 stale；正文只认自述句式（防技术语义误杀）
    if _KEYWORD_RE.search(t):
        return ("stale", "keyword")
    if _SELF_DECLARE_RE.search(b):
        return ("stale", "keyword")

    # 规则二：正文最新日期早于 stale_years 年前 → suspect
    if now_year is None:
        from datetime import datetime
        now_year = datetime.now().year
    latest = extract_latest_year(b)
    if latest is not None and latest < now_year - stale_years:
        return ("suspect", "date_old")
    return None
