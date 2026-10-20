"""LLM key 池（0.2.0 第二十批）：多 api key 顺序尝试、失效/限流自动切换。

纪律延续：key 只进环境变量；错误信息只带指纹（sha256 前 8 位）不带明文。
"""

from __future__ import annotations

import pytest

from knowatlas.semantic.llm import LlmClient, LlmError, _key_fingerprint, _parse_keys


class FakeResp:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def _ok(content: str = "ok") -> FakeResp:
    return FakeResp(200, {"choices": [{"message": {"content": content}}]})


def _client(keys: list[str]) -> LlmClient:
    return LlmClient(base_url="https://api.siliconflow.cn/v1", api_keys=keys,
                     model="deepseek-ai/DeepSeek-V3")


# ---------- 1. 配置解析（_parse_keys） ----------

def test_parse_keys_single_variable_single_key(cfg, monkeypatch):
    """旧行为：单变量名单 key → 单元素池（向后兼容）。"""
    monkeypatch.setenv("KA_TEST_KEY", "sk-aaa")
    cfg._data.setdefault("llm", {})["api_key_env"] = "KA_TEST_KEY"
    assert _parse_keys(cfg) == ["sk-aaa"]


def test_parse_keys_comma_in_value(cfg, monkeypatch):
    """单变量值内逗号分隔多 key（用户最省事的配法）。"""
    monkeypatch.setenv("KA_TEST_KEY", "sk-aaa, sk-bbb ,sk-ccc")
    cfg._data.setdefault("llm", {})["api_key_env"] = "KA_TEST_KEY"
    assert _parse_keys(cfg) == ["sk-aaa", "sk-bbb", "sk-ccc"]


def test_parse_keys_multiple_variable_names(cfg, monkeypatch):
    """api_key_env 逗号分隔多个变量名（两个供应商/两批额度分开存）。"""
    monkeypatch.setenv("KA_TEST_A", "sk-aaa")
    monkeypatch.setenv("KA_TEST_B", "sk-bbb,sk-ccc")
    cfg._data.setdefault("llm", {})["api_key_env"] = "KA_TEST_A,KA_TEST_B"
    assert _parse_keys(cfg) == ["sk-aaa", "sk-bbb", "sk-ccc"]


def test_parse_keys_skips_empty_and_dedupes(cfg, monkeypatch):
    """空变量名/空值/纯逗号跳过；重复 key 去重（保序）。"""
    monkeypatch.setenv("KA_TEST_EMPTY", " , ,sk-bbb,sk-bbb,")
    cfg._data.setdefault("llm", {})["api_key_env"] = "KA_TEST_EMPTY,,KA_TEST_UNSET"
    assert _parse_keys(cfg) == ["sk-bbb"]


def test_from_config_returns_none_without_keys(cfg, monkeypatch):
    """未设 key → None（L3 静默跳过，入库不阻塞——与 M0.5 行为一致）。"""
    monkeypatch.delenv("KA_TEST_UNSET", raising=False)
    cfg._data["llm"] = {"enabled": True, "api_key_env": "KA_TEST_UNSET"}
    assert LlmClient.from_config(cfg) is None
    cfg._data["llm"] = {"enabled": False, "api_key_env": "KA_TEST_ALSO_UNSET"}
    assert LlmClient.from_config(cfg) is None


# ---------- 2. key 池重试行为 ----------

def test_chat_switches_key_on_401(monkeypatch):
    """第一个 key 401（失效）→ 自动换第二个 key 成功。"""
    calls: list[str] = []
    import httpx

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(headers["Authorization"])
        if headers["Authorization"] == "Bearer sk-dead":
            return FakeResp(401, text='{"error":"invalid key"}')
        return _ok("来自第二个 key")
    monkeypatch.setattr(httpx, "post", fake_post)
    assert _client(["sk-dead", "sk-live"]).chat("s", "u") == "来自第二个 key"
    assert calls == ["Bearer sk-dead", "Bearer sk-live"]


def test_chat_switches_key_on_429(monkeypatch):
    """429（限流）同样换 key——这正是「用完一个换一个」的自动化。"""
    import httpx

    def fake_post(url, headers=None, json=None, timeout=None):
        if headers["Authorization"] == "Bearer sk-limited":
            return FakeResp(429, text="rate limited")
        return _ok()
    monkeypatch.setattr(httpx, "post", fake_post)
    assert _client(["sk-limited", "sk-live"]).chat("s", "u") == "ok"


def test_chat_does_not_switch_key_on_500(monkeypatch):
    """500 是服务端问题不是 key 问题——不换 key，直接抛（换也白换）。"""
    import httpx

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(headers["Authorization"])
        return FakeResp(500, text="boom")
    calls: list[str] = []
    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(LlmError, match="HTTP 500"):
        _client(["sk-a", "sk-b"]).chat("s", "u")
    assert calls == ["Bearer sk-a"]  # 没有第二次请求


def test_chat_network_error_does_not_switch_key(monkeypatch):
    """网络异常直接抛，不消耗下一个 key。"""
    import httpx

    def fake_post(url, headers=None, json=None, timeout=None):
        raise OSError("connection reset")
    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(LlmError, match="请求失败"):
        _client(["sk-a", "sk-b"]).chat("s", "u")


def test_chat_all_keys_exhausted_reports_fingerprints_only(monkeypatch):
    """全部 401：聚合错误带全部指纹，绝不回传 key 明文。"""
    import httpx

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResp(401, text="dead")
    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(LlmError) as ei:
        _client(["sk-aaa", "sk-bbb"]).chat("s", "u")
    msg = str(ei.value)
    assert "2 个 key 均不可用" in msg
    assert _key_fingerprint("sk-aaa") in msg and _key_fingerprint("sk-bbb") in msg
    assert "sk-aaa" not in msg and "sk-bbb" not in msg  # 明文绝不出现


def test_chat_single_key_behaves_like_before(monkeypatch):
    """单 key（旧配置）：成功直接返回；失败错误消息带指纹、无「均不可用」措辞。"""
    import httpx

    def ok(url, headers=None, json=None, timeout=None):
        return _ok("内容")
    monkeypatch.setattr(httpx, "post", ok)
    assert _client(["sk-only"]).chat("s", "u") == "内容"

    def boom(url, headers=None, json=None, timeout=None):
        return FakeResp(401, text="dead")
    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(LlmError) as ei:
        _client(["sk-only"]).chat("s", "u")
    assert "sk-only" not in str(ei.value)
    assert _key_fingerprint("sk-only") in str(ei.value)


def test_key_fingerprint_is_sha8_and_stable():
    fp = _key_fingerprint("sk-whatever")
    assert len(fp) == 8 and fp == _key_fingerprint("sk-whatever")
    assert _key_fingerprint("") == ""
