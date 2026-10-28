"""向量后端（完整方案 §2 骨架 embed.py，0.2.0 第五十六批实现）。

两个 provider（同一契约：encode(list[str]) → 已 L2 归一化向量）：
- local：sentence-transformers + bge-m3 类中文模型（requirements-optional，
  装不装都不影响主链路）；
- openai：OpenAI 兼容 `/embeddings` 远端接口（bge-m3 / Qwen3-Embedding 等），
  不装 torch、不下模型，按量计费（变更工单 2026-10-25-远程嵌入提供方）。

供三处消费：
- 混合检索（/api/search mode=hybrid，FTS + 向量余弦 RRF 融合，结果可解释）；
- 关系图语义相似边（radiate sim 通道，db.py:844 挂账收口）；
- 暂存区聚类候选报告（ksync --cluster-report，§6.2 归纳四步之第 3 步——
  聚类后 LLM 为簇命名，生成候选路径，人工确认后生效，本工具只出报告不建类）。

降级纪律（与 LLM 同构）：[embedding] enabled=false / 依赖未装 / key 未设 /
加载失败 → from_config 返回 None，调用方据此跳过（检索降级 fts、sim 通道不出现）。
向量入库时 L2 归一化（normalize_embeddings=True），库内余弦 = 点积
（纯标准库 array 解码，不引 numpy 硬依赖——约两千条 × 1024 维毫秒~百毫秒级）。
库内向量数学有 numpy 快路径（`top_similar` / `top_similar_blobs`，惰性导入、
缺 numpy 或形状不齐回落纯 Python；2026-10-28 工单「检索热路径提速」）。
"""

from __future__ import annotations

import math
import os
import threading
import time
from typing import Any

# 失败闸（2026-10-28 工单「检索降级与嵌入失败处理」）：远端后端刚失败过就冷却一段时间，
# 冷却期内 encode 直接抛（不发 HTTP）。为什么必须：402/401 这类永久错误每次搜索都会
# 重试 3 次 + 退避 ≈ 11 s，而搜索是高频交互路径；充值后冷却到期自动恢复，不用重启 serve。
_FAIL_GATE: dict[tuple[str, str], tuple[float, str]] = {}
_FAIL_GATE_TTL = 60.0

# 本地编码的单条 token 上限（2026-10-28 R28 实测，i5-1240P/CPU/16 线程，4000 字符文本）：
# 512→4.0s、1024→8.3s、2048→19.3s、8192→29.8s。bge-m3 支持 8192，但整篇 4000 字符
# 编码 30 s/条，76 条条目就要 38 分钟；1024 token（≈700 中文字）留住标题+摘要级语义，
# 代价 8 s/条。点文本（一两百字）远低于该上限，不受影响。
_LOCAL_MAX_TOKENS = 1024


class EmbedRejected(RuntimeError):
    """4xx（除 429）——请求本身不可能成功（余额/鉴权/模型名），不重试、直接进冷却闸。"""


def reset_failure_gate() -> None:
    """清空失败闸（测试用；运维也可在进程内调用以立即重试）。"""
    _FAIL_GATE.clear()


def _gate_open(key: tuple[str, str]) -> str | None:
    """冷却中返回失败原因，否则 None（到期即自动放行）。"""
    hit = _FAIL_GATE.get(key)
    if hit is None:
        return None
    until, reason = hit
    if time.monotonic() >= until:
        _FAIL_GATE.pop(key, None)
        return None
    return reason


