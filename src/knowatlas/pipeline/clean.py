"""通用清洗段（批 97a）：只保留知识，其余不进库。

依据：`docs/design/知识索引工具-清洗层方案.md` §5.1、`变更工单-2026-10-24-97a清洗层.md`、
`样本验证-2026-10-24.md`（真实噪音占比：页码行 11%、目录点线行 3%、推广尾 17 行）。

设计纪律：
- **可解释**：每条规则只认一种形态，删掉多少行按规则计数进 `CleanResult.removed`；
- **双闸门防误杀**：①规则自带占比门槛（如页码行占全篇 <2% 时视为数据/编号，不删）；
  ②整篇保留率低于 `min_keep_ratio` 时**整篇放弃**（返回原文 + abandoned=True），宁可不洗；
- **幂等**：`clean_common(clean_common(x).text).text == clean_common(x).text`；
- **保护**：``` 代码块内一行不动；表格行（`|` 开头）不参与"重复行"删除；
- **脱敏独立**：redact 与清洗分开调用，任何情况下（含 abandoned）都执行。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

# 页分隔符：与 `fetchers/pdf_fast.PAGE_BREAK` 同一个字符（那边是来源，这里只认值）
PAGE_BREAK = "\f"

# ---- 规则用到的形态 ----
_PAGE_NUM_RE = re.compile(r"^\s*(?:[ivxlcdm]{1,7}|\d{1,4})\s*$", re.IGNORECASE)
_TOC_LINE_RE = re.compile(r"(?:\s*\.\s*){3,}\s*\d{1,4}\s*$|…{2,}\s*\d{1,4}\s*$")
_TOC_HEAD_RE = re.compile(r"^\s*(?:目\s*录|contents|table\s+of\s+contents)\s*$", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"^\s*(?:-{3,}|={3,}|\*{3,}|_{3,})\s*$")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")

_PROMO_PATTERNS = (
    "公众号", "知识星球", "b站", "youtube", "小红书", "x/twitter", "推特",
    "官网", "created by", "仅供学习参考", "扫码", "加微信", "进群", "关注获取",
)

# ---- 脱敏（redact）：只认强特征，避免把正常文本改花 ----
# 顺序要紧：18 位证件先于手机号——否则身份证里的 11 位数字串会被当成手机号截断。
_REDACT_RULES = (
    (re.compile(r"\b\d{17}[\dXx]\b"), "[证件]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[邮箱]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[密钥]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[密钥]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[密钥]"),
)


@dataclass(frozen=True)
class CleanThresholds:
    """阈值集中在这里，测试可注入；默认值来自真实样本测算。"""

    page_number_ratio: float = 0.02   # 页码行占非空行比例 ≥ 此值才整体删
    toc_min_dot_leaders: int = 3      # 目录点线行至少这么多条才动
    repeat_max_len: int = 40          # 多短的行才参与"重复页眉页脚"
    repeat_min_count: int = 3         # 完全相同出现几次才算噪音
    repeat_max_ratio: float = 0.10    # 本规则总删除量上限（占非空行）
    repeat_structural_ratio: float = 0.02  # 单行出现次数超过全篇此比例 = 结构性重复，不删
    promo_window: int = 25            # 只在末尾这么多非空行里找推广
    promo_max_ratio: float = 0.05     # 推广行最多删全篇这么多比例
    min_keep_ratio: float = 0.80      # 低于此保留率整篇放弃（页码重的书正常删 10–15%）
    min_lines_for_ratio: int = 40     # 少于这么多非空行，不做占比类规则（短文档不猜）
    page_edge_lines: int = 3          # 页边界规则：每页首/尾各看几行（97b）
    page_furniture_ratio: float = 0.5  # 跳页重复率 ≥ 此值才算页眉页脚（97b）
    page_min_pages: int = 3           # 少于这么多页不做页边界规则（97b）


@dataclass
class CleanResult:
    text: str
    removed: dict[str, int] = field(default_factory=dict)
    keep_ratio: float = 1.0
    abandoned: bool = False
    redacted: int = 0
    is_navigation: bool = False
    paged: bool = False          # True = 走过页边界规则（说明来源带页分隔符，如 PDFium）

    def as_meta(self) -> dict:
        """进 Entry.meta['clean'] 的可解释统计（不含正文内容）。"""
        meta = {
            "removed": {k: v for k, v in self.removed.items() if v},
            "keep_ratio": round(self.keep_ratio, 3),
            "abandoned": self.abandoned,
            "redacted": self.redacted,
        }
        if self.paged:
            meta["paged"] = True
        return meta


def _nonempty_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _fence_mask(lines: list[str]) -> list[bool]:
    """标记哪些行在 ``` 代码块内（含围栏行本身），这些行一律不动。"""
    mask: list[bool] = []
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            mask.append(True)
            in_fence = not in_fence
            continue
        mask.append(in_fence)
    return mask


def _normalize(lines: list[str]) -> list[str]:
    """空白归一：去行尾空白/零宽字符、连续空行压成 1、连续分隔线去重。"""
    out: list[str] = []
    prev_blank = False
    prev_sep = False
    for line in lines:
        line = _ZERO_WIDTH_RE.sub("", line).rstrip()
        if not line.strip():
            if prev_blank:
                continue
            prev_blank, prev_sep = True, False
            out.append("")
            continue
        prev_blank = False
        is_sep = bool(_SEPARATOR_RE.match(line))
        if is_sep and prev_sep:
            continue
        prev_sep = is_sep
        out.append(line)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def _drop_toc(lines: list[str], mask: list[bool], removed: dict[str, int],
              thresholds: CleanThresholds) -> tuple[list[str], list[bool]]:
    """删目录块：点线+页码结尾的行，连同紧邻的"目录"标题。"""
    hits = [i for i, line in enumerate(lines)
            if not mask[i] and _TOC_LINE_RE.search(line)]
    if len(hits) < thresholds.toc_min_dot_leaders:
        return lines, mask
    drop: set[int] = set(hits)
    removed["toc_line"] = removed.get("toc_line", 0) + len(hits)
    # 目录标题：命中行上下 3 行内的"目录/Contents"
    for i in hits[:1] + hits[-1:]:
        for j in range(max(0, i - 3), min(len(lines), i + 4)):
            if not mask[j] and _TOC_HEAD_RE.match(lines[j]):
                if j not in drop:
                    drop.add(j)
                    removed["toc_head"] = removed.get("toc_head", 0) + 1
    keep = [i for i in range(len(lines)) if i not in drop]
    return [lines[i] for i in keep], [mask[i] for i in keep]


def _drop_page_numbers(lines: list[str], mask: list[bool], removed: dict[str, int],
                       thresholds: CleanThresholds) -> tuple[list[str], list[bool]]:
    """删页码行：仅当全篇占比达阈值（否则视为数据/编号列表）。"""
    total = sum(1 for line in lines if line.strip())
    if total < thresholds.min_lines_for_ratio:
        return lines, mask
    hits = [i for i, line in enumerate(lines)
            if not mask[i] and _PAGE_NUM_RE.match(line)]
    # 表格行不参与（"48" 可能是表格单元格）
    hits = [i for i in hits if not lines[i].strip().startswith("|")]
    if not hits or len(hits) / total < thresholds.page_number_ratio:
        return lines, mask
    removed["page_number"] = removed.get("page_number", 0) + len(hits)
    drop = set(hits)
    keep = [i for i in range(len(lines)) if i not in drop]
    return [lines[i] for i in keep], [mask[i] for i in keep]


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_CODE_TAIL = (":", "：", ";", "；", "{", "}", "(", ")", "=", "+", "*", "/", "\\", "|", "`")
_STRUCT_PREFIX = ("- ", "* ", "+ ", "> ", "#", "|", "```", "~~~")


