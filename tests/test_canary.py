"""schema canary（完整方案 §11.2）：对六类契约面计算稳定摘要，任一漂移即红。

改动任一项都必须先写变更工单，改完后更新 CANARY 常量（用 pytest -s 输出的 current 值）。
DDL 摘要源 = 全部迁移按序拼接（0.2.0 第三十二批：新表即契约面，002_threads 纳管）。
"""

from __future__ import annotations

import dataclasses

import pytest

from knowatlas.config import CONFIG_SCHEMA_KEYS
from knowatlas.datalayer import schema as kschema
from knowatlas.models import SCHEMES, SOURCE_TYPES, Entry
from knowatlas.registry.builtins import build_registries

CANARY: dict[str, str] = {
    "ddl": "979471412904",
    "source_types": "dfeff8409159",
    "schemes": "40123837bf71",
    "entry_fields": "1a9d42828612",
    "config_keys": "e672d0a323eb",
    "capabilities": "074a5d9a6582",
}


def _current() -> dict[str, str]:
    locators, semantics = build_registries(None)
    return {
        "ddl": kschema.digest(kschema.load_all_migrations()),
        "source_types": kschema.digest("\n".join(SOURCE_TYPES)),
        "schemes": kschema.digest("\n".join(SCHEMES)),
        "entry_fields": kschema.digest("\n".join(f.name for f in dataclasses.fields(Entry))),
        "config_keys": kschema.digest("\n".join(CONFIG_SCHEMA_KEYS)),
        "capabilities": kschema.digest("\n".join(sorted(
            f"{s.name}@{s.version}" for s in (*locators.specs(), *semantics.specs())
        ))),
    }


def test_canary_no_drift():
    current = _current()
    drift = {k: v for k, v in current.items() if CANARY.get(k) != v}
    assert not drift, (
        f"契约漂移：{drift}\n"
        "契约变更必须先写变更工单（CHANGELOG 追加），然后更新本文件 CANARY 常量并升版。"
    )


if __name__ == "__main__":  # 首录 / 重录辅助：python tests/test_canary.py
    for k, v in _current().items():
        print(f'    "{k}": "{v}",')
