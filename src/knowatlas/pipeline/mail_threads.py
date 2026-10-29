"""邮件会话线程还原与引用剥离（0.2.0 第三十九批，完整方案 §9.4）。

三件事：
- quote_strip：把一封含历史引用的邮件剥出**增量正文**（最新净回复）。底座
  mail-parser-reply（开源核实：PyPI 1.36，MIT，零依赖）；其 zh 词典漏了真实
  中文客户端的两种形态（「在…写道：」的「在」前缀、QQ 邮箱「------ 原始邮件 ------」
  分隔），本项目自补规则并入 HEADER_REGEX；库不可用/解析异常时降级自研逐行规则。
- subject_norm：Subject 去回复/转发前缀链（Re:/Fwd:/回复:/转发:/答复:/答: 等，
  中英混合、多层嵌套），得到线程分组键。
- rebuild_mail_threads：conv_messages（引用链优先归到根 Message-ID；无引用头时
  account+subject_norm 归组）→ 组内 ≥2 封建 threads(thread_type='source')，
  thread_items 按 sent_at 排序；thread_id 持久化到 conv_messages 保证幂等。

适配器本身不调 LLM（TODO 约束）。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# ---- Message-ID / Subject 归一化 ----

_MSGID_RE = re.compile(r"<([^<>]+)>")


def normalize_msgid(raw: str | None) -> str | None:
    """Message-ID 归一：去尖括号与空白；空返回 None。"""
    if not raw:
        return None
    m = _MSGID_RE.search(raw)
    inner = m.group(1) if m else raw
    inner = inner.strip()
    return inner or None


_SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:(?:re|fw|fwd|aw|sv|答复|回复|转发|转寄|答)\s*[:：]\s*)+", re.IGNORECASE)


def subject_norm(subject: str | None) -> str:
    """Subject 归一：剥 Re:/Fwd:/回复:/转发: 等前缀链（可嵌套），压缩空白。"""
    s = (subject or "").strip()
    prev = None
    while prev != s:
        prev = s
        s = _SUBJECT_PREFIX_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


# ---- 引用剥离（quote_strip） ----

# 中文客户端自补头（mail-parser-reply zh 词典缺的两种真实形态）：
# ① Foxmail/QQ 风格「在 2026年10月19日 10:00，xxx 写道：」（zh 词典要求行首直接年份）；
# ② QQ 邮箱「------ 原始邮件 ------」分隔横线。
_ZH_EXTRA_HEADERS = (
    r"^(?:> ?)*在\s*\d{4}年\d{1,2}月\d{1,2}日.{0,80}写道：\s*$",
    r"^(?:> ?)*-{2,}\s*原始邮件\s*-{2,}\s*$",
    r"^(?:> ?)*-{3,}\s*转发(?:的邮件|邮件)?\s*-{3,}\s*$",
)
# 降级自研规则（库不可用时）：引用行 + 中文/英文回复头行
_FALLBACK_HEADER_RE = re.compile(
    r"^(?:> ?)*(?:在\s*\d{4}年.{0,80}写道：\s*"
    r"|[-=]{3,}\s*原始邮件\s*[-=]{3,}\s*"
    r"|On\s.+\swrote:\s*"
    r"|发件人\s*[:：]|发送时间\s*[:：]|收件人\s*[:：]|主题\s*[:：]|From\s*:|Sent\s*:)",
    re.IGNORECASE)


def _parser_extra_pattern() -> "re.Pattern | None":
    """把自补中文头并入 mail-parser-reply 的 HEADER_REGEX；库缺失返回 None。"""
    try:
        from mailparser_reply import EmailReplyParser
    except ImportError:
        return None
    try:
        p = EmailReplyParser(languages=["zh", "en"])
        base = p.HEADER_REGEX.pattern
        extra = "|".join(f"({pat})" for pat in _ZH_EXTRA_HEADERS)
        return re.compile(f"{base}|{extra}", flags=re.MULTILINE | re.IGNORECASE)
    except Exception:  # 库版本行为变化 → 降级，不阻断同步
        return None


_EXTRA_PATTERN: "re.Pattern | None" = _parser_extra_pattern()


def quote_strip(text: str) -> str:
    """剥历史引用，返回增量正文（最新净回复）；剥不出（纯引用/空）返回原文截断兜底。"""
    text = (text or "").strip()
    if not text:
        return ""
    delta = ""
    if _EXTRA_PATTERN is not None:
        try:
            from mailparser_reply import EmailReplyParser

            p = EmailReplyParser(languages=["zh", "en"])
            # 预置组合正则（库的正则 + 自补中文头）——实例属性优先于惰性构建
            p._header_regex = _EXTRA_PATTERN
            msg = p.read(text)
            if msg.replies:
                delta = msg.replies[0].body.strip()
        except Exception:  # 解析异常 → 降级，不阻断
            delta = ""
    if not delta:
        delta = _fallback_strip(text)
    return delta.strip() or text[:4000]


def _fallback_strip(text: str) -> str:
    """自研降级：逐行扫到第一个回复头/引用头行即截断。"""
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        if _FALLBACK_HEADER_RE.match(line.strip()):
            break
        out.append(line)
    return "\n".join(out).strip()


# ---- furniture 剔除（批 97c，清洗层方案 §3.5）----
#
# 邮件尾部噪声四类：签名块 / 列表页脚 / 手机标语 / 法律免责。规则只在**尾部窗口**
# 里生效（正文中间讨论「怎么退订」不该被切），并跳过围栏代码块（``` 里的 `--`
# 是 markdown 分隔线，不是签名分隔线）。

_TAIL_LINES = 30            # 只在最后这么多非空行里找签名/标语
_TRAIL_FRACTION = 0.5       # 页脚/免责还要求在后 50% 非空行（防正文中段误切）

_SIG_DELIM_RE = re.compile(r"^--\s*$")   # RFC 3676：行内仅 "--" 或 "-- "
_MOBILE_RE = re.compile(
    r"^\s*(?:发自我的?\s*(?:iPhone|iPad|iPod)"
    r"|发送自\s*(?:iPhone|iPad)"
    r"|从我的\s*(?:iPhone|iPad)\s*发送"
    r"|Sent from my\s+(?:iPhone|iPad|iPod)"
    r"|Get Outlook for\s+(?:iOS|Android)"
    r"|发自\s*(?:网易邮箱大师|QQ\s*邮箱|Foxmail|钉钉|WPS)"
    r"|来自\s*(?:华为|小米|vivo|OPPO|荣耀)\s*手机)\s*$",
    re.IGNORECASE)
_FOOTER_RE = re.compile(
    r"^\s*(?:unsubscribe|退订|取消订阅|您收到(?:此|这)(?:封)?邮件"
    r"|You (?:received|are receiving) this"
    r"|(?:此|本|本次)(?:邮|电)件由.{0,60}发送)",
    re.IGNORECASE)
_DISCLAIMER_RE = re.compile(
    r"(?:本(?:邮件|电邮)(?:及其附件)?[^\n]{0,40}(?:保密|机密|泄露|任何形式)"
    r"|This (?:email|message) and any attachments)",
    re.IGNORECASE)


def _fence_mask(lines: list[str]) -> list[bool]:
    """围栏代码块标记（``` / ~~~ 成对翻转），与开头/结尾标记行一起跳过。"""
    mask = [False] * len(lines)
    fence = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("```") or s.startswith("~~~"):
            mask[i] = True
            fence = not fence
            continue
        mask[i] = fence
    return mask


