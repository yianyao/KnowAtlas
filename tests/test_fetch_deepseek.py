"""DeepSeek Fetch 升级后端测试（0.2.0 第二十四批）：全 mock，不发真实请求。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from knowatlas.errors import FetchError
from knowatlas.fetchers import http_deepseek
from knowatlas.fetchers.base import fetch_with_fallback

DEEPSEEK_URL = "https://api.deepseek.com/v1/tools/fetch"


class FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or str(self._payload)

    def json(self):
        if self._payload == "NOT_JSON":
            raise ValueError("no json")
        return self._payload


class FakeHttp:
    """ctx.http 替身：get 全失败（模拟 simple 后端环境挂掉），post 按脚本回放。"""

    def __init__(self, post_results=None, post_exc=None):
        self.calls = []
        self._results = list(post_results or [])
        self._post_exc = post_exc

    def get(self, *a, **k):
        raise RuntimeError("simulated network failure")

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "auth": headers.get("Authorization", "")})
        if self._post_exc:
            raise self._post_exc
        return self._results.pop(0)


def make_ctx(cfg, http, monkeypatch):
    monkeypatch.setenv("KNOWATLAS_LLM_API_KEY", "sk-test-deepseek")
    return SimpleNamespace(config=cfg, datalayer=None, http=http, run_id="t")


def test_simple_failure_upgrades_to_deepseek(cfg, monkeypatch):
    """探针（TODO Phase 2）：mock simple 失败的 URL，自动走 DeepSeek 拿到正文。"""
    http = FakeHttp(post_results=[FakeResp(payload={"title": "T", "content": "# 正文" * 50})])
    ctx = make_ctx(cfg, http, monkeypatch)
    cfg._data.setdefault("fetch", {})["fallback_backend"] = "deepseek"
    text, title = fetch_with_fallback("https://hard.example/a", None, ctx)
    assert title == "T" and "正文" in text
    assert http.calls[0]["url"] == DEEPSEEK_URL
    assert http.calls[0]["auth"] == "Bearer sk-test-deepseek"


def test_429_backs_off_then_succeeds(cfg, monkeypatch):
    sleeps = []
    monkeypatch.setattr(http_deepseek.time, "sleep", sleeps.append)
    http = FakeHttp(post_results=[FakeResp(429, text="rate"), FakeResp(429, text="rate"),
                                  FakeResp(payload={"title": "t", "content": "内容足够长" * 30})])
    ctx = make_ctx(cfg, http, monkeypatch)
    text, _ = http_deepseek.fetch_page("https://qps.example/a", ctx)
    assert "内容足够长" in text
    assert sleeps == [0.8, 1.6]  # 指数退避 0.8s 起步翻倍
    assert len(http.calls) == 3


def test_429_exhausted_raises(cfg, monkeypatch):
    monkeypatch.setattr(http_deepseek.time, "sleep", lambda s: None)
    http = FakeHttp(post_results=[FakeResp(429, text="rate")] * 5)
    ctx = make_ctx(cfg, http, monkeypatch)
    with pytest.raises(FetchError, match="429"):
        http_deepseek.fetch_page("https://qps.example/b", ctx)
    assert len(http.calls) == 4  # max_retries=3 → 首调 + 3 重试


def test_other_4xx_no_retry(cfg, monkeypatch):
    """非 429 的非 200 直接抛——重试同请求无益，不烧钱。"""
    http = FakeHttp(post_results=[FakeResp(403, text="forbidden")])
    ctx = make_ctx(cfg, http, monkeypatch)
    with pytest.raises(FetchError, match="403"):
        http_deepseek.fetch_page("https://x.example/c", ctx)
    assert len(http.calls) == 1


def test_empty_content_raises(cfg, monkeypatch):
    http = FakeHttp(post_results=[FakeResp(payload={"title": "t", "content": ""})])
    ctx = make_ctx(cfg, http, monkeypatch)
    with pytest.raises(FetchError, match="空正文"):
        http_deepseek.fetch_page("https://x.example/d", ctx)


def test_missing_key_raises_with_hint(cfg, monkeypatch):
    ctx = make_ctx(cfg, FakeHttp(), monkeypatch)  # make_ctx 会设 key，故删在它之后
    monkeypatch.delenv("KNOWATLAS_LLM_API_KEY", raising=False)
    http = FakeHttp()
    ctx.http = http
    with pytest.raises(FetchError, match="KNOWATLAS_LLM_API_KEY"):
        http_deepseek.fetch_page("https://x.example/e", ctx)
    assert http.calls == []  # 未发请求


def test_bad_url_rejected_without_request(cfg, monkeypatch):
    http = FakeHttp()
    ctx = make_ctx(cfg, http, monkeypatch)
    with pytest.raises(FetchError, match="8192"):
        http_deepseek.fetch_page("https://x.example/" + "a" * 9000, ctx)
    with pytest.raises(FetchError, match="http/https"):
        http_deepseek.fetch_page("ftp://x.example/f", ctx)
    assert http.calls == []


# ---- 批次 92：GitHub raw 重写 + 骨架检测（裁决 12：抓来的必须是知识） ----

def test_github_blob_rewrites_to_raw():
    from knowatlas.fetchers.base import github_raw_url
    assert github_raw_url(
        "https://github.com/user/repo/blob/main/README.md"
    ) == "https://raw.githubusercontent.com/user/repo/main/README.md"
    assert github_raw_url(
        "https://www.github.com/u/r/raw/dev/docs/a.md"
    ) == "https://raw.githubusercontent.com/u/r/dev/docs/a.md"
    # 非 blob/raw 页不重写（仓库首页/issues 无对应 raw 资源）
    assert github_raw_url("https://github.com/user/repo") == "https://github.com/user/repo"
    assert github_raw_url("https://github.com/user/repo/issues/1").startswith(
        "https://github.com/")


def test_is_skeleton_body_thresholds():
    from knowatlas.fetchers.base import is_skeleton_body
    chrome = ["Skip to content", "Sign in", "Notifications", "Fork", "Star",
              "Pull requests", "Issues", "Actions", "Projects", "Wiki"]
    assert is_skeleton_body("\n".join(chrome))
    assert not is_skeleton_body("\n".join(chrome[:7]))          # 行数不足不判
    body = "\n".join(f"这是正常的正文段落第{i}行，内容充实。" for i in range(12))
    assert not is_skeleton_body(body)                            # 正文零命中
    # 单行兜底（readability 压行）：短语密度 ≥8 且 ≤80 字符/命中
    wall = "Skip to content Sign in Notifications Fork Star Pull requests " \
           "Issues Actions Projects Wiki"
    assert is_skeleton_body(wall)
    assert not is_skeleton_body("GitHub 教程：fork 与 star 的区别。" * 10)  # 密度不够不判


def test_http_simple_raw_direct_text(cfg):
    """raw.githubusercontent.com 直链：纯文本直取（不经 readability、不骨架检测）。"""
    from knowatlas.fetchers import http_simple
    md = "# README\n\n" + "知识内容段落。" * 40

    class RawResp:
        status_code = 200
        text = md

    class RawHttp:
        def get(self, *a, **k):
            return RawResp()

    text, title = http_simple.fetch_page(
        "https://raw.githubusercontent.com/u/r/main/README.md",
        SimpleNamespace(config=cfg, datalayer=None, http=RawHttp(), run_id="t"))
    assert text == md and title == "README"


def test_http_simple_skeleton_upgrades(cfg):
    """提取结果为按钮墙 → 骨架检测判失败 → 抛 FetchError 触发升级路由重抓。"""
    from knowatlas.fetchers import http_simple
    wall = "Skip to content Sign in Notifications Fork Star Pull requests " \
           "Issues Actions Projects Wiki " + "x" * 200  # 过 min_content_chars

    class SkelResp:
        status_code = 200
        text = f"<html><body><p>{wall}</p></body></html>"

    class SkelHttp:
        def get(self, *a, **k):
            return SkelResp()

    with pytest.raises(FetchError, match="骨架"):
        http_simple.fetch_page("https://github.com/u/r/blob/main/README/",
                               SimpleNamespace(config=cfg, datalayer=None,
                                               http=SkelHttp(), run_id="t"))
