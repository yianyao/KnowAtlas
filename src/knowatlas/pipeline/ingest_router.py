"""入库分流路由（工单 2026-10-27《入库即抽点与自动老化》§2.2）。

一个条目到底走哪条抽取通道，只由**结构性信号**决定，零 LLM、零 IO（纯函数）：
locator scheme / 文件后缀 / 主机名 / 路径形态 / 正文字数。这样路由结果可测、可解释、
可复现；真正花 LLM 的是后面的抽取本身。

通道与理由码（`Route.tool` / `Route.reason`，稳定值，进 `meta.ingest`）：

| tool       | reason           | 含义                                              |
|------------|------------------|---------------------------------------------------|
| `pipeline` | `short`          | 正文 ≤ 分块目标：一次 integral/split 抽取           |
| `pipeline` | `chunked`        | 正文 6k–60k：管道内分块（R16）                       |
| `kpe`      | `pdf_book`       | PDF：走 KPE 的目录/页码分块（溯源能回到页）           |
| `kpe`      | `too_large`      | 正文超过 `points.chunk_total_max`： dumped 成 md 走 KPE |
| `fetch`    | `no_body`        | 还没有正文：先抓（抓完再判一次）                      |
| `skip`     | `needs_capability` | 视频/音频站：当前没有字幕能力，等 Phase B 凭证      |
| `skip`     | `repo_page`      | GitHub/Gitee 仓库首页：正文是文件列表+README，不抽点 |
| `skip`     | `not_knowledge`  | L0 价值守卫判定的首页/列表页/资源直链                |
| `skip`     | `too_short`      | 正文 < `_MIN_BODY_CHARS`，无点可抽                  |
| `skip`     | `other_scheme`   | mail:/emmx:/… 非 file/http(s)，正文由适配器给         |

**宁漏勿脏**：拿不准的一律 `skip` 并留 reason（管理页可见），绝不因为「自动」就乱抽。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

#: 仓库托管站：只有仓库首页算 repo_page，具体文件/issue/wiki 仍按网页处理。
REPO_HOSTS = frozenset({
    "github.com", "gitee.com", "gitlab.com", "bitbucket.org", "codeberg.org",
})

#: 音视频站：没有字幕/转写能力，自动处理只能标 needs_capability。
VIDEO_HOSTS = ("bilibili.com", "youtube.com", "youtu.be", "vimeo.com",
               "douyin.com", "xiaohongshu.com")

#: 书类后缀：PDF 有页与目录，走 KPE；其余办公文档按正文长度决定。
BOOK_SUFFIXES = frozenset({".pdf"})

MIN_BODY_CHARS = 50


@dataclass(frozen=True)
class Route:
    """一次路由结论：tool 只取 pipeline/kpe/fetch/skip，reason 为稳定理由码。"""

    tool: str
    reason: str
    detail: str = ""

    @property
    def skippable(self) -> bool:
        return self.tool == "skip"


def _host(locator: str) -> str:
    try:
        return (urlsplit(locator).hostname or "").lower()
    except ValueError:
        return ""


def _path(locator: str) -> str:
    try:
        return unquote(urlsplit(locator).path or "")
    except ValueError:
        return ""


def _scheme(locator: str) -> str:
    try:
        return (urlsplit(locator).scheme or "").lower()
    except ValueError:
        return ""


def _suffix(locator: str) -> str:
    p = _path(locator).rstrip("/")
    return Path(p).suffix.lower() if p else ""


def is_repo_root(locator: str) -> bool:
    """仓库首页判定：`/<owner>` 或 `/<owner>/<repo>`（可带尾斜杠），不含 /blob/ 等。"""
    if _host(locator) not in REPO_HOSTS:
        return False
    segs = [s for s in _path(locator).split("/") if s]
    if not segs:
        return True                     # github.com 本身
    if len(segs) > 2:
        return False                    # blob/tree/issues/wiki/... 当普通网页
    return segs[-1] not in ("blob", "tree", "issues", "pulls", "wiki", "releases")


def plan(locator: str, *, body_chars: int | None, chunk_chars: int = 6000,
         chunk_total_max: int = 60000, allow_kpe: bool = True) -> Route:
    """给出该条目的处理通道；`body_chars=None` 表示还没正文（先抓）。"""
    loc = str(locator or "").strip()
    scheme = _scheme(loc)
    if scheme not in ("http", "https", "file"):
        return Route("skip", "other_scheme", scheme or "无 scheme")

    if scheme in ("http", "https"):
        host = _host(loc)
        if any(host == h or host.endswith("." + h) for h in VIDEO_HOSTS):
            return Route("skip", "needs_capability", f"视频站 {host}：需字幕能力")
        if is_repo_root(loc):
            return Route("skip", "repo_page", f"仓库首页 {host}")

    if scheme == "file" and _suffix(loc) in BOOK_SUFFIXES:
        return Route("kpe", "pdf_book", "PDF：目录/页码分块")

    if body_chars is None:
        return Route("fetch", "no_body")
    if body_chars < MIN_BODY_CHARS:
        return Route("skip", "too_short", f"{body_chars} 字")
    if body_chars > chunk_total_max:
        if allow_kpe:
            return Route("kpe", "too_large", f"{body_chars:,} 字 > {chunk_total_max:,}")
        return Route("skip", "too_large", f"{body_chars:,} 字且 allow_kpe=false")
    if body_chars > chunk_chars:
        return Route("pipeline", "chunked", f"{body_chars:,} 字")
    return Route("pipeline", "short", f"{body_chars:,} 字")