def _furniture_candidate(s: str, thresholds: CleanThresholds) -> bool:
    """像页眉/页脚的一行：够长、不是代码/列表、带散文特征。

    真实教训（2026-10-24 实测）：不设这条，三种代码符号行（右括号、右花括号、三引号）
    和 `try:` 这类语句会被当成「重复 235 次」整批删掉，把整本书判成清洗失败
    （保留率 0.89 → 触发放弃闸门）。
    """
    if not (4 <= len(s) <= thresholds.repeat_max_len):
        return False
    if s.startswith(_STRUCT_PREFIX):
        return False
    if s.endswith(_CODE_TAIL):
        return False
    return len(_CJK_RE.findall(s)) >= 2 or len(_LATIN_RE.findall(s)) >= 6


def _is_periodic(idxs: list[int]) -> bool:
    """行距是否大致固定：页眉页脚按页重复，行距差异小；代码符号的出现位置随机。"""
    gaps = [b - a for a, b in zip(idxs, idxs[1:])]
    if not gaps:
        return False
    mean = sum(gaps) / len(gaps)
    if mean < 5:
        return False
    var = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    return (var ** 0.5) / mean <= 0.45


def _drop_repeated(lines: list[str], mask: list[bool], removed: dict[str, int],
                   thresholds: CleanThresholds) -> tuple[list[str], list[bool]]:
    """重复页眉/页脚：三重判据（像页眉 + 周期性 + 非结构性）才删，只留首次。"""
    total = sum(1 for line in lines if line.strip())
    counts: dict[str, list[int]] = {}
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        stripped = line.strip()
        if not stripped or not _furniture_candidate(stripped, thresholds):
            continue
        counts.setdefault(stripped, []).append(i)
    structural = max(8, int(total * thresholds.repeat_structural_ratio))
    cap = max(1, int(total * thresholds.repeat_max_ratio))
    drop: set[int] = set()
    for idxs in counts.values():
        if len(idxs) < thresholds.repeat_min_count or len(idxs) > structural:
            continue
        if not _is_periodic(idxs):
            continue
        drop.update(idxs[1:])
        if len(drop) >= cap:
            drop = set(sorted(drop)[:cap])
            break
    if not drop:
        return lines, mask
    removed["repeated_line"] = removed.get("repeated_line", 0) + len(drop)
    keep = [i for i in range(len(lines)) if i not in drop]
    return [lines[i] for i in keep], [mask[i] for i in keep]


