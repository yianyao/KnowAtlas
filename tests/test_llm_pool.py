"""LLM 两级池（0.2.0 第二十一批，递进自第二十批 key 池）：

- 后端池 [[llm.backends]]：书写顺序即 failover 优先级；扁平 [llm] 单后端旧配置兼容；
- 后端内 key 池：失效(401/403)/余额不足(402)/限流(429) 换 key，key 尽或 5xx/网络故障切后端；
- 纪律延续：key 只进环境变量；错误只带指纹（sha256 前 8 位）不带明文。
"""

from __future__ import annotations

import pytest

from knowatlas.semantic.llm import (
    LlmClient,
    LlmError,
    _Backend,
    _key_fingerprint,
    _keys_from_envs,
)

DEEP = "https://deep.example.com/v1"
SF = "https://sf.example.com/v1"


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


def _backends(*specs: tuple[str, list[str]]) -> list[_Backend]:
    """specs: (base_url, [keys]) → backends（model/temperature 用固定值）。"""
    return [_Backend(base_url=url, api_keys=list(keys), model="m", temperature=0.2)
            for url, keys in specs]


def _client(*specs: tuple[str, list[str]]) -> LlmClient:
    return LlmClient(_backends(*specs))


def _install_fake(monkeypatch, routes: dict):
    """routes: (url, authorization) → FakeResp | callable；记录调用序。"""
    calls: list[tuple[str, str]] = []
    import httpx

    def fake_post(url, headers=None, json=None, timeout=None):
        auth = headers["Authorization"]
        calls.append((url, auth))
        r = routes.get((url, auth))
        if callable(r):
            r = r()
        return r if r is not None else FakeResp(500, text="unrouted")
    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


# ---------- 1. 配置解析 ----------

def test_keys_from_envs_all_forms(monkeypatch):
    """多变量名 + 值内多 key 堆叠；空值/重复跳过（保序去重）。"""
    monkeypatch.setenv("KA_A", "sk-a1, sk-a2")
    monkeypatch.setenv("KA_B", "sk-b1")
    assert _keys_from_envs("KA_A,KA_B") == ["sk-a1", "sk-a2", "sk-b1"]
    assert _keys_from_envs("KA_UNSET") == []
    monkeypatch.setenv("KA_C", " , sk-c ,sk-c,")
    assert _keys_from_envs("KA_C,,KA_UNSET") == ["sk-c"]


def test_from_config_flat_single_backend_compat(cfg, monkeypatch):
    """旧配置（扁平 [llm] 无 backends）→ 合成单后端，行为照旧。"""
    monkeypatch.setenv("KA_FLAT", "sk-flat")
    cfg._data["llm"] = {"enabled": True, "api_key_env": "KA_FLAT",
                        "base_url": DEEP, "model": "deepseek-chat"}
    c = LlmClient.from_config(cfg)
    assert c is not None and c.backend_count == 1
    assert c._backends[0].base_url == DEEP and c._backends[0].model == "deepseek-chat"
    assert c._backends[0].api_keys == ["sk-flat"]


def test_from_config_backends_in_order_with_overrides(cfg, monkeypatch):
    """[[llm.backends]] 数组表：顺序保留；temperature 可覆盖全局。"""
    monkeypatch.setenv("KA_D", "sk-d1,sk-d2")
    monkeypatch.setenv("KA_S", "sk-s1")
    cfg._data["llm"] = {
        "enabled": True, "temperature": 0.2,
        "backends": [
            {"base_url": DEEP, "api_key_env": "KA_D", "model": "deepseek-chat"},
            {"base_url": SF, "api_key_env": "KA_S", "model": "deepseek-ai/DeepSeek-V3",
             "temperature": 0.1},
        ],
    }
    c = LlmClient.from_config(cfg)
    assert c.backend_count == 2
    assert [b.base_url for b in c._backends] == [DEEP, SF]
    assert c._backends[0].api_keys == ["sk-d1", "sk-d2"]
    assert c._backends[0].temperature == 0.2           # 全局缺省
    assert c._backends[1].temperature == 0.1           # 后端覆盖
    assert c._backends[1].model == "deepseek-ai/DeepSeek-V3"


