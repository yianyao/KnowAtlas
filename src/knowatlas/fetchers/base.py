"""抓取路由与上下文（完整方案 §9.3）：升级路由集中在此，不在各适配器。

批次 92（裁决 12「入库=知识整理，抓来的必须是知识不是页面骨架」）新增两件：
- github.com blob/raw 页面 → raw.githubusercontent.com 直链重写（blob HTML 页
  readability 必提取 Notifications/Fork/Star 按钮墙，raw 直链是纯文本、免费且精确）；
- 页面骨架检测 is_skeleton_body（导航/登录/版权行占比过高 → 提取失败信号，
  触发升级后端；points 管线对存量条目用它打 degraded 标、不切片）。
"""

from __future__ import annotations

import re

from ..errors import DegradedParseError, FetchError
from ..registry.capability import FetchContext, LocatorRegistry  # re-export 便于上层单一导入

_GH_BLOB = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/(?:blob|raw)/(.+)$")

# 骨架信号（行级）：整行匹配才计数（子串会误伤正文）；中英双语。
_CHROME_LINE = re.compile(
    r"(?:menu|nav(?:igation)?|search|sign in|sign up|log ?in|skip to content|"
    r"notifications?|fork|star|watch|pull requests?|issues?|actions?|projects?|"
    r"wiki|security|insights?|codespaces|copilot|sponsors|about|terms|privacy|"
    r"cookies?|copyright|contact(?: us)?|all rights reserved|read more|"
    r"learn more|homepage|repository|files|commits?|branches|tags|"
    r"首页|导航|菜单|登录|注册|搜索|跳到内容|跳至内容|关于我们|联系我们|"
    r"隐私政策|用户协议|免责声明|版权所有|下一页|上一页|展开|收起|更多"
    r")[.。:：!！]?$", re.I)

# 骨架信号（短语级）：多词英文导航短语互异计数——readability text_content 常把
# 段落压成一行（无换行可分行），行级失效时兜底。只用多词英文短语（中文两字词
# 子串误伤率高，不参与）；再叠加「无句读」条件（。或 ". " <2 处）——导航墙
# 没有句子，而介绍 GitHub UI 的真文（"fork 与 star 的区别。"）必然有句号，
# 借此排除「教程正文提到多个导航词」的误伤。
_CHROME_PHRASES = ("skip to content", "sign in", "sign up", "pull requests",
                   "all rights reserved", "notifications", "fork", "star",
                   "issues", "actions", "projects", "wiki", "privacy",
                   "copyright")


def github_raw_url(locator: str) -> str:
    """github.com blob/raw 页面 → raw.githubusercontent.com 直链（仅确定性等价）。

    仓库首页 / issues 等非 blob 页不重写（无对应 raw 资源），交给双后端路由。
    """
    m = _GH_BLOB.match(locator)
    if m:
        return (f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/"
                f"{m.group(3)}")
    return locator


def is_skeleton_body(text: str) -> bool:
    """正文疑似网页骨架（导航/按钮/版权行占比过高）。

    双模式：①行级——≥8 行且骨架行 ≥8 且占比 ≥60%；②短语级（行级失效时的
    单行兜底）——<1500 字符、互异英文导航短语 ≥8 个、且几乎无句读（。或
    ". " 少于 2 处）。消费方：http_simple 提取后（判提取失败 → 升级 DeepSeek
    Fetch 重抓——误判零数据损失）、points 管线对存量条目（merge_meta
    body_flag=skeleton 跳过切片——degraded 不切片，宁缺毋脏；误判可清标重抽）。
    纯文本内容（raw 直链）不做此检测。
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 8:
        chrome = sum(1 for ln in lines if _CHROME_LINE.match(ln))
        if chrome >= 8 and chrome / len(lines) >= 0.6:
            return True
    if len(text) < 1500:
        low = text.lower()
        distinct = sum(1 for k in _CHROME_PHRASES if k in low)
        if distinct >= 8 and text.count("。") + text.count(". ") < 2:
            return True
    return False


def fetch_with_fallback(locator: str, locators: LocatorRegistry, ctx: FetchContext) -> tuple[str, str]:
    """返回 (text, title)。

    - http/https：走双后端路由（simple 失败/正文过短 → fallback_backend，当前为 DeepSeek Fetch）；
    - 其余 scheme：按注册表分发到唯一 handler。
    已命中 content_store 的条目在 pipeline 层短路（hash 命中不调任何后端，零成本）；
    inline_content 已内联的条目不过 fetcher 直传。
    """
    scheme = locator.split("://", 1)[0].lower()
    if scheme in ("http", "https"):
        return _fetch_http_with_fallback(locator, ctx)
    _spec, handler = locators.resolve(locator)
    return handler(locator, ctx)


def _fetch_http_with_fallback(locator: str, ctx: FetchContext) -> tuple[str, str]:
    from . import http_simple

    locator = github_raw_url(locator)  # 批次 92：blob/raw 页 → raw 直链（两后端共用）
    try:
        return http_simple.fetch_page(locator, ctx)
    except (FetchError, DegradedParseError) as primary_exc:
        fallback = str(ctx.config.get("fetch.fallback_backend") or "").strip()
        if not fallback or fallback == str(ctx.config.get("fetch.default_backend") or "simple"):
            raise
        try:
            from . import http_deepseek  # noqa: F401  导入成功才尝试升级
        except ImportError:
            raise primary_exc
        from . import http_deepseek

        return http_deepseek.fetch_page(locator, ctx)
