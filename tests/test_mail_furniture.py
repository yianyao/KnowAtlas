"""邮件 furniture 剔除 + inline 脱敏（批 97c / 8.9 邮件）。

覆盖：四类尾部家具（签名块 / 列表页脚 / 手机标语 / 免责声明）、围栏保护、
尾部窗口防误切、删空兜底、inline 链路顺序（quote_strip → furniture → redact）、
`[clean].redact_enabled` 开关、剥离率统计与告警。
"""

from __future__ import annotations

from pathlib import Path

from knowatlas.adapters.maildir import collect_maildirs
from knowatlas.pipeline.mail_threads import quote_strip, strip_furniture


def _eml(msg_id: str, subject: str, body: str, *,
         date: str = "Mon, 20 Oct 2026 10:00:00 +0800") -> bytes:
    lines = [
        f"Message-ID: <{msg_id}>",
        "From: 张三 <zhang@x.com>",
        "To: li@x.com",
        f"Subject: {subject}",
        f"Date: {date}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=UTF-8",
        "Content-Transfer-Encoding: 8bit",
    ]
    return ("\r\n".join(lines) + "\r\n\r\n" + body + "\r\n").encode("utf-8")


class _Cfg:
    def __init__(self, root: Path, *, redact: bool = True) -> None:
        self._mail = {"enabled": True, "accounts": {"work": {"path": str(root)}}}
        self._redact = redact

    def get(self, key, default=None):
        if key == "sources.mail":
            return self._mail
        if key == "clean.redact_enabled":
            return self._redact
        return default


def _collect(tmp_path: Path, bodies: dict[str, str], *, redact: bool = True):
    for i, (subject, body) in enumerate(bodies.items()):
        f = tmp_path / "new" / f"m{i}"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_eml(f"id{i}@x", subject, body))
    return collect_maildirs(_Cfg(tmp_path, redact=redact))


# ---- strip_furniture：四类规则 ----

def test_signature_block_cut():
    text = "方案我看了，按这个走。\n\n-- \n张三\n研发部 高级工程师\n13800138000"
    out, counts = strip_furniture(text)
    assert out == "方案我看了，按这个走。"
    assert counts["signature"] == 1 and counts["lines"] >= 3


def test_signature_requires_delimiter():
    """没有 RFC 3676 `--` 分隔线的落款不猜（宁漏勿误）。"""
    text = "方案我看了。\n\n张三\n研发部"
    out, counts = strip_furniture(text)
    assert out == text and counts["lines"] == 0


def test_list_footer_cut_chinese_and_english():
    zh = "本周周报见附件。\n\n您收到此邮件因为订阅了《周报》栏目。\n退订请点这里。"
    out, counts = strip_furniture(zh)
    assert out == "本周周报见附件。" and counts["list_footer"] == 1

    en = "See the attached report.\n\nYou received this email because you subscribed.\nUnsubscribe"
    out, counts = strip_furniture(en)
    assert out == "See the attached report." and counts["list_footer"] == 1


def test_mobile_tagline_removed_line_only():
    text = "收到，明天给你答复。\n\n发自我的 iPhone"
    out, counts = strip_furniture(text)
    assert out == "收到，明天给你答复。" and counts["mobile"] == 1


def test_disclaimer_cut():
    text = ("甲方合同条款已确认。\n\n"
            "本邮件及其附件含有保密信息，未经许可不得以任何形式复制或泄露。")
    out, counts = strip_furniture(text)
    assert out == "甲方合同条款已确认。" and counts["disclaimer"] == 1


# ---- 防误杀闸门 ----

def test_fence_protects_dash_delimiter():
    """``` 代码块里的 `--` 是 SQL/markdown 注释，不是签名分隔线。"""
    text = "示例查询：\n\n```sql\n-- 取最近一周\nSELECT 1;\n```\n\n结论：可行。"
    out, counts = strip_furniture(text)
    assert out == text and counts["signature"] == 0


