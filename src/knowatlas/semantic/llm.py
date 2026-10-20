"""LLM 客户端（完整方案 §6 [llm] 节）：DeepSeek 兼容 OpenAI Chat API。

纪律：
- key 只从 api_key_env 指向的环境变量读取，永不入配置/日志；
- enabled=false 或 key 未设 → from_config 返回 None（L3 静默跳过，行为与 M0.5 一致）；
- 失败（网络/超时/解析）由调用方捕获降级，绝不因 LLM 故障阻塞入库。

key 池（0.2.0 第二十批，用户诉求「多个 api key 用完一个换一个」）：
- api_key_env 支持逗号分隔的多个变量名，每个变量值也支持逗号分隔的多个 key
  （两种堆叠方式任选，顺序即书写顺序）；
- chat() 按池内顺序尝试：HTTP 401/403（key 失效/封禁）、402（余额不足）、
  429（限流）自动换下一个 key 重试；网络错误不换 key（换也没用，照旧抛出）；
- 错误消息只带 key 指纹（sha256 前 8 位），绝不回传 key 明文；
- 单 key 配置行为与旧版完全一致（向后兼容）。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

# 换 key 重试的 HTTP 状态：key 本身的问题/额度问题（网络类错误除外）
_RETRYABLE_STATUS = frozenset({401, 403, 402, 429})


class LlmError(Exception):
    """LLM 调用失败（网络、HTTP 非 2xx、响应结构异常）。"""


class _LlmHttpError(Exception):
    """HTTP 非 2xx 的内部载体（带 status_code 供 key 池判定是否换 key）。"""

    def __init__(self, status_code: int, text: str) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.text = text


def _key_fingerprint(key: str) -> str:
    """key 指纹（sha256 前 8 位）——错误信息/日志里只出现指纹，不出现明文。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8] if key else ""


def _parse_keys(cfg: Any) -> list[str]:
    """解析 key 池：[llm].api_key_env 逗号分隔多个变量名；每变量值再逗号分隔多个 key。

    去空白、去空值、保序去重。结果为空 = 未配置（调用方据此跳过 L3）。
    """
    env_names = [s.strip() for s in
                 str(cfg.get("llm.api_key_env", "KNOWATLAS_LLM_API_KEY")).split(",")]
    keys: list[str] = []
    for name in env_names:
        if not name:
            continue
        for key in os.environ.get(name, "").split(","):
            key = key.strip()
            if key and key not in keys:
                keys.append(key)
    return keys


class LlmClient:
    """最小 Chat 客户端：只做 chat.completions，供语义任务复用。

    api_keys 为 key 池（顺序即优先级）；池内 key 失效/限流/余额不足时自动换下一个。
    """

    def __init__(self, base_url: str, api_keys: list[str], model: str,
                 temperature: float = 0.2, timeout: float = 30.0) -> None:
        if not api_keys:
            raise ValueError("LlmClient 至少需要一个 api key")
        self._base_url = base_url.rstrip("/")
        self._api_keys = list(api_keys)
        self._model = model
        self._temperature = temperature
        self._timeout = timeout

    @classmethod
    def from_config(cls, cfg: Any) -> "LlmClient | None":
        """按配置构建；enabled=false 或 key 环境变量未设 → None（调用方据此跳过 L3）。"""
        if not cfg.get("llm.enabled", False):
            return None
        api_keys = _parse_keys(cfg)
        if not api_keys:
            return None
        return cls(
            base_url=str(cfg.get("llm.base_url", "https://api.deepseek.com/v1")),
            api_keys=api_keys,
            model=str(cfg.get("llm.model", "deepseek-chat")),
            temperature=float(cfg.get("llm.temperature", 0.2)),
        )

    @property
    def key_count(self) -> int:
        """池内 key 个数（供启动日志/测试断言，不含明文）。"""
        return len(self._api_keys)

    def key_fingerprints(self) -> list[str]:
        """池内 key 指纹列表（只指纹不明文——供服务端核对）。"""
        return [_key_fingerprint(k) for k in self._api_keys]

    def _chat_once(self, httpx: Any, key: str, system: str, user: str) -> str:
        try:
            resp = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"model": self._model, "temperature": self._temperature,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]},
                timeout=self._timeout,
            )
        except Exception as exc:  # httpx 异常族统一转 LlmError（网络问题不换 key）
            raise LlmError(f"LLM 请求失败：{exc}") from exc
        if resp.status_code != 200:
            raise _LlmHttpError(resp.status_code, resp.text[:200])
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LlmError(f"LLM 响应结构异常：{resp.text[:200]}") from exc

    def chat(self, system: str, user: str) -> str:
        """单轮 chat；返回首个 choice 的 content。失败抛 LlmError。

        key 池顺序尝试：401/403（key 失效）/402（余额不足）/429（限流）换下一个
        key 重试；全部不可用时抛出带全部指纹的聚合错误（不含明文）。
        """
        import httpx

        n = len(self._api_keys)
        for i, key in enumerate(self._api_keys):
            try:
                return self._chat_once(httpx, key, system, user)
            except _LlmHttpError as exc:
                detail = (f"LLM HTTP {exc.status_code}：{exc.text}"
                          f"（key 指纹 {_key_fingerprint(key)}）")
                if exc.status_code in _RETRYABLE_STATUS and i < n - 1:
                    continue  # key 失效/限流/余额不足 → 换下一个 key
                if n > 1:
                    raise LlmError(
                        f"LLM {n} 个 key 均不可用（指纹 "
                        f"{', '.join(self.key_fingerprints())}）；最后错误：{detail}"
                    ) from exc
                raise LlmError(detail) from exc
        raise LlmError(f"LLM 无可用 key（池大小 {n}）")  # 构造已拦截空池，理论不可达


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
