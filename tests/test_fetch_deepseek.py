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