def _gate_close(key: tuple[str, str], reason: str) -> None:
    _FAIL_GATE[key] = (time.monotonic() + _FAIL_GATE_TTL, reason)


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
            # 长文截断到 _LOCAL_MAX_TOKENS：CPU 上 8192 的注意力开销是 1024 的 ~3.6 倍
            # （8.3 s → 29.8 s/条，4000 字符），收益却在标题/摘要之外基本衰减。
            self._model.max_seq_length = _LOCAL_MAX_TOKENS
            # ST 6.x 把 get_sentence_embedding_dimension 改名 get_embedding_dimension（旧名仍可用但告警）
            get_dim = (getattr(self._model, "get_embedding_dimension", None)
                       or self._model.get_sentence_embedding_dimension)
            self.dim = int(get_dim())

    def encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码（已 L2 归一化）；空输入返回空列表。"""
        if not texts:
            return []
        self._ensure()
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [[float(x) for x in v] for v in vecs]


class RemoteEmbedder:
    """OpenAI 兼容 `/embeddings` 后端（远端算，不装 torch、不下模型）。

    契约与 LocalEmbedder 一致：encode(list[str]) → 已 L2 归一化向量，顺序对齐输入；
    失败抛 RuntimeError（由调用方决定中止还是降级）。dim 未配置时首批发回后自动填，
    换模型会改变维度，因此切模型必须 `ksync --embed --embed-force` 重建。

    错误分类（2026-10-28）：4xx（除 429）是**永久**拒绝（余额不足/鉴权失败/模型名错），
    立即抛 `EmbedRejected` 并把 `(url, model)` 关进失败闸 60 s；5xx/超时/返回条数不符才重试，
    且**不开闸**（瞬时抖动下次请求应继续尝试）。
    """

    def __init__(self, base_url: str, model: str, api_key: str, *,
                 dim: int | None = None, batch_size: int = 32,
                 timeout: float = 30.0, retries: int = 3) -> None:
        self._url = base_url.rstrip("/") + "/embeddings"
        self._model = model
        self._key = api_key
        self.name = f"api:{model}"
        self.dim = int(dim) if dim else None
        self._batch = max(1, int(batch_size))
        self._timeout = float(timeout)
        self._retries = max(1, int(retries))

    def encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码（按 batch_size 切片；空输入返回空列表）。"""
        if not texts:
            return []
        gate = _gate_open(self._gate_key)
        if gate is not None:
            raise EmbedRejected(
                f"embedding 后端冷却中（{self._url}，{_FAIL_GATE_TTL:.0f}s 内不再尝试）：{gate}")
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            out.extend(self._encode_batch(texts[start:start + self._batch]))
        return out

    @property
    def _gate_key(self) -> tuple[str, str]:
        return (self._url, self._model)

    @staticmethod
    def _is_permanent(status: int) -> bool:
        """4xx 且非 429（限流可重试）→ 永久拒绝。"""
        return 400 <= status < 500 and status != 429

    def _encode_batch(self, batch: list[str]) -> list[list[float]]:
        import httpx

        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                resp = httpx.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._key}"},
                    json={"model": self._model, "input": batch},
                    timeout=self._timeout,
                )
                if resp.status_code >= 400:
                    detail = f"HTTP {resp.status_code}：{resp.text[:200]}"
                    if self._is_permanent(resp.status_code):
                        _gate_close(self._gate_key, detail)
                        raise EmbedRejected(
                            f"embedding 请求被拒绝（{self._url}）：{detail}")
                    raise RuntimeError(detail)
                data = resp.json().get("data") or []
                vecs = [normalize([float(x) for x in (d.get("embedding") or [])])
                        for d in data]
                if len(vecs) != len(batch):
                    raise RuntimeError(f"返回条数不符：{len(vecs)} != {len(batch)}")
                if self.dim is None and vecs:
                    self.dim = len(vecs[0])
                return vecs
            except EmbedRejected:
                raise
            except Exception as exc:  # noqa: BLE001 —— 网络/格式错误统一重试
                last = exc
                time.sleep(1.5 * (attempt + 1))
        # 只为「永久性拒绝」开闸：瞬时故障（5xx/超时/条数不符）下次请求应当继续尝试，
        # 否则一次抖动就把语义通道关掉一分钟，比 4.5 s 退避更糟。
        raise RuntimeError(f"embedding 请求失败（{self._url}）：{last}")


