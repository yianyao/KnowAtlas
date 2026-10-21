"""本地向量（完整方案 §2 骨架 embed.py，0.2.0 第五十六批实现）。

定位：M4 可选级——sentence-transformers + bge-m3 类中文模型（requirements-optional，
装不装都不影响主链路）。供三处消费：
- 混合检索（/api/search mode=hybrid，FTS + 向量余弦 RRF 融合，结果可解释）；
- 关系图语义相似边（radiate sim 通道，db.py:844 挂账收口）；
- 暂存区聚类候选报告（ksync --cluster-report，§6.2 归纳四步之第 3 步——
  聚类后 LLM 为簇命名，生成候选路径，人工确认后生效，本工具只出报告不建类）。

降级纪律（与 LLM 同构）：[embedding] enabled=false / 依赖未装 / 加载失败 →
from_config 返回 None，调用方据此跳过（检索降级 fts、sim 通道不出现）。
向量入库时 L2 归一化（normalize_embeddings=True），库内余弦 = 点积
（纯标准库 array 解码，不引 numpy 硬依赖——约两千条 × 1024 维毫秒~百毫秒级）。
"""

from __future__ import annotations

import math
from typing import Any


class LocalEmbedder:
    """sentence-transformers 惰性加载封装（首次 encode 才 import + 载模型）。"""

    def __init__(self, model_path: str = ""):
        self._model_path = (model_path or "").strip() or "BAAI/bge-m3"
        self.name = f"st:{self._model_path}"
        self.dim: int | None = None
        self._model: Any = None

    def _ensure(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # optional 依赖

            self._model = SentenceTransformer(self._model_path)
            self.dim = int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码（已 L2 归一化）；空输入返回空列表。"""
        if not texts:
            return []
        self._ensure()
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [[float(x) for x in v] for v in vecs]


def from_config(cfg: Any) -> LocalEmbedder | None:
    """按 [embedding] 配置构建；未启用/依赖缺失/加载失败 → None（调用方降级）。"""
    if not cfg.get("embedding.enabled", False):
        return None
    provider = str(cfg.get("embedding.provider", "local") or "local")
    if provider != "local":
        return None  # 未知 provider 视同禁用（当前仅 local 实现）
    try:
        return LocalEmbedder(str(cfg.get("embedding.model_path", "") or ""))
    except Exception:  # sentence-transformers 未装等——禁用该级，不阻断启动
        return None


# ---- 库内向量数学（纯标准库；向量入库时已归一化，余弦 = 点积） ----

def blob_to_vec(blob: bytes) -> list[float]:
    """float32 little-endian BLOB → list[float]。"""
    import array

    a = array.array("f")
    a.frombytes(blob)
    return list(a)


def vec_to_blob(vec: list[float]) -> bytes:
    """list[float] → float32 BLOB（入库前调用方保证已归一化）。"""
    import array

    a = array.array("f", vec)
    return a.tobytes()


def normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（入库已归一化的场景等价点积；本函数做完整定义保证独立可用）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def top_similar(query: list[float], candidates: dict[str, list[float]],
                k: int = 30, threshold: float = 0.0) -> list[tuple[str, float]]:
    """query 对候选向量的 top-k 相似（余弦 ≥ threshold，降序）。"""
    scores = [(eid, cosine(query, vec)) for eid, vec in candidates.items()]
    scores = [(eid, s) for eid, s in scores if s >= threshold]
    scores.sort(key=lambda x: -x[1])
    return scores[:k]
