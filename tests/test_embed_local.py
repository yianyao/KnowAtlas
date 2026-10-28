"""本地 embedding provider（sentence-transformers + bge-m3）单元测试。

不载模型、不联网：只验 from_config 的**进程内单例**契约——
  - 同一 model_path 反复 from_config 返回同一实例（每次搜索不重载 2.2 GB 权重）；
  - 不同 model_path 各自独立；
  - 空 model_path = 默认 BAAI/bge-m3，name 前缀 st:。
背景：web/routers/discovery.py 每次请求都调 from_config；不做缓存时本地后端
会在每个搜索请求上重载模型（数秒 + 3 GB 上下内存），见 R28 记录。
"""

from __future__ import annotations

from knowatlas.semantic import embed


class _Cfg:
    def __init__(self, d: dict):
        self._d = d

    def get(self, k, default=None):
        return self._d.get(k, default)


def _cfg(**kw):
    base = {"embedding.enabled": True, "embedding.provider": "local"}
    base.update(kw)
    return _Cfg(base)


def _clean():
    embed.reset_local_cache()


def test_local_provider_cached_per_model_path():
    _clean()
    try:
        a = embed.from_config(_cfg(**{"embedding.model_path": "data/models/bge-m3"}))
        b = embed.from_config(_cfg(**{"embedding.model_path": "data/models/bge-m3"}))
        c = embed.from_config(_cfg(**{"embedding.model_path": "data/models/other"}))
        assert isinstance(a, embed.LocalEmbedder)
        assert a is b                       # 同路径复用（关键：不重载模型）
        assert a is not c                   # 不同路径各自独立
        assert a.name == "st:data/models/bge-m3"
    finally:
        _clean()


def test_local_provider_default_model_path():
    _clean()
    try:
        emb = embed.from_config(_cfg())
        assert isinstance(emb, embed.LocalEmbedder)
        assert emb.name == "st:BAAI/bge-m3"
        assert emb.dim is None              # 惰性：未 encode 前不知道维度
    finally:
        _clean()


def test_local_cache_reset_builds_new_instance():
    _clean()
    try:
        a = embed.from_config(_cfg(**{"embedding.model_path": "m"}))
        embed.reset_local_cache()
        b = embed.from_config(_cfg(**{"embedding.model_path": "m"}))
        assert a is not b
    finally:
        _clean()