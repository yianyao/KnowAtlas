"""结构化日志（完整方案 §10.2）：JSON 行，禁止打印凭证与正文内容。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_CONTEXT_FIELDS = ("component", "run_id", "entry_id", "source_type", "url")


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "msg": record.getMessage(),
        }
        run_id = getattr(record, "run_id", "")
        if run_id:
            payload["run_id"] = run_id
        for f in _CONTEXT_FIELDS:
            v = getattr(record, f, None)
            if v is not None and f not in ("component", "run_id"):
                payload[f] = v
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("knowatlas")
    if logger.handlers:  # 幂等：重复调用不叠加 handler
        return logger
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLineFormatter())
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    return logger
