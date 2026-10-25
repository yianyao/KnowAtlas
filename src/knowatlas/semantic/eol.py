"""EOL 表与版本抽取（P2 老化，确定性优先；2026-10-26 工单 P2点级老化两型）。

只收录**有官方支持矩阵**的技术——没有官方 EOL 口径的（Flask、React、PyTorch…）
宁可不收，避免拿猜测当依据判 stale。每条 data 都带官方 URL（`SOURCES`），
判 stale 时原样写进 `point.meta.lifecycle.evidence`，人裁时点开就能核。

规则（与点级勘误同一套防幻觉纪律）：
- 版本比对**只认精确命中**：表里没有该版本 → `unknown`（调用方降 suspect），
  不按「比最大值新就是支持的」猜——表滞后时猜错的方向正是「把过时说成现行」；
- 家族 `N.x`：只有该大版本**全部**已录小版本都 EOL 才算 EOL；
- 裸 `node` 不入别名（会被「节点(node)」误伤），只认 `node.js` / `nodejs`。

`data/eol.json` 可覆盖或扩充内置表（`{"tech": {"版本": "YYYY-MM-DD"}}`，或
`{"tech": {"eol": {...}, "source": "..."}}` 形态）；`data/` 在 gitignore 内，换机不丢内置表。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# ---- 官方支持矩阵（日期=EOL 当日；来源见 SOURCES） ----

EOL: dict[str, dict[str, str]] = {
    "python": {"2.7": "2020-01-01", "3.6": "2021-12-23", "3.7": "2023-06-27",
               "3.8": "2024-10-07", "3.9": "2025-10-31"},
    "django": {"2.2": "2022-04-11", "3.2": "2024-04-01", "4.0": "2023-04-01",
               "4.1": "2023-12-05", "4.2": "2026-04-01", "5.0": "2025-04-01"},
    "nodejs": {"12": "2022-04-30", "14": "2023-04-30", "16": "2023-09-11",
               "18": "2025-04-30", "20": "2026-04-30"},
    "jquery": {"1.0": "2016-01-12", "2.0": "2016-01-12"},
    "vue": {"2.0": "2023-12-31"},
    "angularjs": {"1.0": "2022-01-01"},
    "php": {"7.4": "2022-11-28", "8.0": "2023-11-26", "8.1": "2025-12-31"},
    "ruby": {"2.7": "2023-03-31", "3.0": "2024-03-31"},
}

SOURCES: dict[str, str] = {
    "python": "https://devguide.python.org/versions/",
    "django": "https://www.djangoproject.com/download/",
    "nodejs": "https://nodejs.org/en/about/previous-releases",
    "jquery": "https://jquery.com/download/",
    "vue": "https://v2.vuejs.org/eol/",
    "angularjs": "https://docs.angularjs.org/misc/version-support-status",
    "php": "https://www.php.net/supported-versions.php",
    "ruby": "https://www.ruby-lang.org/en/downloads/branches/",
}

# 仍在官方支持期的大版本（家族判定用）：表里只记 EOL 过的版本，所以「该大版本还有活着的
# 小版本」必须显式声明——否则 'Python 3.x' 会被 3.6–3.9 的 EOL 记录带成 stale（假阳性，
# 2026-10-26 自检抓到）。判 stale 的方向必须保守：宁可 suspect，不可误杀。
LIVE_MAJORS: dict[str, set[str]] = {
    "python": {"3"},
    "django": {"5"},
    "nodejs": {"22", "24", "25"},
    "jquery": {"3"},
    "vue": {"3"},
    "angularjs": set(),
    "php": {"8"},
    "ruby": {"3"},
}

# 别名（小写；按词边界匹配）。顺序=匹配优先级，长别名在前防截断（angular.js 先于 angularjs）。
TECH_ALIASES: dict[str, tuple[str, ...]] = {
    "python": ("python", "cpython"),
    "django": ("django",),
    "nodejs": ("node.js", "nodejs", "node js"),
    "jquery": ("jquery",),
    "vue": ("vue.js", "vuejs", "vue"),
    "angularjs": ("angular.js", "angularjs"),
    "php": ("php",),
    "ruby": ("ruby",),
}

# 版本字面：2.7 / v3.8 / 3.x / 3（单大版本按 3.x 家族处理）。
# 大版本上限 50：'Python 2019' 里的 2019 是年份不是版本，直接不匹配。
_VERSION_TEMPLATE = (
    r"(?<![\w.])%s[vV]?(?:\s*(?:版|version|ver\.?))?\s*"
    r"(\d{1,2}(?:\s*\.\s*(?:\d{1,3}|[xX])){0,2})(?!\d)"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class VersionHit:
    """一处「技术 + 版本」出现（version 已归一化）。"""

    tech: str
    version: str        # "3.8"（精确）/ "2.x"（家族）
    raw: str            # 命中的原文片段，便于人裁对证


# 「最低版本要求」语境（要求 ≥X 不是「在用 X」）。实测踩过：'需要 Python 3.10 或更高
# 版本、Node.js 16.0 或更高版本' 被当成用过时版本 → 假 stale（2026-10-26 真库自检抓到）。
_REQ_AFTER = ("+", "＋", "或更高", "或更新", "或以上", "及以上", "以上", "更高版本",
              "or higher", "or later", "or above", "and above")
_REQ_BEFORE = ("≥", ">=", ">", "＞")


def _looks_like_requirement(text: str, start: int, end: int) -> bool:
    after = text[end:end + 16].strip().lower()
    if any(after.startswith(k) for k in _REQ_AFTER):
        return True
    before = text[max(0, start - 3):start].rstrip()
    return any(before.endswith(k) for k in _REQ_BEFORE)


def _alias_regex(alias: str) -> re.Pattern[str]:
    return re.compile(_VERSION_TEMPLATE % re.escape(alias), re.IGNORECASE)


_ALIAS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (tech, _alias_regex(alias))
    for tech, aliases in TECH_ALIASES.items()
    for alias in aliases
]


def _normalize(version: str) -> str:
    """'3.8.10' → '3.8'（丢掉补丁号）；'3' → '3.x'；'3.X' → '3.x'。"""
    parts = [p.strip().lower() for p in version.split(".") if p.strip()]
    if len(parts) >= 2 and parts[1] == "x":
        return f"{parts[0]}.x"
    if len(parts) == 1:
        return f"{parts[0]}.x"
    return f"{parts[0]}.{parts[1].lstrip('0') or '0'}"


def detect_versions(text: str, *, table: dict[str, dict[str, str]] | None = None) -> list[VersionHit]:
    """抽出一段文本里的全部「技术 + 版本」命中（按出现顺序，同 tech+version 去重）。"""
    if not text:
        return []
    avail = set((table or EOL).keys())
    out: list[VersionHit] = []
    seen: set[tuple[str, str]] = set()
    for tech, pattern in _ALIAS_PATTERNS:
        if tech not in avail:
            continue
        for m in pattern.finditer(text):
            if _looks_like_requirement(text, m.start(), m.end()):
                continue          # 「Python 3.10 或更高」= 环境门槛，不是版本过时
            version = _normalize(m.group(1))
            key = (tech, version)
            if key in seen:
                continue
            seen.add(key)
            out.append(VersionHit(tech=tech, version=version, raw=m.group(0).strip()))
    return out


def detect_techs(text: str, *, table: dict[str, dict[str, str]] | None = None) -> set[str]:
    """只认技术名（不看版本）——退场型（B 段）按技术栈分组的入口。"""
    if not text:
        return set()
    avail = set((table or EOL).keys())
    found: set[str] = set()
    for tech, aliases in TECH_ALIASES.items():
        if tech not in avail:
            continue
        for alias in aliases:
            if re.search(r"(?<![\w.])" + re.escape(alias) + r"(?![\w])", text, re.IGNORECASE):
                found.add(tech)
                break
    return found


def eol_status(tech: str, version: str, *, table: dict[str, dict[str, str]] | None = None,
               today: date | None = None) -> tuple[str, str]:
    """返回 (status, evidence)：status ∈ {'eol','supported','unknown'}。

    evidence 是可核查依据（官方支持矩阵 + 日期），直接写进点 meta 供人裁复核。
    """
    data = (table or EOL).get(tech) or {}
    if not data:
        return "unknown", f"{tech}：EOL 表未收录该技术"
    today = today or date.today()
    source = SOURCES.get(tech, "")

    def _day(s: str) -> date | None:
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None

    if version.endswith(".x"):
        major = version.split(".")[0]
        if major in LIVE_MAJORS.get(tech, set()):
            return "supported", (f"{tech} {version}：该大版本仍在官方支持期"
                                  + (f" {source}" if source else ""))
        dates = [(v, d) for v, d in data.items() if v.split(".")[0] == major]
        if not dates:
            return "unknown", f"{tech} {version}：EOL 表未收录该大版本"
        pending = [v for v, d in dates if (_day(d) or date.max) >= today]
        if pending:
            return "supported", (f"{tech} {version}：官方支持期内（{', '.join(sorted(pending))}）"
                                  + (f" {source}" if source else ""))
        last = max(d for _, d in dates)
        return "eol", f"{tech} {version}：全部已录小版本均于 {last} 前 EOL" + (f" {source}" if source else "")

    if version in data:
        eol_day = _day(data[version]) or date.min
        if eol_day < today:
            return "eol", f"{tech} {version}：官方 EOL 于 {data[version]}" + (f" {source}" if source else "")
        return "supported", f"{tech} {version}：官方支持至 {data[version]}" + (f" {source}" if source else "")
    # 表按大版本记的技术（nodejs 12/14/16…）：'14.18' 落到 '14' 上比
    major_key = version.split(".")[0]
    if major_key in data:
        return eol_status(tech, f"{major_key}.x", table=table, today=today)
    return "unknown", (f"{tech} {version}：EOL 表未收录该版本（表覆盖 "
                       + ", ".join(sorted(data)) + "）")


def load_table(data_dir: Path | None = None) -> dict[str, dict[str, str]]:
    """内置表 +（存在时）`<data_dir>/eol.json` 覆盖合并；坏文件忽略不炸主链路。"""
    table: dict[str, dict[str, str]] = {t: dict(v) for t, v in EOL.items()}
    if data_dir is None:
        return table
    path = Path(data_dir) / "eol.json"
    if not path.is_file():
        return table
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return table
    if not isinstance(raw, dict):
        return table
    for tech, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        eol = payload.get("eol") if isinstance(payload.get("eol"), dict) else payload
        cleaned = {str(k): str(v) for k, v in eol.items() if _DATE_RE.match(str(v))}
        if cleaned:
            table.setdefault(str(tech), {}).update(cleaned)
    return table