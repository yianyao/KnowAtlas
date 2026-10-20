"""LLM 客户端（完整方案 §6 [llm] 节）：DeepSeek 兼容 OpenAI Chat API。

纪律：
- key 只从 api_key_env 指向的环境变量读取，永不入配置/日志；
- enabled=false 或 key 未设 → from_config 返回 None（L3 静默跳过，行为与 M0.5 一致）；
- 失败（网络/超时/解析）由调用方捕获降级，绝不因 LLM 故障阻塞入库。

两级池（0.2.0 第二十一批，递进自第二十批 key 池——用户追问「多个 base_url 也没用啊」）：
- config 用 [[llm.backends]] 数组表声明多个后端；每个后端 = base_url + key 池 + model，
  书写顺序即 failover 优先级；不写 backends 时由扁平 [llm] 字段合成单后端（旧配置照常工作）。
- chat() 两级切换：后端内先换 key（key 失效/限流/余额不足），key 池尽或服务端故障
  （5xx）再切下一个后端；4xx 其他错误直接抛（是请求/配置问题，不是供应商问题）；
- 错误消息只带 key 指纹（sha256 前 8 位），绝不回传明文 key；
- 单后端单 key 配置的错误消息与旧版逐字一致（向后兼容）。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

# 换 key 重试的 HTTP 状态：key 本身的问题/额度问题（网络类错误除外）
_RETRYABLE_STATUS = frozenset({401, 403, 402, 429})


class LlmError(Exception):
    """LLM 调用失败（网络、HTTP 非 2xx、响应结构异常）。"""


class _LlmHttpError(Exception):
    """HTTP 非 2xx 的内部载体（带 status_code 供判定切换策略）。"""

    def __init__(self, status_code: int, text: str) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.text = text


def _key_fingerprint(key: str) -> str:
    """key 指纹（sha256 前 8 位）——错误信息/日志里只出现指纹，不出现明文。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8] if key else ""


def _keys_from_envs(api_key_env: str) -> list[str]:
    """api_key_env 逗号分隔多个变量名；每个变量值再逗号分隔多个 key（两种堆叠，保序去重）。"""
    keys: list[str] = []
    for name in (s.strip() for s in api_key_env.split(",")):
        if not name:
            continue
        for key in os.environ.get(name, "").split(","):
            key = key.strip()
            if key and key not in keys:
                keys.append(key)
    return keys


@dataclass
class _Backend:
    """一个 LLM 后端：base_url + key 池 + model（temperature 可覆盖全局）。"""

    base_url: str
    api_keys: list[str] = field(default_factory=list)
    model: str = ""
    temperature: float = 0.2

    @property
    def key_fingerprints(self) -> list[str]:
        return [_key_fingerprint(k) for k in self.api_keys]


