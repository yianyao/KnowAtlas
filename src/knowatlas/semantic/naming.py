# -*- coding: utf-8 -*-
"""AI 批量起名（批次 71）：网页原标题 → 知识化短名。

用户截图批注「这些能不能按知识的名字来命名」——书签条目标题是网页原标题
（长句 + 「 | 站点名」尾巴），列表里毫无知识味。本模块取条目正文（content_store）
交 LLM 起 8-20 字知识化名字，写 meta.display_name 覆盖层（数据层统一应用，
重同步冲不回）。默认提示词可在调用时覆盖（与知识梳理 §7.9 提示词面板同思路）。
"""

from __future__ import annotations

import re
from typing import Any

# 默认提示词：前端「✨AI 起名」面板可编辑（覆盖 default 时整段替换 system）
DEFAULT_SYSTEM_PROMPT = (
    "你是知识库管理员。根据文档正文给它起一个知识化的短名字。\n"
    "要求：\n"
    "1. 8-20 个字，中文为主（专有名词保留原文）\n"
    "2. 直说知识内容本身（做什么/讲什么），不要「浅谈」「一文读懂」「详解」等水词\n"
    "3. 去掉网站名、作者署名、管道符尾巴\n"
    "4. 只输出名字本身，不要引号、句号或任何解释"
)

_SITE_TAIL = re.compile(r"\s*[|｜/·]\s*[^|｜/·]{2,20}$")  # 「 | 人人都是产品经理」尾巴


def _strip_site_tail(title: str) -> str:
    """降级用：无 LLM 时至少把「| 站点名」尾巴剪掉。"""
    return _SITE_TAIL.sub("", title or "").strip()


def auto_name_entries(cfg: Any, dl: Any, ids: list[str], *,
                      force: bool = False,
                      prompt_override: str | None = None) -> dict[str, Any]:
    """对 ids 逐条起名写 meta.display_name；返回逐条结果。

    - 已有 display_name 且未 force → skip（不重复烧钱）；
    - 无正文（content_store 无块）→ 降级：剪站点尾巴后作为名字（零费用）；
    - LLM 未启用 → 全部走尾巴剪枝降级（degraded 标记）；
    - 单条 LLM 失败 → errors 记录继续（不中断整批）。
    """
    from .llm import LlmClient

    llm = LlmClient.from_config(cfg)
    system = prompt_override or DEFAULT_SYSTEM_PROMPT
    named: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for eid in ids:
        e = dl.get_entry(eid)
        if e is None:
            skipped.append({"id": eid, "reason": "not_found"})
            continue
        if str(e.meta.get("display_name") or "").strip() and not force:
            skipped.append({"id": eid, "title": e.title[:60], "reason": "already_named"})
            continue
        body = ""
        if e.content_hash:
            body = (dl.get_content(e.content_hash) or "")[:1500]
        name = ""
        if llm is not None and body:
            user = f"当前标题：{e.title}\n\n正文：\n{body}"
            try:
                name = llm.chat(system, user).strip().strip('"「」「」"\'「」')
            except Exception as exc:  # LlmError 等——单条失败不断批
                errors.append({"id": eid, "title": e.title[:60], "error": str(exc)[:120]})
                continue
        if not name:
            # 降级：剪尾巴（正文缺失或 LLM 不可用时）
            name = _strip_site_tail(e.title) or e.title[:30]
            degraded.append({"id": eid, "name": name})
        name = name[:120]
        dl.merge_meta(eid, {"display_name": name})
        dl.log_task(_now_iso(), "web", "auto_name", eid,
                    {"old": e.title[:60], "new": name,
                     "mode": "llm" if (llm is not None and body) else "tail_strip"})
        named.append({"id": eid, "old": e.title[:60], "new": name})
    return {"named": named, "skipped": skipped, "degraded": degraded,
            "errors": errors, "count": len(named)}


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")
