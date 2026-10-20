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