class LlmClient:
    """最小 Chat 客户端：只做 chat.completions，供语义任务复用。

    backends 为后端池（顺序即优先级）；后端内 key 失效/限流/余额不足自动换 key，
    key 池尽或 5xx/网络故障切下一个后端。
    """

    def __init__(self, backends: list[_Backend], timeout: float = 30.0) -> None:
        if not backends:
            raise ValueError("LlmClient 至少需要一个 backend")
        if not any(b.api_keys for b in backends):
            raise ValueError("LlmClient 至少需要一个 api key")
        self._backends = list(backends)
        self._timeout = timeout

    # ---------- 配置构建 ----------

    @classmethod
    def from_config(cls, cfg: Any) -> "LlmClient | None":
        """按配置构建；enabled=false 或无可用 key → None（调用方据此跳过 L3）。

        优先读 [[llm.backends]] 数组表（多后端 failover）；缺失时由扁平
        llm.base_url / llm.api_key_env / llm.model 合成单后端（旧配置兼容）。
        """
        if not cfg.get("llm.enabled", False):
            return None
        temperature = float(cfg.get("llm.temperature", 0.2))
        backends: list[_Backend] = []
        raw_backends = cfg.get("llm.backends")
        if isinstance(raw_backends, list) and raw_backends:
            for rb in raw_backends:
                if not isinstance(rb, dict):
                    continue
                api_keys = _keys_from_envs(str(rb.get("api_key_env", "")))
                if not api_keys:
                    continue  # 该后端 key 未设——跳过而不是带着空池进 failover
                backends.append(_Backend(
                    base_url=str(rb.get("base_url", "https://api.deepseek.com/v1")).rstrip("/"),
                    api_keys=api_keys,
                    model=str(rb.get("model", "deepseek-chat")),
                    temperature=float(rb.get("temperature", temperature)),
                ))
        else:
            api_keys = _keys_from_envs(str(cfg.get("llm.api_key_env", "KNOWATLAS_LLM_API_KEY")))
            if api_keys:
                backends.append(_Backend(
                    base_url=str(cfg.get("llm.base_url", "https://api.deepseek.com/v1")).rstrip("/"),
                    api_keys=api_keys,
                    model=str(cfg.get("llm.model", "deepseek-chat")),
                    temperature=temperature,
                ))
        if not backends:
            return None
        return cls(backends)

    # ---------- 运行 ----------

    @property
    def backend_count(self) -> int:
        """后端个数（供启动日志/测试断言，不含任何 key 信息）。"""
        return len(self._backends)

    def key_fingerprints(self) -> list[str]:
        """全部后端全部 key 的指纹列表（只指纹不明文——供服务端核对）。"""
        return [fp for b in self._backends for fp in b.key_fingerprints]

    def _chat_once(self, httpx: Any, be: _Backend, key: str,
                   system: str, user: str) -> str:
        try:
            resp = httpx.post(
                f"{be.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"model": be.model, "temperature": be.temperature,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]},
                timeout=self._timeout,
            )
        except Exception as exc:  # httpx 异常族统一转 LlmError（换后端时再捕获）
            raise LlmError(f"LLM 请求失败：{exc}") from exc
        if resp.status_code != 200:
            raise _LlmHttpError(resp.status_code, resp.text[:200])
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LlmError(f"LLM 响应结构异常：{resp.text[:200]}") from exc

    def chat(self, system: str, user: str) -> str:
        """单轮 chat；返回首个 choice 的 content。失败抛 LlmError。

        两级切换：后端内先换 key（key 失效/限流/余额不足），key 池尽或 5xx/网络故障
        切下一个后端；4xx 其他错误直接抛（请求/配置问题，换供应商也治不好）。
        全部不可用时抛聚合错误（含各后端 base_url 与 key 指纹，不含明文）。
        """
        import httpx

        n_be = len(self._backends)
        failures: list[tuple[str, str]] = []  # (base_url, detail)
        for be in self._backends:
            n_k = len(be.api_keys)
            for key in be.api_keys:
                try:
                    return self._chat_once(httpx, be, key, system, user)
                except _LlmHttpError as exc:
                    detail = (f"LLM HTTP {exc.status_code}：{exc.text}"
                              f"（key 指纹 {_key_fingerprint(key)}）")
                    failures.append((be.base_url, detail))
                    if exc.status_code in _RETRYABLE_STATUS:
                        continue  # key 类问题：先试同后端下一个 key
                    if exc.status_code >= 500:
                        break     # 服务端故障：同后端其他 key 无益，直接切后端
                    raise LlmError(detail) from exc  # 4xx 其他：不该切，直接抛
                except LlmError as exc:  # 网络异常 / 响应结构异常
                    failures.append((be.base_url, str(exc)))
                    break  # 这个后端连不上或输出不可解析，下一个
            # 内层自然尽或 break → 下一个后端
        if n_be == 1 and len(self._backends[0].api_keys) == 1:
            raise LlmError(failures[-1][1])  # 单后端单 key：与旧版错误消息逐字一致
        raise LlmError(
            f"LLM {n_be} 个后端均不可用：\n  "
            + "\n  ".join(f"{url} — {detail}" for url, detail in failures))


def extract_json_array(text: str) -> list[dict[str, Any]]:
    """从 LLM 输出中容错提取 JSON 数组（容忍 markdown 代码块与前后杂文本）。"""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise LlmError(f"LLM 输出中无 JSON 数组：{text[:200]}")
    try:
        arr = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise LlmError(f"JSON 解析失败：{text[:200]}") from exc
    if not isinstance(arr, list):
        raise LlmError("JSON 顶层不是数组")
    return [x for x in arr if isinstance(x, dict)]
