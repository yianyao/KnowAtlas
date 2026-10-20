"""邮件 maildir 适配器（source_type=mail，完整方案 §3.2；0.2.0 第三十九批）。

设计定调：本项目**不做 IMAP 直连、不碰凭证**——外部同步工具（offlineimap 等）
把邮箱落成 maildir，本适配器只解析本地文件。目录不存在/不是 maildir →
AdapterError 明确指向 `sources.mail` 配置项（TODO 探针①）。

支持形态：
- 标准 maildir：root/{cur,new,tmp} = 收件箱；root/<子文件夹>/{cur,new,tmp} = 邮箱文件夹
  （一层，文件夹名入 meta.mailbox）；
- 导出工具直落：目录下直接一堆 .eml 文件（stats.mode 记录）。

契约：source_key = `{account}:{message_id}`（Message-ID 缺省 sha1(raw) 兜底，重同步幂等）；
locator = `mail://{account}/{message_id}`（mail scheme 契约既有预留，浏览器打不开
属预期，UI 按「复制路径」处理）；native_path = 邮箱文件夹；created_at = Date 头。

会话头（message_id/in_reply_to/references/subject_norm/sent_at）入 meta，
sync 层据此落 conv_messages 并还原 source 线程（pipeline/mail_threads.py）。
正文双轨（K1 语义的邮件版）：适配器产出全量正文；引用剥离（quote_strip）后的
增量正文由 sync 组装进 inline_content（检索摘要干净）；全量正文进 content_store
（FTS 全文完整）。清洗函数在 pipeline（适配器纪律：只翻译），此处仅 import 使用。
"""

from __future__ import annotations

import hashlib
import html as html_mod
import re
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..ids import content_hash
from ..models import Entry
from ..pipeline.mail_threads import (
    _hash_msgid, normalize_msgid, quote_strip, subject_norm,
)
from .base import AdapterOutput

_MAX_MESSAGES = 5000  # 单源邮件上限（防失控）
_MAILDIR_SUBDIRS = ("cur", "new", "tmp")


def _decode_date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat(timespec="seconds")


def _strip_html(raw: str) -> str:
    """text/html 降级：去 script/style/标签，解实体，压缩空行。"""
    txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    txt = html_mod.unescape(txt)
    lines = [ln.strip() for ln in txt.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(ln for ln in lines if ln).replace("\n\n\n", "\n\n")) or txt


def _extract_body(msg: Any) -> str:
    """取正文：优先 text/plain，降级 text/html 剥标签；附件跳过。"""
    if msg.is_multipart():
        plain = html = None
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain" and plain is None:
                try:
                    plain = part.get_content()
                except Exception:
                    plain = None
            elif ctype == "text/html" and html is None:
                try:
                    html = part.get_content()
                except Exception:
                    html = None
        body = plain if plain else (html if html else "")
        return body if plain else (_strip_html(str(body)) if body else "")
    try:
        body = msg.get_content()
    except Exception:
        body = ""
    if msg.get_content_type() == "text/html":
        return _strip_html(str(body))
    return str(body)


def _find_mailboxes(root: Path, stats: dict[str, Any]) -> list[tuple[str, Path]]:
    """发现 mailbox：root 自身（收件箱）+ 一层子文件夹。返回 (mailbox 名, 目录)。"""
    boxes: list[tuple[str, Path]] = []
    if any((root / d).is_dir() for d in _MAILDIR_SUBDIRS):
        boxes.append(("", root))
    elif any(root.glob("*.eml")):
        boxes.append(("", root))
        stats["mode"] = "eml_dir"
    if stats.get("mode") != "eml_dir":
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name in _MAILDIR_SUBDIRS:
                continue
            if any((child / d).is_dir() for d in _MAILDIR_SUBDIRS):
                boxes.append((child.name, child))
            elif any(child.glob("*.eml")):
                boxes.append((child.name, child))
                stats.setdefault("mode", "maildir+eml")
    return boxes


def _mailbox_files(box: Path, stats: dict[str, Any]) -> list[Path]:
    """mailbox 内待解析文件：标准 maildir 取 cur+new；eml 目录取 *.eml。"""
    files: list[Path] = []
    if (box / "cur").is_dir() or (box / "new").is_dir():
        for sub in ("new", "cur"):
            d = box / sub
            if d.is_dir():
                files.extend(sorted(p for p in d.iterdir() if p.is_file()))
    else:
        files.extend(sorted(box.glob("*.eml")))
    return files


