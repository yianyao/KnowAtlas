"""抽取结果校验：JSON 容错、quote 匹配、最小自洽闸门、去重。"""

from __future__ import annotations

import difflib
import json
import re

_PUNCT = re.compile(r"[\s，。！？；：、“”‘’（）《》〈〉…—·,.;:!?\"'()\[\]{}<>|]+")
_DOT_LEADER = re.compile(r"\.\s*\.\s*\.")
_BAD_START = re.compile(
    r"^(本章|本节|本文|作者|它|该|这些|上述|前面|接下来|下面|如上|由此可见)")
_SKIP_WORDS = ("目录", "版权所有", "ISBN")


def _norm(text: str) -> str:
    return _PUNCT.sub("", text or "")


def parse_points(content: str) -> tuple[list[dict], str]:
    """返回 (points, error)。容忍 ```json 围栏、前后废话、顶层数组。"""
    s = (content or "").strip()
    s = re.sub(r"^```(?:json)?\s*|```\s*$", "", s, flags=re.M).strip()
    candidates = [s]
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        candidates.append(m.group(0))
    m = re.search(r"\[.*\]", s, re.S)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):
            return [p for p in obj if isinstance(p, dict)], ""
        if isinstance(obj, dict):
            pts = obj.get("points")
            if isinstance(pts, list):
                return [p for p in pts if isinstance(p, dict)], ""
    return [], "输出不是合法 JSON 或缺少 points 数组"


def quote_ok(quote: str, chunk: str) -> bool:
    """精确（去标点空白）子串优先；不中再用相似度兜底（容忍标点改写）。"""
    q, c = _norm(quote), _norm(chunk)
    if not q or not c:
        return False
    if q in c:
        return True
    if len(q) < 8:
        return False
    window = max(len(q) + 20, int(len(q) * 1.5))
    for i in range(0, max(1, len(c) - len(q) + 1), max(1, len(q) // 2)):
        seg = c[i:i + window]
        if difflib.SequenceMatcher(None, q, seg).ratio() >= 0.9:
            return True
    return False


def gate_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    t = (text or "").strip()
    if len(t) < 10:
        reasons.append("too_short")
    if len(t) > 600:
        reasons.append("too_long")
    if _BAD_START.match(t):
        reasons.append("bad_start")
    if "……" in t or "..." in t:
        reasons.append("truncated")
    if _DOT_LEADER.search(t):
        reasons.append("toc")
    if any(w in t for w in _SKIP_WORDS) and len(t) < 80:
        reasons.append("boilerplate")
    if t.count("```") % 2 == 1:
        reasons.append("code_fence")
    return reasons


def dedupe(points: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for p in points:
        key = _norm(str(p.get("text") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out