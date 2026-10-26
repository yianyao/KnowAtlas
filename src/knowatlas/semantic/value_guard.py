"""L0 价值守卫（value_guard）：URL 结构一眼可判的「非知识内容」——零成本，不调 LLM。

定位（2026-10-20 用户定调）：收藏夹里大量条目"进去就是一个资源文件，或者是网站
首页/某个子目录页面"，此类条目 URL 结构即可判定，不需要 LLM 语义判断。LLM 侧
（classify_deep 的 kind=non）保留完整语义判据；本模块只取其结构可判子集，先短路，
省 token 也防漏判。

三类规则（判定结论与 LLM kind=non 同构，同走 meta.value_flag=not_knowledge
待清理候选，保留决定权在用户）：

| reason          | 规则                                                        |
|-----------------|-------------------------------------------------------------|
| resource_file   | locator path 尾段扩展名 ∈ RESOURCE_EXTS（压缩包/安装包/镜像/  |
|                 | 媒体/图片/二进制库）——"进去就是一个资源"                     |
| portal_homepage | http(s) URL 的 path 为空或 "/"——站点门户/导航首页            |
| index_subdir    | http(s) URL 的 path 以 "/" 结尾且非根——列表/导航子页         |

另有**正文层**判据 `is_index_page`（2026-10-26 P5 扩散加固）：URL 结构完全正常、
但正文就是一张带下载链接的书名/条目表——见下方函数说明。`judge_value` 只看 URL，
所以这类页面要靠 `is_index_page` 在正文层拦（扩散入库前 + `--value-scan` 存量体检）。

明确不判（防误杀）：
- PDF/电子书/Office 文档直链——可解析正文的知识资源（fetchers markitdown 路线）；
- 内容页——无尾斜杠路径、.html 后缀、GitHub 仓库页（README 即正文）等；
- file:// 条目的 portal 规则不启用（首页/列表页是 web 概念；文件夹源只收文件，
  目录层由 [sources] include/exclude 白名单控制）；resource_file 规则与 scheme
  无关，对 file:// 直链同样生效。

边界与兜底：误判条目用户可在 Web UI「待清理候选」一键否决（value_flag=ok，
之后本模块与 LLM 都不再标记它）；纯函数、无 IO，供 classify_coarse 的 L0 与
ksync --value-scan 价值体检复用。
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

# 资源类扩展名（小写、不含点）——进去就是文件本体而非可读知识页
RESOURCE_EXTS: frozenset[str] = frozenset({
    # 压缩包
    "zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "tbz2", "xz", "txz", "zst",
    # 安装包 / 应用包
    "exe", "msi", "apk", "ipa", "aab", "deb", "rpm", "pkg", "dmg", "appimage",
    "crx", "xpi", "whl", "jar", "war",
    # 磁盘镜像 / 虚拟机镜像
    "iso", "img", "vhd", "vhdx", "vmdk", "wim",
    # 音视频媒体
    "mp3", "wav", "flac", "aac", "ogg", "wma", "m4a",
    "mp4", "avi", "mkv", "mov", "wmv", "flv", "webm", "m4v",
    # 图片（栅格；svg 等矢量/图标不判，常伴文档出现）
    "png", "jpg", "jpeg", "gif", "bmp", "webp", "ico", "psd", "tif", "tiff",
    # 二进制库 / 种子
    "dll", "so", "dylib", "torrent",
})


def judge_value(locator: str | None) -> str | None:
    """按 URL 结构判定是否「非知识内容」；返回原因码，不是则返回 None。

    原因码（稳定值，进 meta.value_flag_reason）：
    - "resource_file"   —— path 尾段是资源文件本体
    - "portal_homepage" —— http(s) 站点首页/门户（path 为空或 "/"）
    - "index_subdir"    —— http(s) 列表/导航子页（path 以 "/" 结尾且非根）
    """
    url = str(locator or "").strip()
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None  # 非法 netloc（如全角字符）：URL 本身就不可用，不判价值
    if parts.scheme not in ("http", "https", "file"):
        return None  # 其余 scheme 适配层已过滤；防御性不判

    # 资源文件：path 尾段扩展名判定（与 scheme 无关，file:// 直链同样适用）
    path = unquote(parts.path or "")
    last_seg = path.rstrip("/").rsplit("/", 1)[-1] if path.rstrip("/") else ""
    ext = last_seg.rsplit(".", 1)[-1].lower() if "." in last_seg else ""
    if ext in RESOURCE_EXTS:
        return "resource_file"

    # portal 规则只对 http(s) 生效
    if parts.scheme not in ("http", "https"):
        return None
    raw = parts.path or ""
    if raw in ("", "/"):
        return "portal_homepage"
    if raw.endswith("/"):
        return "index_subdir"
    return None


# ---- 正文层判据：表格式索引/书目页（2026-10-26 P5 扩散加固）----
# 实测形态（`ebook-treasure-chest` 扩散进来的 20 条，全部同款）：
#   # 5G
#   | 书名 | 作者 | epub/mobi/azw3 |
#   | --- | --- | --- |
#   | 5G金融 | 莫开伟/陈名银/邱泉 | [下载](https://url89.ctfile.com/…) |
# URL 是正常的 blob 文件页（不是目录页、不是资源直链），judge_value 判不出来；
# 但「正文」就是一张带下载链接的书名表，没有可提炼的知识。
_INDEX_COLUMN_KEYS_CN = ("书名", "标题", "作者", "下载", "格式", "大小", "出版",
                         "年份", "语言", "简介", "链接", "文件名")
_INDEX_COLUMN_KEYS_EN = ("name", "title", "author", "size", "download", "format",
                         "year", "file", "link", "ext")
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\([^)]+\)")
_TABLE_SEP_RE = re.compile(r"^\|[\s:\-|]+\|$")


def _table_cells(line: str) -> str:
    """`| a | b |` → "a b"（小写，供列名关键词匹配）。"""
    return " ".join(c.strip() for c in line.strip().strip("|").split("|")).lower()


def _header_hits(line: str) -> int:
    """该行命中多少个「索引表列名」关键词（中英各一套）。"""
    cells = _table_cells(line)
    hits = sum(1 for k in _INDEX_COLUMN_KEYS_CN if k in cells)
    hits += sum(1 for k in _INDEX_COLUMN_KEYS_EN if re.search(rf"\b{k}\b", cells))
    return hits


def is_index_page(text: str, *, min_rows: int = 1, scan_limit: int = 4000) -> bool:
    """正文是不是「表格式索引/书目页」（纯文本、零 IO、零费用）。

    四条同时成立才判 True——全部朝「防误杀」方向取阈值：
    ① 表格成型：至少「表头 + `|---|` 分隔行 + `min_rows` 行数据」（默认 1 行；
       真库实测这些站存在「一本书一页」的形态，行数下限卡太死会漏掉一半）；
    ② 某一行命中列名关键词 ≥2（书名/作者/下载/… 或 name/author/download/…）；
    ③ 数据行里含 Markdown 链接 `[x](y)` 的比例 ≥50%（书目页每行一个下载链接）；
    ④ 表格行占非空行 ≥40%（正文主体就是这张表，而不是「文章里带一张对照表」）。

    ``` 围栏代码块内的行不参与统计（代码里的管道符不是表格）。
    只判「表格化清单」这一类；纯链接罗列（无表格）不判——留给 L0 的 URL 规则与
    人工复核，宁漏不误杀。真库 49 条有正文条目实测：20 条书目页全中、其余 0 误报。
    """
    lines: list[str] = []
    in_fence = False
    for raw in (text or "")[:scan_limit].splitlines():
        s = raw.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s:
            continue
        lines.append(s)
    if not lines:
        return False
    table = [ln for ln in lines
             if ln.startswith("|") and ln.endswith("|") and len(ln) >= 2]
    if len(table) < 3:                     # 表格成型：表头 + 分隔 + ≥1 数据行
        return False
    rows = [ln for ln in table if not _TABLE_SEP_RE.match(ln)]
    if not any(_header_hits(ln) >= 2 for ln in rows):
        return False
    data = [ln for ln in rows if _header_hits(ln) < 2]
    if len(data) < max(1, min_rows):
        return False
    linked = sum(1 for ln in data if _MD_LINK_RE.search(ln))
    if linked / len(data) < 0.5:
        return False
    return len(table) / len(lines) >= 0.4


def is_garbled(text: str, *, scan_limit: int = 5000) -> bool:
    """内容质量守卫（用户铁律 2026-10-20：乱码 = 不是可用的知识 = 没有）。

    规则（纯函数零 IO）：替换符 U+FFFD 占比 > 5%，或控制字符（\\t\\n\\r 除外）
    占比 > 10% → 乱码。只扫前 scan_limit 字符（内联正文上限 4000，余量足够）。
    """
    if not text:
        return False
    sample = text[:scan_limit]
    n = len(sample)
    if sample.count("\ufffd") / n > 0.05:
        return True
    ctrl = sum(1 for ch in sample if ord(ch) < 32 and ch not in "\t\n\r")
    return ctrl / n > 0.10