def _drop_promo_tail(lines: list[str], mask: list[bool], removed: dict[str, int],
                     thresholds: CleanThresholds) -> tuple[list[str], list[bool]]:
    """推广/署名尾：只在末尾窗口内删命中行，且总删除量受比例上限约束。"""
    idx_nonempty = [i for i, line in enumerate(lines) if line.strip()]
    window = set(idx_nonempty[-thresholds.promo_window:])
    hits = [i for i in idx_nonempty
            if i in window and not mask[i]
            and any(p in lines[i].lower() for p in _PROMO_PATTERNS)]
    if not hits:
        return lines, mask
    cap = max(1, int(len(idx_nonempty) * thresholds.promo_max_ratio))
    if len(hits) > cap:
        hits = hits[-cap:] if cap < len(hits) else hits
    drop = set(hits)
    removed["promo_line"] = removed.get("promo_line", 0) + len(drop)
    keep = [i for i in range(len(lines)) if i not in drop]
    return [lines[i] for i in keep], [mask[i] for i in keep]


def is_navigation_doc(text: str) -> bool:
    """导航文件判定（navbar/sidebar 这类）：短、几乎全是链接/列表、没有完整句子。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or len(lines) > 12:
        return False
    link_like = sum(
        1 for line in lines
        if line.startswith(("-", "*", "|", "#"))
        or re.search(r"\]\([^)]+\)", line)
        or line.count(":") + line.count("：") == 1 and len(line) < 40
    )
    has_sentence = sum(1 for line in lines if re.search(r"[。！？!?]$", line))
    return link_like / len(lines) >= 0.6 and has_sentence <= 1


def redact(text: str) -> tuple[str, int]:
    """脱敏：手机/证件/邮箱/密钥 → 掩码。返回 (文本, 命中次数)。"""
    hits = 0
    for pattern, replacement in _REDACT_RULES:
        text, n = pattern.subn(replacement, text)
        hits += n
    return text, hits


def clean_common(text: str, thresholds: CleanThresholds | None = None,
                 *, redact_enabled: bool = True) -> CleanResult:
    """通用段清洗主入口：规则逐层过滤，最后过防误杀闸门。

    参数 redact_enabled 只影响脱敏，不影响清洗；abandoned 时仍脱敏（隐私优先）。
    """
    th = thresholds or CleanThresholds()
    if not text or not text.strip():
        return CleanResult(text=text)

    original_total = _nonempty_lines(text)
    result = CleanResult(text=text)

    if is_navigation_doc(text):
        # 导航文件（navbar/sidebar）整篇不是知识：正文置空，由 L0 判 not_knowledge
        result.is_navigation = True
        result.removed["navigation_doc"] = original_total
        result.keep_ratio = 0.0
        result.text = ""
        return result

    lines = _normalize(text.splitlines())
    mask = _fence_mask(lines)
    for rule in (_drop_toc, _drop_page_numbers, _drop_repeated, _drop_promo_tail):
        lines, mask = rule(lines, mask, result.removed, th)
    # 删完再归一一次（删行后可能出现连续空行）
    lines = _normalize(lines)

    cleaned = "\n".join(lines).strip()
    kept = _nonempty_lines(cleaned)
    result.keep_ratio = (kept / original_total) if original_total else 1.0
    # 闸门只对大文档生效：短文档（<40 行）里归一"连续分隔线/空行"本就该减行，
    # 那不是误杀，不该因此整篇放弃。
    if original_total >= th.min_lines_for_ratio and result.keep_ratio < th.min_keep_ratio:
        # 闸门：洗得太狠说明规则有问题，整篇放弃（保留原文），避免误杀
        result.abandoned = True
        result.text = text
    else:
        result.text = cleaned
    if redact_enabled:
        result.text, result.redacted = redact(result.text)
    return result


# ---- 页边界规则（批 97b）：只有 PDF 快速通道会给页分隔符 ----

def _edge_indexes(lines: list[str], edge: int) -> list[int]:
    """每页首/尾各取 edge 个非空行（页眉页脚只可能长在页边界上）。"""
    idx = [i for i, line in enumerate(lines) if line.strip()]
    if len(idx) <= edge * 2:
        return idx
    return idx[:edge] + idx[-edge:]


def _drop_page_furniture(pages: list[list[str]], removed: dict[str, int],
                         thresholds: CleanThresholds) -> list[list[str]]:
    """页边界清洗：删页边页码（无条件）+ 跨页重复的页眉页脚。

    与 `clean_common` 的分工：那边靠"占全篇比例"猜（<2% 不敢删，怕误删数据行）；
    这里有页边界，**页边上的独立数字必然是页码**，不需要再猜。
    """
    if len(pages) < thresholds.page_min_pages:
        return pages

    # ① 页边独立数字/罗马数字 → 无条件删（页码）
    numbers = 0
    for lines in pages:
        for i in _edge_indexes(lines, thresholds.page_edge_lines):
            if _PAGE_NUM_RE.match(lines[i]):
                lines[i] = ""
                numbers += 1
    if numbers:
        removed["page_number_edge"] = removed.get("page_number_edge", 0) + numbers

    # ② 出现在 ≥页数×比例 的页边行 = 页眉页脚（章节标题只出现在自己那几页，比例不够）
    per_page: list[set[str]] = []
    for lines in pages:
        per_page.append({lines[i].strip() for i in _edge_indexes(lines, thresholds.page_edge_lines)
                         if lines[i].strip()})
    seen: dict[str, int] = {}
    for names in per_page:
        for name in names:
            seen[name] = seen.get(name, 0) + 1
    threshold = max(2, int(len(pages) * thresholds.page_furniture_ratio))
    furniture = {
        name for name, count in seen.items()
        if count >= threshold
        and len(name) <= thresholds.repeat_max_len
        and _furniture_candidate(name, thresholds)
    }
    if not furniture:
        return pages
    dropped = 0
    for lines in pages:
        for i in _edge_indexes(lines, thresholds.page_edge_lines):
            if lines[i].strip() in furniture:
                lines[i] = ""
                dropped += 1
    if dropped:
        removed["page_furniture"] = removed.get("page_furniture", 0) + dropped
    return pages


def clean_paged(text: str, thresholds: CleanThresholds | None = None,
                *, redact_enabled: bool = True) -> CleanResult:
    """带页边界的清洗（PDF 快速通道）：页边规则 → 通用段 → 闸门 → 脱敏。

    落库前一定去掉 `\\f`（换成换行），避免控制符进正文库与检索结果。
    """
    th = thresholds or CleanThresholds()
    if PAGE_BREAK not in text:
        return clean_common(text, thresholds=th, redact_enabled=redact_enabled)

    original_total = _nonempty_lines(text)
    result = CleanResult(text=text, paged=True)
    if is_navigation_doc(text):
        result.is_navigation = True
        result.removed["navigation_doc"] = original_total
        result.keep_ratio = 0.0
        return result

    pages = [page.splitlines() for page in text.split(PAGE_BREAK)]
    pages = _drop_page_furniture(pages, result.removed, th)
    joined = "\n".join(line for page in pages for line in page)
    # 内层先不过闸门（阈值 0.0），闸门放到"页边删除 + 通用段删除"都算完再判一次，
    # 否则两段各自守 0.80、合起来可能已经删掉 30%。
    inner = clean_common(joined, thresholds=replace(th, min_keep_ratio=0.0),
                         redact_enabled=False)
    result.removed.update(inner.removed)
    result.is_navigation = inner.is_navigation
    cleaned = inner.text.replace(PAGE_BREAK, "\n")
    kept = _nonempty_lines(cleaned)
    result.keep_ratio = (kept / original_total) if original_total else 1.0
    if original_total >= th.min_lines_for_ratio and result.keep_ratio < th.min_keep_ratio:
        result.abandoned = True
        cleaned = text.replace(PAGE_BREAK, "\n")
    result.text = cleaned
    if redact_enabled:
        result.text, result.redacted = redact(result.text)
    return result


def clean_text(text: str, thresholds: CleanThresholds | None = None,
               *, redact_enabled: bool = True) -> CleanResult:
    """清洗统一入口：有页分隔符走 `clean_paged`，否则走 `clean_common`。"""
    if PAGE_BREAK in text:
        return clean_paged(text, thresholds=thresholds, redact_enabled=redact_enabled)
    return clean_common(text, thresholds=thresholds, redact_enabled=redact_enabled)