# 本地模型进程内单例（2026-10-28 切本地 bge-m3 时补）：from_config 在
# web/routers/discovery.py 是**每次请求**调用一次，而 sentence-transformers
# 载入 2.2 GB 权重要数秒、常驻内存 3 GB 上下——不缓存等于每次搜索都重载模型。
# 键 = model_path（空串 = 默认 BAAI/bge-m3），值 = 惰性加载的封装实例。
_LOCAL_CACHE: dict[str, "LocalEmbedder"] = {}
_LOCAL_LOCK = threading.Lock()


def reset_local_cache() -> None:
    """清空本地模型缓存（测试用；换模型路径/释放显存时可调）。"""
    with _LOCAL_LOCK:
        _LOCAL_CACHE.clear()


def _local_embedder(model_path: str) -> "LocalEmbedder":
    """取（必要时创建）进程内共享的 LocalEmbedder；同路径并发首调只建一个。"""
    key = (model_path or "").strip()
    emb = _LOCAL_CACHE.get(key)
    if emb is None:
        with _LOCAL_LOCK:
            emb = _LOCAL_CACHE.get(key)
            if emb is None:
                emb = LocalEmbedder(key)
                _LOCAL_CACHE[key] = emb
    return emb


def from_config(cfg: Any) -> "LocalEmbedder | RemoteEmbedder | None":
    """按 [embedding] 配置构建；未启用/依赖缺失/key 未设/加载失败 → None（调用方降级）。"""
    if not cfg.get("embedding.enabled", False):
        return None
    provider = str(cfg.get("embedding.provider", "local") or "local").strip().lower()
    if provider in ("openai", "remote", "siliconflow"):
        base = str(cfg.get("embedding.base_url", "") or "").strip()
        model = str(cfg.get("embedding.model", "") or "").strip()
        env_name = (str(cfg.get("embedding.api_key_env", "") or "").strip()
                    or "KNOWATLAS_LLM_API_KEY")
        api_key = os.environ.get(env_name, "").strip()
        if not (base and model and api_key):
            return None  # 配置不全视同禁用（检索降级 fts，不报错）
        return RemoteEmbedder(
            base, model, api_key,
            dim=int(cfg.get("embedding.dim", 0) or 0) or None,
            batch_size=int(cfg.get("embedding.batch_size", 32) or 32),
            timeout=float(cfg.get("embedding.timeout_seconds", 30) or 30),
        )
    if provider != "local":
        return None  # 未知 provider 视同禁用（仅 local / openai 两实现）
    try:
        # 同一路径复用同一实例：模型只载一次（见 _local_embedder 注释）
        return _local_embedder(str(cfg.get("embedding.model_path", "") or ""))
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


def _rank_hits(ids: list[str], scores: Any, k: int,
               threshold: float) -> list[tuple[str, float]]:
    """统一收口：阈值过滤 → 降序 → top-k（numpy 与纯 Python 两条路径共用）。

    纯 Python 路径原实现先过滤后排序（`scores.sort(key=lambda x: -x[1])`），
    这里保持同一顺序语义（稳定排序 + 候选插入序），两条路径结果同序。
    """
    pairs = [(i, float(s)) for i, s in zip(ids, scores) if s >= threshold]
    pairs.sort(key=lambda x: -x[1])
    return pairs[:k]


def _scores_python(query: list[float],
                   tokens: list[list[float]]) -> list[float]:
    return [cosine(query, v) for v in tokens]


def _scores_numpy(query: list[float], matrix: Any, np: Any) -> Any | None:
    """矩阵批量余弦（完整定义：逐行归一化，不假设调用方已归一化）。

    浮点精度用 float32（与库内 BLOB 同精度；bge-m3 余弦在 1e-7 级差异内）。
    返回 None = 该批数据不可向量化（query 空 / 全零模长），调用方回落纯 Python。
    """
    q = np.asarray(query, dtype=np.float32)
    qn = float(np.linalg.norm(q))
    if qn == 0.0:
        return None
    denom = np.linalg.norm(matrix, axis=1) * qn
    denom[denom == 0.0] = 1.0          # 零模长候选 → 点积为 0 → 分数 0（与 cosine 同）
    return (matrix @ q) / denom


