"""LLM 客户端（完整方案 §6 [llm] 节）：DeepSeek 兼容 OpenAI Chat API。

纪律：
- key 只从 api_key_env 指向的环境变量读取，永不入配置/日志；
- enabled=false 或 key 未设 → from_config 返回 None（L3 静默跳过，行为与 M0.5 一致）；
- 失败（网络/超时/解析）由调用方捕获降级，绝不因 LLM 故障阻塞入库。
"""

from __future__ import annotations

import json
import os
from typing import Any


class LlmError(Exception):
    """LLM 调用失败（网络、HTTP 非 2xx、响应结构异常）。"""


class LlmClient:
    """最小 Chat 客户端：只做 chat.completions，供语义任务复用。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.2, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._timeout = timeout

    @classmethod
    def from_config(cls, cfg: Any) -> "LlmClient | None":
        """按配置构建；enabled=false 或 key 环境变量未设 → None（调用方据此跳过 L3）。"""
        if not cfg.get("llm.enabled", False):
            return None
        key_env = str(cfg.get("llm.api_key_env", "KNOWATLAS_LLM_API_KEY"))
        api_key = os.environ.get(key_env, "")
        if not api_key:
            return None
        return cls(
            base_url=str(cfg.get("llm.base_url", "https://api.deepseek.com/v1")),
            api_key=api_key,
            model=str(cfg.get("llm.model", "deepseek-chat")),
            temperature=float(cfg.get("llm.temperature", 0.2)),
        )

    def chat(self, system: str, user: str) -> str:
        """单轮 chat；返回首个 choice 的 content。失败抛 LlmError。"""
        import httpx

        try:
            resp = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Content-Type": "application/json"},
                json={"model": self._model, "temperature": self._temperature,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]},
                timeout=self._timeout,
            )
        except Exception as exc:  # httpx 异常族统一转 LlmError
            raise LlmError(f"LLM 请求失败：{exc}") from exc
        if resp.status_code != 200:
            raise LlmError(f"LLM HTTP {resp.status_code}：{resp.text[:200]}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LlmError(f"LLM 响应结构异常：{resp.text[:200]}") from exc


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