def strip_furniture(text: str) -> tuple[str, dict[str, int]]:
    """剔邮件尾部家具，返回 (清洗后文本, 计数)。

    计数键：signature / list_footer / mobile / disclaimer / lines（删掉的非空行数）。
    删完为空则**原样返回**（只有签名的邮件不产出空正文）。
    """
    removed = {"signature": 0, "list_footer": 0, "mobile": 0,
               "disclaimer": 0, "lines": 0}
    if not (text or "").strip():
        return text, removed
    lines = text.splitlines()
    mask = _fence_mask(lines)
    nonempty = [i for i, line in enumerate(lines) if line.strip()]
    if not nonempty:
        return text, removed
    tail_from = nonempty[max(0, len(nonempty) - _TAIL_LINES)]
    trail_from = nonempty[max(0, int(len(nonempty) * _TRAIL_FRACTION))]

    cut_at: int | None = None      # 从这一行切到尾（取最早命中）
    drop: set[int] = set()         # 只删单行（手机标语）
    for i in range(tail_from, len(lines)):
        if mask[i]:
            continue
        s = lines[i].strip()
        if not s:
            continue
        if cut_at is not None and i >= cut_at:
            break                  # 更靠后的命中已被切掉，不再计数
        if _SIG_DELIM_RE.match(s):
            cut_at, removed["signature"] = i, removed["signature"] + 1
        elif i >= trail_from and _FOOTER_RE.match(s):
            cut_at, removed["list_footer"] = i, removed["list_footer"] + 1
        elif i >= trail_from and _DISCLAIMER_RE.search(s):
            cut_at, removed["disclaimer"] = i, removed["disclaimer"] + 1
        elif _MOBILE_RE.match(s):
            drop.add(i)
            removed["mobile"] += 1

    if cut_at is None and not drop:
        return text, removed
    limit = cut_at if cut_at is not None else len(lines)
    keep = [ln for i, ln in enumerate(lines) if i < limit and i not in drop]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()
    if not out:
        return text, {k: 0 for k in removed}   # 删空兜底：整封都是家具
    kept_nonempty = sum(1 for i in range(limit)
                        if i not in drop and lines[i].strip())
    removed["lines"] = len(nonempty) - kept_nonempty
    return out, removed