def test_from_config_backend_without_keys_skipped(cfg, monkeypatch):
    """后端 key 未设 → 跳过该后端（不带着空池进 failover 链）。"""
    monkeypatch.setenv("KA_D", "sk-d1")
    cfg._data["llm"] = {
        "enabled": True,
        "backends": [
            {"base_url": DEEP, "api_key_env": "KA_MISSING", "model": "m"},
            {"base_url": SF, "api_key_env": "KA_D", "model": "m"},
        ],
    }
    c = LlmClient.from_config(cfg)
    assert c.backend_count == 1 and c._backends[0].base_url == SF


def test_from_config_none_paths(cfg, monkeypatch):
    """enabled=false 或全部无 key → None（L3 静默跳过，不阻塞入库）。"""
    monkeypatch.delenv("KA_GONE", raising=False)
    cfg._data["llm"] = {"enabled": False, "api_key_env": "KA_GONE"}
    assert LlmClient.from_config(cfg) is None
    cfg._data["llm"] = {"enabled": True, "api_key_env": "KA_GONE"}
    assert LlmClient.from_config(cfg) is None
    cfg._data["llm"] = {"enabled": True, "backends": [{"base_url": DEEP,
                                                       "api_key_env": "KA_GONE",
                                                       "model": "m"}]}
    assert LlmClient.from_config(cfg) is None


# ---------- 2. 两级池切换行为 ----------

def test_backend_failover_on_401(monkeypatch):
    """后端1 的 key 401 → 切后端2 成功（url 与 key 都换）。"""
    calls = _install_fake(monkeypatch, {
        (f"{DEEP}/chat/completions", "Bearer sk-d1"): FakeResp(401, text="dead"),
        (f"{SF}/chat/completions", "Bearer sk-s1"): _ok("硅基顶上"),
    })
    assert _client((DEEP, ["sk-d1"]), (SF, ["sk-s1"])).chat("s", "u") == "硅基顶上"
    assert calls == [(f"{DEEP}/chat/completions", "Bearer sk-d1"),
                     (f"{SF}/chat/completions", "Bearer sk-s1")]


def test_key_then_backend_two_level_switch(monkeypatch):
    """两级全路径：后端1 key1 401 → key2 429 → 切后端2 成功。"""
    _install_fake(monkeypatch, {
        (f"{DEEP}/chat/completions", "Bearer sk-d1"): FakeResp(401, text="dead"),
        (f"{DEEP}/chat/completions", "Bearer sk-d2"): FakeResp(429, text="limited"),
        (f"{SF}/chat/completions", "Bearer sk-s1"): _ok("第三个可用"),
    })
    c = _client((DEEP, ["sk-d1", "sk-d2"]), (SF, ["sk-s1"]))
    assert c.chat("s", "u") == "第三个可用"


def test_5xx_skips_same_backend_keys_and_fails_over(monkeypatch):
    """5xx 是服务端故障：同后端其他 key 不必试，直接切下一个后端。"""
    calls = _install_fake(monkeypatch, {
        (f"{DEEP}/chat/completions", "Bearer sk-d1"): FakeResp(503, text="overloaded"),
        (f"{SF}/chat/completions", "Bearer sk-s1"): _ok("兜底成功"),
    })
    assert _client((DEEP, ["sk-d1", "sk-d2"]), (SF, ["sk-s1"])).chat("s", "u") == "兜底成功"
    # 同后端第二个 key（sk-d2）没有被打
    assert calls == [(f"{DEEP}/chat/completions", "Bearer sk-d1"),
                     (f"{SF}/chat/completions", "Bearer sk-s1")]


