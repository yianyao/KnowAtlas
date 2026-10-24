"""书签扩散抓取（0.2.0 第四十批，TODO Phase 2；用户 2026-10-20 需求）。

「像微信收藏全扒一样」：书签种子不只抓原文，还抓**同一目录页同一主题**的内容。
显式触发（`ksync --expand <entry_id>`），绝不自动跑；纯规则、可解释（relation_reason
纪律），LLM 相似判定后置。

扩散线索 = 种子页内链接中与种子**同目录**（同 scheme+host+父目录路径）者。整站
同 host 链接不收——导航/推荐噪音会演变成全站爬取，违背「显式触发、小步扩充」。

GitHub 仓库树扩散（批次 92 补充裁决 2026-10-23：链接要探「真正的知识」——收藏
仓库根，知识常在子目录如 /tree/main/cn-book）：种子为仓库根或 /tree/<分支>/<目录>
页时，候选 = 页内 (blob|tree)/<分支>/ 链接中位于种子目录范围内者；tree 子目录
再下钻一层取其文件（BFS ≤2 层、树页 ≤10 页、候选仍受 --expand-limit 封顶）；
blob 是确定性文件页（非门户/列表），**跳过 L0 价值守卫**；抓取走
fetch_with_fallback（blob→raw 直链重写，批次 92），locator 保留 blob 原链
（与用户书签一致、canonical 去重不受影响）。

候选过滤链（顺序固定）：canonical 化去锚 → 排除种子自身 → 未入库
（find_by_canonical / find_by_locator）→ L0 价值守卫（judge_value 放行，
GitHub 文件页豁免）→ limit 截断。
命中的候选逐条 fetch_with_fallback 抓正文入库：source_type="expand"
（bookmark 会被书签源 full 同步 archive_missing 归档；manual 语义不准），
meta 记 seed_entry_id + expand_reason（关联解释），照常走 classify_coarse 分类。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from ..errors import KnowAtlasError
from ..fetchers.base import fetch_with_fallback, is_skeleton_body
from ..ids import canonical_url, content_hash
from ..models import Entry, FetchResult
from ..registry.capability import FetchContext
from ..semantic.base import SemanticInput, TaskContext
from .kadd import ensure_category_path

_USER_AGENT = "KnowAtlas/0.1 (+personal knowledge indexer)"
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.IGNORECASE)
_GH_REPO = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)(?:/tree/([^/]+)((?:/[^/]+)*?))?/?$")
_GH_FILE_LINK = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/(blob|tree)/([^/]+)/(.+)$")
_GH_MAX_TREE_PAGES = 10  # 树页下钻上限（防大仓库失控抓取；候选另有 limit 封顶）

# 文件名黑名单（批次 94，用户截图指认 .nojekyll 空文件入库产点）：仓库元数据
# 与工程管理文件不是知识——候选层直接拦截，不发起抓取（宁缺毋脏；误拦可手动
# kadd 单条补录）。
_GH_FILE_NAME_BLACKLIST = frozenset({
    ".nojekyll", ".gitignore", ".gitattributes", ".gitmodules", ".editorconfig",
    ".npmignore", ".dockerignore", ".babelrc", ".eslintrc", ".prettierrc",
    "license", "license.md", "license.txt", "license.rst", "copying",
    "copying.txt", "notice", "notice.txt", "authors", "contributors",
    "code_of_conduct.md", "contributing.md", "security.md", "funding.yml",
})
# 扩展名黑名单：二进制/媒体/字体——文本管线抓回即垃圾（raw 直链也是字节流）。
_GH_EXT_BLACKLIST = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff",
    ".psd", ".ai", ".eps", ".pdf", ".epub", ".mobi", ".azw3",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".webm", ".avi", ".mov", ".mkv", ".flac", ".wav",
    ".exe", ".dll", ".so", ".dylib", ".jar", ".class", ".bin", ".dat",
    ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".o", ".a", ".wasm",
})


def _gh_file_blocked(blob_url: str) -> str | None:
    """GitHub blob 文件拦截判定：命中黑名单返回原因，None=放行（批次 94）。

    文件名黑名单（仓库元数据）+ 扩展名黑名单（二进制/媒体）——两类文件没有
    文本管线可提炼的知识。
    """
    m = _GH_FILE_LINK.match(blob_url)
    if not m:
        return None
    name = unquote(m.group(5).strip("/").rsplit("/", 1)[-1]).lower()
    if name in _GH_FILE_NAME_BLACKLIST:
        return f"文件名黑名单：{name}"
    dot = name.rfind(".")
    if dot > 0 and name[dot:] in _GH_EXT_BLACKLIST:
        return f"扩展名黑名单：{name[dot:]}"
    return None


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parent_dir(url: str) -> tuple[str, str]:
    """(host, 父目录路径)。根路径页面父目录 = "/"。"""
    parts = urlsplit(url)
    path = parts.path or "/"
    if path.endswith("/"):
        parent = path
    else:
        parent = path.rsplit("/", 1)[0] + "/"
    return (parts.hostname or "").lower(), parent


def _same_dir(seed_url: str, cand_url: str) -> bool:
    """同目录判定：scheme+host+父目录路径一致。"""
    a, b = urlsplit(seed_url), urlsplit(cand_url)
    return (_parent_dir(seed_url) == _parent_dir(cand_url)
            and a.scheme.lower() == b.scheme.lower())


def _candidate_links(seed_url: str, html: str) -> list[str]:
    """从种子 HTML 提取同目录链接：urljoin 归一 → 去锚 → 同目录过滤 → 保序去重。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in _HREF_RE.findall(html):
        joined = urljoin(seed_url, raw.strip())
        canon = canonical_url(joined)
        if canon is None or canon in seen:
            continue
        seen.add(canon)
        if _same_dir(seed_url, joined):
            out.append(joined)
    return out


