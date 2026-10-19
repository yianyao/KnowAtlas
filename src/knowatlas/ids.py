"""ID 生成、canonical URL 规范化、内容 hash（完整方案 §3.3 定稿）。"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 去除的跟踪参数（§3.3 第 4 步）；发现新跟踪参数在此追加并跑 canary
TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "spm", "from", "share_source", "share_medium", "share_plat", "share_tag",
    "share_token", "vd_source", "vd_extend", "ref", "referrer", "fbclid", "gclid",
})


def entry_id(source_type: str, source_key: str) -> str:
    """entry_id = sha1(f"{source_type}\\x1f{source_key}")[:16]。

    \\x1f 作分隔符防碰撞（如路径里恰好含 |）。
    重复导入同一源内容 → id 不变 → upsert 幂等。
    """
    raw = f"{source_type}\x1f{source_key}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def canonical_url(url: str) -> str | None:
    """canonical URL 五步规范化（§3.3）。

    非 http/https 返回 None（file/mail 等不走此逻辑）。
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.netloc:
        return None

    # 1. scheme 与 host 小写；去默认端口；丢弃用户信息段
    host = parts.hostname or ""
    host = host.lower()
    port = parts.port
    default_port = {"http": 80, "https": 443}.get(scheme)
    if port is not None and port != default_port:
        host = f"{host}:{port}"

    # 2. www. 前缀默认保留（无法探测时保守不合并，§3.3 第 2 步）

    # 3. 去 fragment；4. 去跟踪参数 + 按 key 排序重建
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    query_pairs.sort(key=lambda kv: (kv[0], kv[1]))
    query = urlencode(query_pairs)

    # 5. path 去尾斜杠（根路径除外）；大小写保留
    path = parts.path or ""
    if len(path) > 1:
        path = path.rstrip("/") or "/"

    return urlunsplit((scheme, host, path, query, ""))


def normalize_text(text: str) -> str:
    """内容 hash 前的文本规范化：统一 LF；去每行首尾空白；压缩连续空行；去首尾空行。"""
    lines = (line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    out: list[str] = []
    blank = False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif out and not blank:
            out.append("")
            blank = True
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def content_hash(text: str) -> str:
    """content_hash = sha1(规范化文本.encode()).hexdigest()。"""
    return hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()