def test_footer_in_body_middle_not_cut():
    """尾窗 + 后 50% 双闸门：正文中段讨论「退订流程」不误切。"""
    lines = [f"正文第 {i} 行，讨论业务流程细节。" for i in range(40)]
    lines[16] = "退订流程需要产品经理确认后再上线。"
    text = "\n".join(lines)
    out, counts = strip_furniture(text)
    assert out == text and counts["list_footer"] == 0


def test_furniture_all_removed_falls_back_to_original():
    """整封都是家具（只有签名）时不产出空正文。"""
    text = "-- \n张三\n13800138000"
    out, counts = strip_furniture(text)
    assert out == text and counts["lines"] == 0


# ---- inline 链路：quote_strip → furniture → redact ----

def test_adapter_inline_strips_quote_and_signature(tmp_path):
    body = ("同意，我来排期。\n\n"
            "-- \n李四\n项目经理\n13900139000\n\n"
            "在 2026年10月20日 09:00，张三 <zhang@x.com> 写道：\n"
            "> 项目立项讨论：目标与里程碑。")
    out = _collect(tmp_path, {"项目讨论": body})
    e = out.entries[0]
    assert e.inline_content == "同意，我来排期。"
    assert "13900139000" not in e.inline_content
    assert e.meta["mail_clean"]["furniture_lines"] >= 3
    # 全量正文（content_store 那份）保留签名原文（FTS 完整、可溯源）
    assert "13900139000" in out.stats["_full_bodies"][e.id]


def test_inline_redacts_phone_email_and_key(tmp_path):
    body = ("联系人手机 13800138000，邮箱 someone@x.com，"
            "临时密钥 sk-abcdefghijklmnop1234。")
    out = _collect(tmp_path, {"联系方式": body})
    e = out.entries[0]
    assert "13800138000" not in e.inline_content
    assert "[手机]" in e.inline_content
    assert "[邮箱]" in e.inline_content and "[密钥]" in e.inline_content
    assert e.meta["mail_clean"]["redacted"] >= 3
    # 正文库那份也脱敏（_store_bodies 的 clean_text），但适配器交出的全量正文不动
    assert "13800138000" in out.stats["_full_bodies"][e.id]


def test_redact_disabled_keeps_pii(tmp_path):
    out = _collect(tmp_path, {"联系方式": "手机 13800138000"}, redact=False)
    e = out.entries[0]
    assert "13800138000" in e.inline_content
    assert e.meta["mail_clean"]["redacted"] == 0


def test_strip_ratio_stats_and_near_empty_warning(tmp_path):
    long_quote = "原始邮件正文。" * 40      # 约 280 字，原文 ≥ 200
    body = ("收到。\n\n"
            "在 2026年10月19日 10:00，老李 <lao@x.com> 写道：\n" + long_quote)
    out = _collect(tmp_path, {"长引用": body})
    e = out.entries[0]
    assert e.inline_content == "收到。"
    assert out.stats["strip_near_empty"] == 1
    assert out.stats["strip_over90"] == 1
    assert any("剥后近空" in w for w in out.stats["warnings"])   # 只有近空才告警


def test_normal_reply_no_warning(tmp_path):
    body = ("方案已按上次评审意见改完，一共三处：\n"
            "1. 分类树合并口径；2. 词云缓存；3. 分卷摄取。\n"
            "详见附件。\n\n-- \n李四")
    out = _collect(tmp_path, {"评审回复": body})
    assert out.stats["warnings"] == []
    assert out.stats["strip_near_empty"] == 0


def test_quote_strip_then_furniture_order():
    """furniture 作用在去引用后的增量上：引用块里的 `--` 不会误切正文。"""
    body = ("结论：可行。\n\n"
            "在 2026年10月19日 10:00，老李 写道：\n"
            "> -- \n> 老李的签名\n")
    delta = quote_strip(body)
    out, counts = strip_furniture(delta)
    assert out == "结论：可行。" and counts["signature"] == 0