# ---- 线程还原 ----

def _hash_msgid(raw: bytes) -> str:
    return "sha1-" + hashlib.sha1(raw).hexdigest()[:16]


def rebuild_mail_threads(dl: Any, messages: list[dict[str, Any]],
                         run_id: str) -> dict[str, int]:
    """把本批邮件消息落 conv_messages 并还原 source 线程。

    messages = maildir 适配器产出的会话头记录（account/entry_id/message_id/
    in_reply_to/subject_norm/sent_at）。幂等：conv_messages 按消息 id upsert；
    已有 thread_id 的消息不重复分组。返回统计。
    """
    if not messages:
        return {"messages_staged": 0, "threads_built": 0}
    dl.upsert_conv_messages([
        {"id": m["message_id"], "entry_id": m["entry_id"],
         "in_reply_to": m.get("in_reply_to"),
         "subject_norm": m.get("subject_norm", ""),
         "sent_at": m.get("sent_at")}
        for m in messages
    ])
    staged = len(messages)

    # 分组：只处理未映射的消息（thread_id IS NULL）
    all_msgs = dl.list_conv_messages()
    by_id = {m["id"]: m for m in all_msgs}
    pending = [m for m in all_msgs if not m["thread_id"] and m["id"] in by_id]

    # ① 引用链归并：沿 in_reply_to 向上找到根（根=无 in_reply_to 或指向不存在的消息）
    group_of: dict[str, str] = {}   # 消息 id -> 组键

    def root_of(mid: str, depth: int = 0) -> str:
        if depth > 50 or mid not in by_id:
            return mid
        parent = by_id[mid].get("in_reply_to")
        if not parent or parent not in by_id or parent == mid:
            return mid
        return root_of(parent, depth + 1)

    for m in pending:
        if m.get("in_reply_to"):
            r = root_of(m["id"])
            group_of[m["id"]] = "ref:" + r
            # 根消息自身（无 in_reply_to，未进 ref 通道）也归入本组
            if r in by_id and r not in group_of:
                group_of[r] = "ref:" + r

    # ② 无引用头：account+subject_norm 归组（跨 account 不混）
    for m in pending:
        if m["id"] in group_of:
            continue
        group_of[m["id"]] = f"subj:{m.get('account', '')}:{m['subject_norm']}"

    # ③ 组内 ≥2 才建 source 线程；thread_items 按 sent_at 排序
    groups: dict[str, list[dict[str, Any]]] = {}
    for m in pending:
        groups.setdefault(group_of[m["id"]], []).append(m)
    threads_built = 0
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda x: (x.get("sent_at") or "9999", x["id"]))
        subject = members[0].get("subject_norm") or "(无主题)"
        account = members[0].get("account", "")
        name = f"📮 {subject[:60]}"
        existing = dl.list_threads(thread_type="source", limit=1000)
        found = next((t for t in existing if t["name"] == name), None)
        if found is None:
            thread = dl.create_thread(
                name, note=f"邮件会话线程（{account}，{len(members)} 封）",
                thread_type="source")
            threads_built += 1
            thread_id = thread.id
        else:
            thread_id = found["id"]
        # thread_items 顺序：members 已按 sent_at 排序，add_thread_item 依次追加；
        # 重复同步按（thread, entry）去重，不产生重复项
        for m in members:
            dl.add_thread_item(thread_id, m["entry_id"], relation_type="seq")
        dl.set_conv_thread([m["id"] for m in members], thread_id)
        dl.log_task(_now_iso(), "mail_threads", "build", thread_id,
                    {"group": key[:80], "members": len(members), "run_id": run_id})
    return {"messages_staged": staged, "threads_built": threads_built}


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")
