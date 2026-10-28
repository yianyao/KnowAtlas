"""远程 embedding provider 单元测试（变更工单 2026-10-25-远程嵌入提供方）。

不联网：httpx.post / time.sleep 全部打桩；只验契约——
from_config 降级、批量切片、L2 归一化、维度回填、失败重试后抛错。
"""

from __future__ import annotations

import httpx
import pytest

from knowatlas.semantic import embed


class _Cfg:
    def __init__(self, d: dict):
        self._d = d

    def get(self, k, default=None):
        return self._d.get(k, default)


class _Resp:
    def __init__(self, vecs, status=200, text=""):
        self.status_code = status
        self._vecs = vecs
        self.text = text

    def json(self):
        return {"data": [{"embedding": v} for v in self._vecs]}


def _cfg(**kw):
    base = {
        "embedding.enabled": True,
        "embedding.provider": "openai",
        "embedding.base_url": "https://api.example.com/v1",
        "embedding.model": "BAAI/bge-m3",
        "embedding.api_key_env": "KA_TEST_KEY",
    }
    base.update(kw)
    return _Cfg(base)


def test_from_config_requires_key(monkeypatch):
    monkeypatch.delenv("KA_TEST_KEY", raising=False)
    assert embed.from_config(_cfg()) is None


def test_from_config_builds_remote(monkeypatch):
    monkeypatch.setenv("KA_TEST_KEY", "sk-x")
    emb = embed.from_config(_cfg(**{"embedding.dim": 1024,
                                    "embedding.batch_size": 8}))
    assert isinstance(emb, embed.RemoteEmbedder)
    assert emb.name == "api:BAAI/bge-m3"
    assert emb.dim == 1024


def test_disabled_or_unknown_provider_degrades():
    assert embed.from_config(_cfg(**{"embedding.enabled": False})) is None
    assert embed.from_config(_cfg(**{"embedding.provider": "nope"})) is None


def test_encode_batches_and_normalizes(monkeypatch):
    calls: list[list[str]] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(list(json["input"]))
        return _Resp([[3.0, 4.0, 0.0] for _ in json["input"]])

    monkeypatch.setattr(httpx, "post", fake_post)
    emb = embed.RemoteEmbedder("https://api.example.com/v1", "m", "k", batch_size=2)
    vecs = emb.encode(["a", "b", "c", "d", "e"])
    assert [len(c) for c in calls] == [2, 2, 1]
    assert len(vecs) == 5
    assert abs(vecs[0][0] - 0.6) < 1e-6
    assert abs(vecs[0][1] - 0.8) < 1e-6
    assert emb.dim == 3                      # 未配置 dim 时首批发回后自动填


def test_encode_empty_returns_empty(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("不该发请求"))
    emb = embed.RemoteEmbedder("https://api.example.com/v1", "m", "k")
    assert emb.encode([]) == []


def test_encode_retries_then_raises(monkeypatch):
    monkeypatch.setattr(embed.time, "sleep", lambda s: None)
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    emb = embed.RemoteEmbedder("https://x/v1", "m", "k", retries=3)
    with pytest.raises(RuntimeError, match="embedding 请求失败"):
        emb.encode(["a"])


def test_count_mismatch_is_rejected(monkeypatch):
    monkeypatch.setattr(embed.time, "sleep", lambda s: None)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp([[1.0, 0.0]]))
    emb = embed.RemoteEmbedder("https://x/v1", "m", "k", retries=1)
    with pytest.raises(RuntimeError, match="返回条数不符"):
        emb.encode(["a", "b"])


# ---- 失败分类与失败闸（2026-10-28 变更工单-检索降级与嵌入失败处理） ----

def test_4xx_is_permanent_no_retry_and_opens_gate(monkeypatch):
    """402（余额不足）是永久错误：只打一次 HTTP，随后进 60 s 冷却、不再发请求。"""
    calls: list[int] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _Resp([], status=402, text='{"code":30001,"message":"insufficient"}')

    monkeypatch.setattr(httpx, "post", fake_post)
    emb = embed.RemoteEmbedder("https://api.example.com/v1", "m", "k",
                               retries=3, timeout=5)
    with pytest.raises(embed.EmbedRejected, match="HTTP 402"):
        emb.encode(["a"])
    assert len(calls) == 1                     # 3 次重试被跳过

    # 冷却期内：第二个实例（同 url+model，模拟下一次搜索新建 embedder）直接拒绝，零 HTTP
    with pytest.raises(embed.EmbedRejected, match="冷却中"):
        embed.RemoteEmbedder("https://api.example.com/v1", "m", "k").encode(["b"])
    assert len(calls) == 1

    # 清闸后恢复尝试（充值即自愈，不依赖重启进程）
    embed.reset_failure_gate()
    with pytest.raises(embed.EmbedRejected, match="HTTP 402"):
        emb.encode(["c"])
    assert len(calls) == 2


def test_gate_expires_after_ttl(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp([], status=401, text="no auth"))
    emb = embed.RemoteEmbedder("https://api.example.com/v1", "m", "k", retries=1)
    with pytest.raises(embed.EmbedRejected):
        emb.encode(["a"])
    base = embed.time.monotonic()
    monkeypatch.setattr(embed.time, "monotonic", lambda: base + embed._FAIL_GATE_TTL + 1)
    # 到期后闸自动放行 → 重新发请求（仍 401，说明真的又打了一次）
    with pytest.raises(embed.EmbedRejected, match="HTTP 401"):
        emb.encode(["b"])


def test_429_is_retried_not_gated(monkeypatch):
    """限流是可重试错误：不开关闸，退避后重试到上限；换一次调用仍会真的再打。"""
    calls: list[int] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _Resp([], status=429, text="rate limited")

    monkeypatch.setattr(embed.time, "sleep", lambda s: None)
    monkeypatch.setattr(httpx, "post", fake_post)
    emb = embed.RemoteEmbedder("https://api.example.com/v1", "m", "k", retries=3)
    with pytest.raises(RuntimeError, match="embedding 请求失败"):
        emb.encode(["a"])
    assert len(calls) == 3                     # 429 仍重试
    with pytest.raises(RuntimeError, match="embedding 请求失败"):
        emb.encode(["b"])                      # 未开闸 → 再打 3 次（不是「冷却中」）
    assert len(calls) == 6