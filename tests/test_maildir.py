"""邮件适配器测试（0.2.0 第三十九批）：maildir 解析、幂等、会话线程还原、引用剥离。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowatlas.adapters.maildir import collect_maildirs
from knowatlas.errors import AdapterError
from knowatlas.ids import content_hash
from knowatlas.models import Entry, FetchResult
from knowatlas.pipeline.mail_threads import (
    normalize_msgid, quote_strip, rebuild_mail_threads, subject_norm,
)
from knowatlas.pipeline.sync import run_sync


def _eml(msg_id: str, subject: str, body: str, *,
         in_reply_to: str | None = None, references: str | None = None,
         date: str = "Mon, 20 Oct 2026 10:00:00 +0800",
         from_addr: str = "张三 <zhang@x.com>", to_addr: str = "li@x.com") -> bytes:
    lines = [
        f"Message-ID: <{msg_id}>",
        f"From: {from_addr}",
        f"To: {to_addr}",
        f"Subject: {subject}",
        f"Date: {date}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=UTF-8",
        "Content-Transfer-Encoding: 8bit",
    ]
    if in_reply_to:
        lines.append(f"In-Reply-To: <{in_reply_to}>")
    if references:
        lines.append(f"References: {references}")
    return ("\r\n".join(lines) + "\r\n\r\n" + body + "\r\n").encode("utf-8")


def _make_maildir(tmp_path: Path, files: dict[Path, bytes]) -> Path:
    for f, data in files.items():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    return tmp_path


def _cfg(tmp_path: Path, root: Path, enabled: bool = True):
    class Cfg:
        _data = {"sources": {"mail": {
            "enabled": enabled, "accounts": {"work": {"path": str(root)}}}}}

        def get(self, key):
            assert key == "sources.mail"
            return self._data["sources"]["mail"]
    return Cfg()


# ---- 解析与 meta ----

def test_parse_maildir_meta_and_body(tmp_path):
    root = _make_maildir(tmp_path, {
        tmp_path / "new" / "1": _eml("a@x", "季度总结", "这是正文第一段。\n第二段。"),
    })
    out = collect_maildirs(_cfg(tmp_path, root))
    assert len(out.entries) == 1
    e = out.entries[0]
    assert e.title == "季度总结"
    assert e.source_type == "mail"
    assert e.locator == "mail://work/a@x"
    assert e.meta["account"] == "work" and e.meta["mailbox"] == ""
    assert e.meta["from"] == "zhang@x.com" and e.meta["to"] == "li@x.com"
    assert e.meta["message_id"] == "a@x"
    assert e.created_at and e.created_at.startswith("2026-10-20")
    assert "这是正文第一段" in e.inline_content
    assert out.stats["_full_bodies"][e.id].startswith("这是正文第一段")


def test_parse_subfolder_mailbox_and_rfc2047(tmp_path):
    root = tmp_path / "acct"
    (root / "INBOX" / "cur").mkdir(parents=True)
    # RFC2047 编码的中文标题（两个编码词拼接）+ RFC2047 发件人
    import base64
    b64 = lambda s: base64.b64encode(s.encode("utf-8")).decode("ascii")
    raw = (
        "Message-ID: <b@x>\r\n"
        f"From: =?utf-8?B?{b64('老李')}?= <lao@x.com>\r\n"
        "To: me@x.com\r\n"
        f"Subject: =?utf-8?B?{b64('方案评审')}?= =?utf-8?B?{b64('意见')}?=\r\n"
        "Date: Tue, 21 Oct 2026 09:00:00 +0800\r\n"
        "Content-Type: text/plain; charset=UTF-8\r\n\r\n"
    ).encode("ascii") + "正文内容\r\n".encode("utf-8")
    (root / "INBOX" / "cur" / "m1").write_bytes(raw)
    out = collect_maildirs(_cfg(tmp_path, root))
    assert len(out.entries) == 1
    e = out.entries[0]
    assert e.meta["mailbox"] == "INBOX"
    assert e.native_path == "INBOX"
    assert "方案评审" in e.title and "意见" in e.title


# ---- 探针①：路径配置错误报错指向 sources.mail ----

def test_missing_path_error_points_to_config(tmp_path):
    with pytest.raises(AdapterError) as ei:
        collect_maildirs(_cfg(tmp_path, tmp_path / "nope"))
    assert "sources.mail" in str(ei.value)
    assert "sources.mail" in ei.value.hint
    assert "accounts.work.path" in ei.value.hint


def test_disabled_source_returns_empty(tmp_path):
    out = collect_maildirs(_cfg(tmp_path, tmp_path, enabled=False))
    assert out.entries == []


# ---- 幂等：重复 collect 同 key、重复 put_content 不重复 ----

def test_collect_idempotent_source_key(tmp_path):
    root = _make_maildir(tmp_path, {
        tmp_path / "new" / "1": _eml("a@x", "t", "正文"),
    })
    out1 = collect_maildirs(_cfg(tmp_path, root))
    out2 = collect_maildirs(_cfg(tmp_path, root))
    assert [e.id for e in out1.entries] == [e.id for e in out2.entries]


# ---- Subject 归一化与 Message-ID ----

def test_subject_norm_and_msgid():
    assert subject_norm("Re: Re: 回复: 方案评审") == "方案评审"
    assert subject_norm("Fwd: 转发: 季度目标") == "季度目标"
    assert subject_norm("  无前缀主题 ") == "无前缀主题"
    assert normalize_msgid("<abc@x>") == "abc@x"
    assert normalize_msgid(None) is None
    assert normalize_msgid("abc@x") == "abc@x"


# ---- 引用剥离（quote_strip）----

def test_quote_strip_english_and_chinese_quotes():
    en = ("Great, will fix tomorrow.\n\n"
          "On Mon, 20 Oct 2026 10:00, Zhang San wrote:\n"
          "> Please send the review notes\n"
          "> Thanks\n")
    delta = quote_strip(en)
    assert "will fix tomorrow" in delta
    assert "> Please send" not in delta and "wrote:" not in delta

    zh = ("好的，明天改完发你。\n\n小王\n\n"
          "在 2026年10月19日 10:00，老李 <lao@x.com> 写道：\n"
          "> 上周的方案评审意见发我一下\n> 谢谢\n")
    delta = quote_strip(zh)
    assert "明天改完发你" in delta
    assert "写道：" not in delta and "> 上周" not in delta

    qq = ("收到，意见如下。\n\n"
          "------------------ 原始邮件 ------------------\n"
          "发件人: 老李 <lao@x.com>\n"
          "时间: 2026年10月19日 10:00\n"
          "主题: 方案评审\n\n"
          "评审意见原文。\n")
    delta = quote_strip(qq)
    assert "意见如下" in delta
    assert "原始邮件" not in delta and "评审意见原文" not in delta


def test_quote_strip_fallback_no_reference_mail():
    text = "这是没有任何引用的普通邮件正文。"
    assert quote_strip(text) == text


# ---- 会话线程还原 ----

def _seed_entries(dl, n: int) -> list[Entry]:
    es = [Entry.build(source_type="mail", source_key=f"k{i}",
                      title=f"邮件{i}", locator=f"mail://work/m{i}",
                      meta={"source_type": "mail"}) for i in range(n)]
    dl.upsert_entries(es)
    return es


def test_thread_rebuild_by_in_reply_to_chain(dl):
    """探针②：A→B(In-Reply-To)→C(References) 还原为一条 source 线程、轮次按时间序。"""
    es = _seed_entries(dl, 3)
    msgs = [
        {"account": "work", "message_id": "m-a@x", "entry_id": es[0].id,
         "in_reply_to": None, "subject_norm": "方案评审",
         "sent_at": "2026-10-20T09:00:00+08:00"},
        {"account": "work", "message_id": "m-b@x", "entry_id": es[1].id,
         "in_reply_to": "m-a@x", "subject_norm": "方案评审",
         "sent_at": "2026-10-20T10:00:00+08:00"},
        {"account": "work", "message_id": "m-c@x", "entry_id": es[2].id,
         "in_reply_to": "m-b@x", "subject_norm": "Re: 方案评审",
         "sent_at": "2026-10-20T11:00:00+08:00"},
    ]
    stats = rebuild_mail_threads(dl, msgs, "run0000000000001")
    assert stats["threads_built"] == 1 and stats["messages_staged"] == 3
    threads = dl.list_threads(thread_type="source")
    assert len(threads) == 1 and threads[0]["item_count"] == 3
    full = dl.get_thread(threads[0]["id"])
    # 轮次顺序 = 时间序 A→B→C
    assert [it.entry_id for it in full.items] == [es[0].id, es[1].id, es[2].id]
    # 探针③的锚点部分：conv_messages.in_reply_to 指向被引用轮
    convs = {m["id"]: m for m in dl.list_conv_messages()}
    assert convs["m-b@x"]["in_reply_to"] == "m-a@x"
    assert convs["m-c@x"]["in_reply_to"] == "m-b@x"
    # 幂等：重复还原不建新线程
    stats2 = rebuild_mail_threads(dl, msgs, "run0000000000002")
    assert stats2["threads_built"] == 0
    assert len(dl.list_threads(thread_type="source")) == 1


def test_thread_group_by_subject_when_no_references(dl):
    """无引用头但 Subject 同链（原文 vs Re:）归入同一线程；不同主题不混。"""
    es = _seed_entries(dl, 3)
    msgs = [
        {"account": "work", "message_id": "s1@x", "entry_id": es[0].id,
         "in_reply_to": None, "subject_norm": "周报",
         "sent_at": "2026-10-20T09:00:00+08:00"},
        {"account": "work", "message_id": "s2@x", "entry_id": es[1].id,
         "in_reply_to": None, "subject_norm": "周报",
         "sent_at": "2026-10-20T10:00:00+08:00"},
        {"account": "work", "message_id": "s3@x", "entry_id": es[2].id,
         "in_reply_to": None, "subject_norm": "别的主题",
         "sent_at": "2026-10-20T10:30:00+08:00"},
    ]
    stats = rebuild_mail_threads(dl, msgs, "run0000000000001")
    assert stats["threads_built"] == 1
    threads = dl.list_threads(thread_type="source")
    assert len(threads) == 1 and threads[0]["item_count"] == 2  # 只含同主题两封


def test_single_message_no_thread(dl):
    es = _seed_entries(dl, 1)
    msgs = [{"account": "work", "message_id": "solo@x", "entry_id": es[0].id,
             "in_reply_to": None, "subject_norm": "独封", "sent_at": "2026-10-20T09:00:00+08:00"}]
    stats = rebuild_mail_threads(dl, msgs, "run0000000000001")
    assert stats["threads_built"] == 0
    assert dl.list_threads(thread_type="source") == []


# ---- 端到端：ksync mail 源（解析→入库→content_store→线程）----

def test_sync_mails_end_to_end(cfg, dl, registries, tmp_path):
    root = _make_maildir(tmp_path, {
        tmp_path / "new" / "m1": _eml(
            "t1@x", "项目讨论", "项目立项讨论：目标与里程碑。",
            date="Mon, 20 Oct 2026 09:00:00 +0800"),
        tmp_path / "new" / "m2": _eml(
            "t2@x", "Re: 项目讨论", "同意，我来排期。\n\n"
            "在 2026年10月20日 09:00，张三 <zhang@x.com> 写道：\n"
            "> 项目立项讨论：目标与里程碑。",
            in_reply_to="t1@x", date="Mon, 20 Oct 2026 10:00:00 +0800"),
    })
    cfg._data["sources"]["mail"] = {
        "enabled": True, "accounts": {"work": {"path": str(root)}}}
    locators, semantics = registries

    stats = run_sync(cfg, dl, locators, semantics, full=True)
    src = stats["sources"]["mail"]
    assert src["entries"] == 2 and src["created"] == 2
    assert src["messages_staged"] == 2 and src["threads_built"] == 1
    assert src["contents_stored"] == 2
    # 增量正文：Re 邮件的 inline 不含引用块；全量正文进 content_store
    by_title = {e.title: e for e in dl.list_entries(status="active", limit=10)}
    assert "同意，我来排期" in by_title["Re: 项目讨论"].inline_content
    assert "写道：" not in by_title["Re: 项目讨论"].inline_content
    full = dl.get_content(by_title["Re: 项目讨论"].content_hash)
    assert "项目立项讨论" in full
    # 线程已建且轮次正确
    threads = dl.list_threads(thread_type="source")
    assert len(threads) == 1 and threads[0]["item_count"] == 2

    # 二跑幂等：不新建、不重建线程
    stats2 = run_sync(cfg, dl, locators, semantics, full=True)
    src2 = stats2["sources"]["mail"]
    assert src2["created"] == 0 and src2["threads_built"] == 0
    assert len(dl.list_threads(thread_type="source")) == 1
