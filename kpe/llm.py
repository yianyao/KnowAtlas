"""OpenAI 兼容 Chat 适配器（stdlib urllib，无第三方依赖）。"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class LLMError(RuntimeError):
    def __init__(self, status: object, body: str) -> None:
        super().__init__(f"LLM HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str
    temperature: float = 0.2
    timeout: float = 180.0
    thinking: str = "omit"          # on | off | omit
    max_tokens: int = 0             # 0 = 不传


class LLMClient:
    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self.url = cfg.base_url.rstrip("/") + "/chat/completions"

    def _body(self, system: str, user: str) -> dict:
        body: dict = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        if self.cfg.max_tokens:
            body["max_tokens"] = self.cfg.max_tokens
        if self.cfg.thinking in ("on", "off"):
            body["thinking"] = {"type": "enabled" if self.cfg.thinking == "on"
                                else "disabled"}
        return body

    def chat(self, system: str, user: str) -> tuple[str, dict]:
        """返回 (content, usage)；429/5xx/超时重试 3 次，其余直接抛。"""
        data = json.dumps(self._body(system, user), ensure_ascii=False).encode()
        headers = {"Authorization": f"Bearer {self.cfg.api_key}",
                   "Content-Type": "application/json"}
        last: Exception | None = None
        for attempt in range(1, 4):
            req = urllib.request.Request(self.url, data=data, headers=headers,
                                         method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                msg = payload["choices"][0]["message"]
                return (msg.get("content") or ""), (payload.get("usage") or {})
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                    last = LLMError(exc.code, body)
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(exc.code, body) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError("network", str(exc)) from exc
        raise LLMError("retry", str(last))


def key_from_env(name: str) -> str:
    key = os.environ.get(name, "").strip()
    if not key:
        raise SystemExit(f"环境变量 {name} 为空：请先设置 API key（不要写进配置文件）")
    return key