def _top_similar_rows(query: list[float], ids: list[str], tokens: Any,
                      k: int, threshold: float,
                      fallback: Any = None) -> list[tuple[str, float]]:
    """list[float] 候选的 numpy 快路径；numpy 缺失或形状不齐 → 回落纯 Python。

    真库实测（2026-10-28，5,607 点 × 1,024 维）：纯 Python 510 ms →
    list 成矩阵 104 ms（`top_similar_blobs` 直吃 BLOB 再降到 7 ms）。
    为什么不假设「已归一化」：`top_similar` 的契约是完整余弦（
    `tests/test_embed.py::test_top_similar_threshold_and_order` 用未归一化向量钉住），
    逐行归一化只多几毫秒，语义零偏移。
    """
    try:
        import numpy as np  # noqa: PLC0415 惰性导入：缺 numpy 时回落纯 Python
    except ImportError:
        np = None
    if np is not None:
        try:
            matrix = np.asarray(tokens, dtype=np.float32)
            if matrix.ndim == 1:          # 单条候选 → asarray 退化成一维
                matrix = matrix.reshape(1, -1)
            scores = _scores_numpy(query, matrix, np)
        except (ValueError, TypeError):
            scores = None                 # 维度不齐等 → 回落
        if scores is not None:
            return _rank_hits(ids, scores, k, threshold)
    if fallback is not None:
        return fallback()
    return _rank_hits(ids, _scores_python(query, tokens), k, threshold)


def top_similar(query: list[float], candidates: dict[str, list[float]],
                k: int = 30, threshold: float = 0.0) -> list[tuple[str, float]]:
    """query 对候选向量的 top-k 相似（余弦 ≥ threshold，降序）。

    签名与语义不变；内部有 numpy 快路径（惰性导入 + 形状不齐回落纯 Python）。
    """
    if not candidates:
        return []
    ids = list(candidates)
    tokens = [candidates[i] for i in ids]
    return _top_similar_rows(query, ids, tokens, k, threshold)


def top_similar_blobs(query: list[float], candidates: dict[str, bytes],
                      k: int = 30, threshold: float = 0.0
                      ) -> list[tuple[str, float]]:
    """`top_similar` 的 BLOB 直连版：候选为 float32 小端 BLOB（库内存储形态）。

    检索热路径刚用 `all_point_vectors()` / `all_vectors()` 拿到 BLOB 就要打分，
    这里 `np.frombuffer(b"".join(...))` 一次成矩阵——省掉 `blob_to_vec` 逐条构造
    Python float（真库 5,607 × 1,024 实测 89 ms）与逐条余弦（510 ms），
    合计 7 ms。入库纪律保证 BLOB 是 L2 归一化后的向量（`embed_index` 均经
    `normalize()` 再 `vec_to_blob()`），但仍按完整余弦算（行范数归一化），
    不把「已归一化」当硬前提。

    无 numpy / 行长不一致 / 非本机字节序可解析 → 回落 `blob_to_vec` + `top_similar`。
    """
    if not candidates:
        return []
    ids = list(candidates)
    dim = len(query)

    def _fallback() -> list[tuple[str, float]]:
        return top_similar(query, {i: blob_to_vec(candidates[i]) for i in ids},
                           k, threshold)

    if dim == 0:
        return _fallback()        # 空 query：与 list 版同口径（cosine 全 0）
    try:
        import numpy as np  # noqa: PLC0415 惰性导入：缺 numpy 时回落
    except ImportError:
        return _fallback()
    width = dim * 4
    if any(len(candidates[i]) != width for i in ids):
        return _fallback()
    try:
        matrix = np.frombuffer(b"".join(candidates[i] for i in ids),
                               dtype=np.float32).reshape(len(ids), dim)
    except (ValueError, TypeError):
        return _fallback()
    scores = _scores_numpy(query, matrix, np)
    if scores is None:
        return []
    return _rank_hits(ids, scores, k, threshold)