def _github_scope(seed_url: str) -> tuple[str, str, str, str] | None:
    """GitHub 仓库/目录种子 → (owner, repo, 分支|'', 目录|'')；非仓库页 None。

    仓库根：branch/目录均空（任意分支任意位置）；/tree/main/cn-book：只收
    main 分支 cn-book 范围内。issues/pull 等页不匹配（无 /tree 且路径多段）。
    """
    m = _GH_REPO.match(seed_url)
    if not m or m.group(1).lower() in ("orgs", "topics", "features", "about",
                                       "pricing", "settings", "notifications"):
        return None
    return (m.group(1), m.group(2), m.group(3) or "", (m.group(4) or "").strip("/"))


def _gh_in_scope(scope_dir: str, rest: str) -> bool:
    """rest（blob/tree 路径）是否在种子目录范围内。"""
    if not scope_dir:
        return True
    return rest == scope_dir or rest.startswith(scope_dir + "/")


def _github_collect(seed_url: str, seed_html: str, client: Any, cfg: Any,
                    cap: int) -> tuple[list[str], list[tuple[str, str]]]:
    """GitHub 仓库树扩散候选：页内 blob 链接收集 + tree 子目录下钻（BFS ≤2 层）。

    seed_html 复用 expand_seed 已抓的种子页（不重复请求）；树页再逐个抓取
    （失败静默跳过——扩散是非关键增强，不因单个树页失败中止），页数受
    _GH_MAX_TREE_PAGES 封顶。返回 (blob URL 列表, 被黑名单拦截的 (url, 原因)
    列表)（保序去重，≤cap；批次 94 起文件名/扩展黑名单候选层拦截）。
    """
    scope = _github_scope(seed_url)
    assert scope is not None
    _, _, seed_branch, scope_dir = scope
    blobs: list[str] = []
    blocked: list[tuple[str, str]] = []
    seen: set[str] = set()
    tree_queue: list[tuple[str, str, int]] = [(seed_url, seed_html, 0)]
    tree_seen: set[str] = {seed_url}
    pages = 0
    while tree_queue and len(blobs) < cap and pages < _GH_MAX_TREE_PAGES:
        url, html, depth = tree_queue.pop(0)
        pages += 1
        for raw in _HREF_RE.findall(html):
            joined = urljoin(url, raw.strip())
            fm = _GH_FILE_LINK.match(joined)
            if not fm or fm.group(1).lower() != scope[0].lower() \
                    or fm.group(2).lower() != scope[1].lower():
                continue
            branch, rest = fm.group(4), fm.group(5).strip("/")
            if seed_branch and branch != seed_branch:
                continue
            if not _gh_in_scope(scope_dir, rest):
                continue
            if fm.group(3) == "blob":
                if joined in seen:
                    continue
                reason = _gh_file_blocked(joined)
                if reason is not None:
                    blocked.append((joined, reason))
                    continue
                seen.add(joined)
                blobs.append(joined)
                if len(blobs) >= cap:
                    break
            else:  # tree 子目录：下钻一层取其文件（depth ≤2 防深递归）
                if depth + 1 <= 2 and joined not in tree_seen:
                    tree_seen.add(joined)
                    try:
                        resp = client.get(
                            joined, follow_redirects=True,
                            timeout=float(cfg.get("fetch.timeout_seconds", 20)),
                            headers={"User-Agent": _USER_AGENT})
                    except Exception:
                        continue
                    if resp.status_code < 400:
                        tree_queue.append((joined, resp.text, depth + 1))
    return blobs[:cap], blocked