def collect_maildirs(cfg: Any) -> AdapterOutput:
    """[sources.mail] 配置：{accounts: {账号名: {path: maildir 根}}} 或扁平
    {paths: {账号名: 路径}}。解析全部邮箱产出条目；stats["_full_bodies"] 携带
    entry_id → 全量正文（sync 层放 content_store，不进 meta）。"""
    sec = cfg.get("sources.mail") or {}
    if not sec.get("enabled"):
        return AdapterOutput([], {"skipped_disabled": 1})
    accounts = sec.get("accounts") or {}
    if not accounts:
        raise AdapterError(
            "sources.mail 未配置任何邮箱账号",
            hint="在 config/knowatlas.toml 配置 [sources.mail] accounts.<账号名>.path"
                 " = maildir 根目录（外部 IMAP 同步工具落盘，如 offlineimap）")

    stats: dict[str, Any] = {"_full_bodies": {}, "messages": 0, "skipped_parse": 0}
    entries: list[Entry] = []
    convs: list[dict[str, Any]] = []   # 会话头（sync 层落 conv_messages 还原线程）

    for account, acc_sec in accounts.items():
        acc_sec = acc_sec if isinstance(acc_sec, dict) else {"path": acc_sec}
        raw_path = str(acc_sec.get("path") or "").strip()
        root = Path(raw_path) if raw_path else None
        if root is None or not root.is_dir():
            raise AdapterError(
                f"sources.mail：账号 {account} 的 maildir 路径不存在或不可读：{raw_path!r}",
                hint="检查 config/knowatlas.toml 的 [sources.mail] accounts."
                     f"{account}.path；IMAP 凭证由外部同步工具管理，本项目只读本地 maildir")
        boxes = _find_mailboxes(root, stats)
        if not boxes:
            raise AdapterError(
                f"账号 {account} 的目录里没找到 mailbox（无 cur/new/tmp 子目录，也无 .eml）：{raw_path!r}",
                hint=f"确认外部同步工具已落盘 maildir 到 sources.mail.accounts.{account}.path")
        for mailbox, box_dir in boxes:
            for f in _mailbox_files(box_dir, stats):
                if stats["messages"] >= _MAX_MESSAGES:
                    stats["truncated"] = stats.get("truncated", 0) + 1
                    break
                try:
                    raw = f.read_bytes()
                    msg = BytesParser(policy=policy.default).parsebytes(raw)
                except Exception:
                    stats["skipped_parse"] += 1
                    continue
                msgid = normalize_msgid(str(msg.get("Message-ID") or "")) \
                    or _hash_msgid(raw)
                subject = str(msg.get("Subject") or "").strip() or "(无主题)"
                date_iso = _decode_date(str(msg.get("Date") or "")) \
                    or _mtime_iso(f)
                irt = normalize_msgid(str(msg.get("In-Reply-To") or ""))
                refs = " ".join(filter(None, (
                    normalize_msgid(x) for x in (msg.get_all("References") or [])
                    for x in x.split())))

                full_body = _extract_body(msg).strip()
                if not full_body:
                    stats["skipped_empty"] = stats.get("skipped_empty", 0) + 1
                    continue
                fhash = content_hash(full_body)
                delta = quote_strip(full_body)
                source_key = f"{account}:{msgid}"
                entry = Entry.build(
                    source_type="mail",
                    source_key=source_key,
                    title=subject,
                    locator=f"mail://{account}/{msgid}",
                    locator_canonical=None,
                    inline_content=delta,
                    content_hash=fhash,
                    native_path=mailbox or None,
                    meta={"source_type": "mail", "account": account,
                          "mailbox": mailbox, "from": parseaddr(str(msg.get("From") or ""))[1],
                          "to": parseaddr(str(msg.get("To") or ""))[1],
                          "date": date_iso, "message_id": msgid,
                          "in_reply_to": irt, "references": refs,
                          "subject_norm": subject_norm(subject)},
                    created_at=date_iso,
                )
                entries.append(entry)
                convs.append({"entry_id": entry.id, "account": account,
                              "message_id": msgid,
                              "in_reply_to": irt, "references": refs,
                              "subject_norm": subject_norm(subject),
                              "sent_at": date_iso})
                stats["_full_bodies"][entry.id] = full_body
                stats["messages"] += 1
            if stats["messages"] >= _MAX_MESSAGES:
                break
        if stats["messages"] >= _MAX_MESSAGES:
            break

    stats["conv_messages"] = convs   # sync 层 pop 出去做线程还原
    return AdapterOutput(entries, stats)


def _mtime_iso(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds")
