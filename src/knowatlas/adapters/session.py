"""AI 会话适配器（0.2.0 第五十七批，完整方案 §3.2/TODO Phase 3，零凭证）。

输入：session-harvester 的 exports 目录（harvester exporter.py 产物）：
  <root>/<category>/<YYYY-MM>/<YYYYMMDD-HHMM>__<adapter>__<slug>__<sid6>.json
  同名 .md 是渲染版；本适配器只读 **结构化 .json**（SessionRecord 平铺结构：
  source / session_id / title / created_at / updated_at / extra / messages），
  manifest（export_manifest.json）与解析失败的文件跳过计数，不中断同步。

映射（探针：条目含 title/session_id/created_at/turns 摘要）：
- source_type='session'，source_key=session_id，locator=session://<urlencode>
- native_path = "<category>/<YYYY-MM>"（给先验映射的路径信号）
- meta：harvester_source / origin / workspace / lossy / models / export_file /
  turns（总轮数）/ turns_content（对话轮数）
- inline_content = turns 摘要（前 12 个对话轮，每轮「role: 首行≤80 字」，
  截 4000）；全量对话正文（不含 note/[context] 系统注入轮）经
  stats["_full_bodies"] 交 sync 层落 content_store（与 mail 源同约定）。

线程增补（TODO 探针「conv_messages 轮次/父子关系与产物一致；原文不复制」）：
全部轮次（含 note）落 conv_messages——id=msg_key（session_id#序号），
in_reply_to 置 NULL（harvester 产物是平铺列表，无引用头，父子关系如实为
空）；每会话建一条 threads(thread_type='source')（复用 add_thread_item 的
(thread, entry) 去重保证幂等）。thread_items 是条目级粒度，轮次顺序由
msg_key 序号 + sent_at 承载。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..errors import AdapterError
from ..ids import content_hash
from ..models import Entry
from .base import AdapterOutput

_MANIFEST_NAME = "export_manifest.json"
_INLINE_CAP = 4000
_TURNS_SHOWN = 12
_TURN_LINE_CAP = 80


def _first_line(text: str, cap: int = _TURN_LINE_CAP) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line[:cap]


def _turns_summary(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        if m.get("role") == "note":
            continue
        lines.append(f"{m.get('role', '?')}: {_first_line(str(m.get('text') or ''))}")
        if len(lines) >= _TURNS_SHOWN:
            lines.append(f"…（共 {sum(1 for x in messages if x.get('role') != 'note')} 个对话轮）")
            break
    return "\n".join(lines)


def _full_body(messages: list[dict[str, Any]]) -> str:
    """全量对话正文（不含 note/[context] 系统注入轮；渲染口径与 exporter 同构）。"""
    out: list[str] = []
    for m in messages:
        if m.get("role") == "note":
            continue
        ts = f" · {m['timestamp']}" if m.get("timestamp") else ""
        out.append(f"## [{m.get('role', '?')}]{ts}")
        out.append(str(m.get("text") or "").strip())
        out.append("")
    return "\n".join(out).strip()


def collect_sessions(cfg: Any) -> AdapterOutput:
    """[sources.session] 配置：{harvester_dirs: [exports 根目录, ...]}。"""
    sec = cfg.get("sources.session") or {}
    if not sec.get("enabled"):
        return AdapterOutput([], {"skipped_disabled": 1})
    roots = [Path(str(p)) for p in (sec.get("harvester_dirs") or []) if str(p).strip()]
    if not roots:
        raise AdapterError(
            "sources.session 未配置任何 harvester 产物目录",
            hint="在 config/knowatlas.toml 配置 [sources.session] harvester_dirs = "
                 "[\"…/exports\"]（session-harvester exporter 的输出目录）")

    stats: dict[str, Any] = {"_full_bodies": {}, "conv_messages": [],
                             "files": 0, "skipped_parse": 0}
    entries: list[Entry] = []
    for root in roots:
        if not root.is_dir():
            raise AdapterError(
                f"sources.session：harvester 目录不存在或不可读：{str(root)!r}",
                hint="检查 config/knowatlas.toml 的 [sources.session] harvester_dirs")
        for f in sorted(root.rglob("*.json")):
            if f.name == _MANIFEST_NAME:
                continue
            stats["files"] += 1
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                sid = str(rec["session_id"]).strip()
                assert sid
            except Exception:
                stats["skipped_parse"] += 1
                continue
            rel = f.relative_to(root).as_posix()
            parts = rel.split("/")
            category = parts[0] if len(parts) > 2 else ""
            month = parts[1] if len(parts) > 2 else ""
            messages = rec.get("messages") or []
            note_turns = sum(1 for m in messages if m.get("role") == "note")
            meta = {
                "source_type": "session",
                "harvester_source": str(rec.get("source") or ""),
                "origin": str((rec.get("extra") or {}).get("origin") or ""),
                "workspace": str((rec.get("extra") or {}).get("workspace") or ""),
                "lossy": bool((rec.get("extra") or {}).get("lossy")),
                "models": (rec.get("extra") or {}).get("models") or {},
                "export_file": rel,
                "turns": len(messages),
                "turns_content": len(messages) - note_turns,
            }
            body = _full_body(messages)
            e = Entry.build(
                source_type="session", source_key=sid,
                title=str(rec.get("title") or "").strip() or sid[:60],
                locator=f"session://{quote(sid, safe='')}",
                locator_canonical=None,
                native_path="/".join(x for x in (category, month) if x) or None,
                inline_content=(_turns_summary(messages)[:_INLINE_CAP] or None),
                content_hash=content_hash(body) if body else None,
                meta=meta,
                created_at=rec.get("created_at"),
            )
            entries.append(e)
            if body:
                stats["_full_bodies"][e.id] = body
            for i, m in enumerate(messages):  # 全部轮次（含 note）→ conv_messages
                stats["conv_messages"].append({
                    "message_id": f"{sid}#{i:04d}",
                    "entry_id": e.id,
                    "in_reply_to": None,
                    "subject_norm": e.title,
                    "sent_at": str(m.get("timestamp") or "") or None,
                })
    return AdapterOutput(entries, stats)