def _gh_blob_dir(blob_url: str) -> str:
    """blob 链接 → 仓库内目录路径（owner/repo/目录），作 native_path 溯源。"""
    m = _GH_FILE_LINK.match(blob_url)
    if not m:
        return ""
    rest = m.group(5).strip("/")
    dir_in_repo = rest.rsplit("/", 1)[0] if "/" in rest else ""
    return f"{m.group(1)}/{m.group(2)}/{dir_in_repo}".rstrip("/")


def expand_seed(cfg: Any, dl: Any, locators: Any, semantics: Any,
                seed_entry_id: str, limit: int = 20) -> dict[str, Any]:
    """对单个种子条目做一轮同目录扩散。返回统计 dict。"""
    run_id = uuid.uuid4().hex[:16]
    dl.start_run(run_id, "expand")
    stats: dict[str, Any] = {"seed": seed_entry_id, "candidates": 0,
                             "created": 0, "fetch_failed": 0,
                             "blocked_by_guard": 0, "already_known": 0,
                             "blocked_files": 0, "empty_body": 0,
                             "skeleton": 0}
    try:
        seed = dl.get_entry(seed_entry_id)
        if seed is None:
            raise KnowAtlasError(f"种子条目不存在：{seed_entry_id}",
                                 hint="entry_id 可在条目详情/URL 中查看")
        canon_seed = canonical_url(seed.locator)
        if canon_seed is None:
            raise KnowAtlasError(
                f"种子不是 http(s) 条目，无法扩散：{seed.locator}",
                hint="扩散只支持网页书签（http/https locator）")

        # 现抓种子 HTML（content_store 存的是 readability 纯文本，链接已丢）
        with httpx.Client() as client:
            ctx = FetchContext(config=cfg, datalayer=dl, http=client, run_id=run_id)
            try:
                resp = client.get(seed.locator, follow_redirects=True,
                                  timeout=float(cfg.get("fetch.timeout_seconds", 20)),
                                  headers={"User-Agent": _USER_AGENT})
            except Exception as exc:
                raise KnowAtlasError(
                    f"种子页面抓取失败：{seed.locator}（{exc}）",
                    hint="扩散需重新读取种子页 HTML 以提取同目录链接；检查网络后重试") from exc
            if resp.status_code >= 400:
                raise KnowAtlasError(
                    f"种子页面 HTTP {resp.status_code}：{seed.locator}",
                    hint="种子页可能已失效；可先跑 kcheck 体检")
            from ..semantic.value_guard import judge_value

            gh_scope = _github_scope(seed.locator)
            if gh_scope is not None:
                # GitHub 仓库树扩散（批次 92）：候选=blob 文件页（确定性知识文件，
                # 跳过 L0 守卫），locator 保留 blob 原链，native_path 记仓库目录；
                # 批次 94：黑名单文件候选层拦截（不发起抓取）
                blob_pool, blocked = _github_collect(
                    seed.locator, resp.text, client, cfg, cap=max(60, limit * 3))
                stats["blocked_files"] = len(blocked)
                for burl, reason in blocked:
                    dl.log_task(_now(), "expand", "blocked_file", burl,
                                {"reason": reason, "run_id": run_id})
                link_pool = [(link, True) for link in blob_pool]
            else:
                link_pool = [(link, False)
                             for link in _candidate_links(seed.locator, resp.text)]

            candidates: list[str] = []
            for link, is_gh_file in link_pool:
                c = canonical_url(link)
                if c == canon_seed:
                    stats["already_known"] += 1                 # 种子自身
                    continue
                stats["candidates"] += 1
                if dl.find_by_canonical(c) is not None \
                        or dl.find_by_locator(link):
                    stats["already_known"] += 1                 # 已入库（canonical 去重）
                    continue
                if not is_gh_file:                              # L0 守卫（gh 文件页豁免）
                    reason = judge_value(link)
                    if reason is not None:
                        stats["blocked_by_guard"] += 1          # L0：门户/列表/资源页
                        continue
                candidates.append(link)
                if len(candidates) >= max(1, int(limit)):
                    break

            created_ids: list[str] = []
            for link in candidates:
                try:
                    text, title = fetch_with_fallback(link, locators, ctx)
                except Exception as exc:
                    stats["fetch_failed"] += 1
                    dl.log_task(_now(), "expand", "fetch_fail", link,
                                {"error": str(exc)[:160], "run_id": run_id})
                    continue
                # 空/骨架守门（批次 94，用户截图指认垃圾条目入库产点）：
                # 升级后端与非 GitHub 路径的返回不做二次校验——入库前统一守门。
                if not text.strip():
                    stats["empty_body"] += 1
                    dl.log_task(_now(), "expand", "empty_body", link,
                                {"run_id": run_id})
                    continue
                if is_skeleton_body(text):
                    stats["skeleton"] += 1
                    dl.log_task(_now(), "expand", "skeleton_skip", link,
                                {"run_id": run_id})
                    continue
                c = canonical_url(link)
                is_gh = gh_scope is not None
                # gh 文件条目标题 =「仓库名 · 文件名」（批次 94，用户截图：来源
                # chips 显示裸文件名 navbar/index 无上下文）。不用种子标题——
                # gh 书签标题常是 GitHub 全量描述（数百字）；仓库名即书名/项目名，
                # 短且有定位力。
                if is_gh:
                    fname = unquote(link.rsplit("/", 1)[-1])
                    stem = fname.rsplit(".", 1)[0] if "." in fname else fname
                    name = f"{gh_scope[1]} · {stem}"[:120] or title or link
                else:
                    name = title or link.rsplit("/", 1)[-1] or link
                entry = Entry.build(
                    source_type="expand",
                    source_key=f"expand:{seed_entry_id}:{c}",
                    title=name,
                    locator=link,
                    locator_canonical=c,
                    inline_content=text[:4000]
                    + ("…[截断，全文在 content_store]" if len(text) > 4000 else ""),
                    content_hash=content_hash(text),
                    native_path=_gh_blob_dir(link) if is_gh
                    else _parent_dir(seed.locator)[1],
                    meta={"source_type": "expand", "seed_entry_id": seed_entry_id,
                          "expand_reason": "github_repo_tree" if is_gh
                          else "series_same_dir"},
                    created_at=_now(),
                )
                dl.upsert_entries([entry])
                dl.put_content(FetchResult(
                    text=text, content_hash=entry.content_hash,
                    fetcher=str(cfg.get("fetch.default_backend", "simple")),
                    fetched_at=_now()))
                dl.log_task(_now(), "expand", "create", entry.id,
                            {"seed": seed_entry_id, "url": link,
                             "reason": "series_same_dir", "run_id": run_id})
                created_ids.append(entry.id)
                stats["created"] += 1

            # 分类：复用 kadd 链路（L0 已过滤，classify_coarse 的 L0 短路不会误标）
            if created_ids:
                _categorize(dl, semantics, cfg,
                            [dl.get_entry(eid) for eid in created_ids if dl.get_entry(eid)],
                            run_id)
            stats["entry_ids"] = created_ids
            dl.log_task(_now(), "expand", "done", seed_entry_id, stats)
            return stats
    finally:
        dl.finish_run(run_id, stats)


def _categorize(dl: Any, semantics: Any, cfg: Any, entries: list[Any],
                run_id: str) -> None:
    """扩散条目批量 classify_coarse（与 sync._categorize 同款，未命中进暂存区）。"""
    from ..semantic.llm import LlmClient

    if not entries:
        return
    _, classify = semantics.resolve_task("classify_coarse")
    known = frozenset(dl.all_category_paths())
    inputs = [SemanticInput(entry_id=e.id, title=e.title, body=e.inline_content,
                            native_path=e.native_path,
                            meta={**e.meta, "locator": e.locator})
              for e in entries]
    outputs = classify(inputs, TaskContext(run_id=run_id, known_paths=known,
                                           llm=LlmClient.from_config(cfg), config=cfg))
    for entry, out in zip(entries, outputs):
        for classification in out.classifications:
            cid = ensure_category_path(dl, classification.category_path,
                                       classification.origin)
            dl.attach_category(entry.id, cid, classification.confidence,
                               classification.origin, run_id)
