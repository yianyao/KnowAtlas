"""批 98：移动端响应式 + PWA 壳（2026-10-29）静态探针。

工单：`docs/design/变更工单-2026-10-29-响应式与PWA壳.md`
覆盖：
- `manifest.webmanifest` 是合法 JSON，含 name/start_url/display/icons，192/512 图标真实存在；
- `sw.js` 有 install/activate/fetch 三 handler、四张 HTML 入口进预缓存、原文代理 `/file` 排除、
  非 GET 直通（离线写不排队）、版本化缓存名；
- 页（index/graph/thread）都有 viewport、manifest 链接、theme-color、SW 注册片段（安全上下文守门）；
- `components.css` 有 820px 断点与抽屉/底部标签条/预览浮层规则；
- `favicon.ico` 与 `apple-touch-icon.png` 存在（顺手消掉 `/favicon.ico` 404）。

这些断言只读文件、不起服务——不依赖 DB/配置，可在任意环境跑。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "src" / "knowatlas" / "web" / "static"
SHELL_PAGES = ["index.html", "graph.html", "thread.html"]


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(_read("manifest.webmanifest"))


# ---------------------------------------------------------------- manifest


def test_manifest_core_fields(manifest: dict) -> None:
    assert manifest["name"] == "知道 KnowAtlas"
    assert manifest["short_name"]
    assert manifest["start_url"].startswith("/")
    assert manifest["scope"] == "/"
    assert manifest["display"] in {"standalone", "minimal-ui", "fullscreen"}
    assert manifest["theme_color"].startswith("#")
    assert manifest["background_color"].startswith("#")
    assert manifest["lang"] == "zh-CN"


def test_manifest_icons_exist_on_disk(manifest: dict) -> None:
    icons = manifest["icons"]
    sizes = {i["sizes"] for i in icons}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in icons)
    for icon in icons:
        path = STATIC / icon["src"].lstrip("/")
        assert path.is_file(), f"manifest 里的图标不存在：{icon['src']}"
        assert path.stat().st_size > 500, f"图标疑似空文件：{icon['src']}"


def test_manifest_shortcuts_point_at_real_pages(manifest: dict) -> None:
    for sc in manifest.get("shortcuts", []):
        assert (STATIC / sc["url"].lstrip("/")).is_file()


# ---------------------------------------------------------------- sw.js


@pytest.fixture(scope="module")
def sw() -> str:
    return _read("sw.js")


def test_sw_has_three_handlers(sw: str) -> None:
    for event in ("install", "activate", "fetch"):
        assert re.search(rf'self\.addEventListener\("{event}"', sw), f"缺 {event} handler"


def test_sw_precaches_the_shell_pages(sw: str) -> None:
    for page in ("/index.html", "/graph.html", "/thread.html"):
        assert f'"{page}"' in sw, f"预缓存清单缺 {page}"
    assert "/vendor/echarts.min.js" in sw
    assert "/tokens.css" in sw and "/components.css" in sw


def test_sw_never_caches_entry_file_proxy(sw: str) -> None:
    """原文代理可能是几十 MB 的 PDF —— 必须在进 API 分支前就被排除。"""
    assert 'path.endsWith("/file")' in sw
    file_guard = sw.index('path.endsWith("/file")')
    api_branch = sw.index('path.startsWith("/api/")')
    assert file_guard < api_branch, "排除 /file 的判断必须早于 /api 分支"


def test_sw_bypasses_non_get_requests(sw: str) -> None:
    """写操作一律直通网络：离线时不排队、不静默成功。"""
    assert 'request.method !== "GET"' in sw
    idx = sw.index('request.method !== "GET"')
    tail = sw[idx: idx + 80]
    assert "return" in tail


def test_sw_uses_versioned_caches(sw: str) -> None:
    assert re.search(r'const VERSION = "ka-', sw)
    assert "caches.delete" in sw, "activate 里必须清旧版本缓存"
    assert "UNREGISTER" in sw, "回滚通道（自注销）要留着"


def test_sw_api_cache_has_bound(sw: str) -> None:
    assert "API_MAX_ENTRIES" in sw
    assert re.search(r"const API_MAX_ENTRIES = \d+", sw)
    assert "OFFLINE" in sw, "未缓存的离线请求要回结构化 503，而不是白屏"


# ---------------------------------------------------------------- 三页头部/注册


@pytest.mark.parametrize("page", SHELL_PAGES)
def test_page_has_mobile_viewport(page: str) -> None:
    html = _read(page)
    assert 'name="viewport"' in html
    assert "width=device-width" in html


@pytest.mark.parametrize("page", SHELL_PAGES)
def test_page_links_manifest_and_theme(page: str) -> None:
    html = _read(page)
    assert 'rel="manifest"' in html
    assert 'name="theme-color"' in html
    assert 'rel="apple-touch-icon"' in html
    assert 'rel="icon"' in html


@pytest.mark.parametrize("page", SHELL_PAGES)
def test_page_registers_sw_guarded_by_secure_context(page: str) -> None:
    html = _read(page)
    assert 'navigator.serviceWorker.register("/sw.js")' in html
    assert "isSecureContext" in html, "内网 http 下注册会抛错，必须用安全上下文守门"


@pytest.mark.parametrize("page", SHELL_PAGES)
def test_script_tags_balanced(page: str) -> None:
    """加注册片段时最容易手滑吃掉一个 </script>——浏览器表现为
    `SyntaxError: Unexpected token '<'`，静态页看不出，这里钉住。"""
    html = _read(page)
    assert html.count("<script") == html.count("</script>"), f"{page} 的 <script> 标签不配对"


# ---------------------------------------------------------------- 响应式 CSS


def test_components_css_has_mobile_breakpoints() -> None:
    css = _read("components.css")
    assert "@media (max-width: 820px)" in css
    assert "@media (max-width: 560px)" in css


def test_components_css_mobile_layout_rules() -> None:
    css = _read("components.css")
    # 底部标签条 / 抽屉 / 预览浮层 三件事的关键选择器
    assert "#view-tabs { position: fixed" in css
    assert "body.side-open #layout > aside" in css
    assert "#side-mask" in css
    assert "width: auto !important" in css, "预览面板宽度是内联写的，必须 !important 才能压住"
    # 手机上 side-hide 的 30px 窄条不成立，树必须还原可见
    assert "body.side-hide #tree { display: block; }" in css


def test_mobile_drawer_selector_is_scoped_to_tree_aside() -> None:
    """页面里有两个 <aside>（分类树 + 预览面板）。抽屉规则若用裸 `aside`，
    预览面板会一起吃到 translateX(-102%)，实测浮层被推到 x=-398（不可见）。"""
    css = _read("components.css")
    mobile = css[css.index("@media (max-width: 820px)"):]
    for line in mobile.splitlines():
        stripped = line.strip()
        if stripped.startswith("aside {") or stripped.startswith("body.side-open aside"):
            pytest.fail(f"移动端抽屉规则必须写成 `#layout > aside`，发现了裸选择器：{stripped}")


def test_graph_and_thread_have_own_mobile_rules() -> None:
    assert "@media (max-width: 820px)" in _read("graph.html")
    assert "@media (max-width: 820px)" in _read("thread.html")
    assert "100dvh" in _read("graph.html") or "100dvh" in _read("thread.html")


# ---------------------------------------------------------------- 图标 / favicon


def test_favicon_and_touch_icon_exist() -> None:
    ico = STATIC / "favicon.ico"
    assert ico.is_file() and ico.stat().st_size > 500
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00", "不是合法 ICO 头"
    touch = STATIC / "apple-touch-icon.png"
    assert touch.is_file()
    assert touch.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_offline_badge_present_in_index() -> None:
    html = _read("index.html")
    assert 'id="offline-badge"' in html
    assert 'addEventListener("offline"' in html
    assert 'addEventListener("online"' in html