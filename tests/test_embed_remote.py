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
    def __init__(self, vecs):
        self.status_code = 200
        self._vecs = vecs

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