def test_network_error_fails_over(monkeypatch):
    """网络异常（连不上）→ 切下一个后端。"""
    import httpx

    def fake_post(url, headers=None, json=None, timeout=None):
        if url.startswith(DEEP):
            raise OSError("connection refused")
        return _ok("第二个后端通")
    monkeypatch.setattr(httpx, "post", fake_post)
    assert _client((DEEP, ["sk-d1"]), (SF, ["sk-s1"])).chat("s", "u") == "第二个后端通"


def test_malformed_response_fails_over(monkeypatch):
    """HTTP 200 但结构不可解析 → 切下一个后端（不同模型可能输出合规）。"""
    _install_fake(monkeypatch, {
        (f"{DEEP}/chat/completions", "Bearer sk-d1"): FakeResp(200, text="garbage"),
        (f"{SF}/chat/completions", "Bearer sk-s1"): _ok("合规输出"),
    })
    assert _client((DEEP, ["sk-d1"]), (SF, ["sk-s1"])).chat("s", "u") == "合规输出"


def test_4xx_other_raises_without_failover(monkeypatch):
    """400（请求/配置问题）→ 直接抛，不换供应商（换了也治不好，且掩盖问题）。"""
    calls = _install_fake(monkeypatch, {
        (f"{DEEP}/chat/completions", "Bearer sk-d1"): FakeResp(400, text="bad model"),
    })
    with pytest.raises(LlmError, match="HTTP 400"):
        _client((DEEP, ["sk-d1"]), (SF, ["sk-s1"])).chat("s", "u")
    assert len(calls) == 1


def test_all_backends_exhausted_aggregates_fingerprints_only(monkeypatch):
    """全部不可用：聚合错误含两个 base_url + 各 key 指纹，绝不含明文。"""
    _install_fake(monkeypatch, {
        (f"{DEEP}/chat/completions", "Bearer sk-d1"): FakeResp(401, text="dead"),
        (f"{SF}/chat/completions", "Bearer sk-s1"): FakeResp(429, text="limited"),
    })
    with pytest.raises(LlmError) as ei:
        _client((DEEP, ["sk-d1"]), (SF, ["sk-s1"])).chat("s", "u")
    msg = str(ei.value)
    assert "2 个后端均不可用" in msg
    assert DEEP in msg and SF in msg
    assert _key_fingerprint("sk-d1") in msg and _key_fingerprint("sk-s1") in msg
    assert "sk-d1" not in msg and "sk-s1" not in msg


def test_single_backend_single_key_error_message_unchanged(monkeypatch):
    """单后端单 key：错误消息与旧版逐字一致（无「N 个后端」聚合头）。"""
    _install_fake(monkeypatch, {
        (f"{DEEP}/chat/completions", "Bearer sk-only"): FakeResp(401, text='{"e":1}'),
    })
    with pytest.raises(LlmError) as ei:
        _client((DEEP, ["sk-only"])).chat("s", "u")
    msg = str(ei.value)
    assert "均不可用" not in msg
    assert msg == f"LLM HTTP 401：{{\"e\":1}}（key 指纹 {_key_fingerprint('sk-only')}）"


def test_success_returns_first_working_backend(monkeypatch):
    """第一个后端第一个 key 直接成功——不浪费后续请求。"""
    calls = _install_fake(monkeypatch, {
        (f"{DEEP}/chat/completions", "Bearer sk-d1"): _ok("首发命中"),
    })
    assert _client((DEEP, ["sk-d1"]), (SF, ["sk-s1"])).chat("s", "u") == "首发命中"
    assert len(calls) == 1


def test_key_fingerprints_flatten_all_backends():
    c = _client((DEEP, ["sk-d1", "sk-d2"]), (SF, ["sk-s1"]))
    assert c.key_fingerprints() == [
        _key_fingerprint("sk-d1"), _key_fingerprint("sk-d2"), _key_fingerprint("sk-s1")]
