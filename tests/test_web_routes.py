"""护栏：REST 端点集合快照。

拆分 `web/api.py` 时，URL 与方法必须**逐字不动**。本测试就是这把尺子。
端点集合变更（新增/删除接口）是契约变更：先写工单，再更新这份快照。
"""
from __future__ import annotations

import tempfile
import tomllib
from pathlib import Path

import pytest

from knowatlas.config import Config
from knowatlas.datalayer.db import DataLayer
from knowatlas.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]

EXPECTED = frozenset({
    "GET /api/categories/{category_id}/entries", "GET /api/cloud", "GET /api/dead-links",
    "GET /api/entries/linkage", "GET /api/entries/points", "GET /api/entries/{entry_id}",
    "GET /api/entries/{entry_id}/emmx_tree", "GET /api/entries/{entry_id}/file",
    "GET /api/entries/{entry_id}/preview", "GET /api/entries/{entry_id}/summary",
    "GET /api/entries/{entry_id}/threads", "GET /api/errata", "GET /api/errata/points",
    "GET /api/freshness", "GET /api/graph", "GET /api/graph/overview", "GET /api/graph/radiate",
    "GET /api/graph/reverse", "GET /api/graph/search", "GET /api/graph/subtree",
    "GET /api/graph/topics", "GET /api/mcp/entry/{entry_id}", "GET /api/mcp/search",
    "GET /api/mcp/tree", "GET /api/not-knowledge", "GET /api/pending", "GET /api/rejected",
    "GET /api/search", "GET /api/session", "GET /api/sets/group", "GET /api/sources",
    "GET /api/stats", "GET /api/threads", "GET /api/threads-lookup",
    "GET /api/threads/{thread_id}", "GET /api/timeline", "GET /api/token-hint", "GET /api/tree",
    "GET /api/uncategorized", "POST /api/categories", "POST /api/categories/{category_id}/merge",
    "POST /api/categories/{category_id}/move", "POST /api/categories/{category_id}/rename",
    "POST /api/entries", "POST /api/entries/auto-name", "POST /api/entries/batch-recategorize",
    "POST /api/entries/bulk-status", "POST /api/entries/merge",
    "POST /api/entries/{entry_id}/confirm-category", "POST /api/entries/{entry_id}/errata",
    "POST /api/entries/{entry_id}/errata/dismiss", "POST /api/entries/{entry_id}/form",
    "POST /api/entries/{entry_id}/recategorize", "POST /api/entries/{entry_id}/reject",
    "POST /api/entries/{entry_id}/rename", "POST /api/entries/{entry_id}/restore",
    "POST /api/entries/{entry_id}/unflag", "POST /api/entries/{entry_id}/unflag-freshness",
    "POST /api/points/{point_id}/explain", "POST /api/points/{point_id}/fact-check/dismiss",
    "POST /api/recall", "POST /api/sources/emmx/rejudge", "POST /api/synthesize/commit",
    "POST /api/synthesize/preview", "POST /api/threads", "POST /api/threads/{thread_id}/delete",
    "POST /api/threads/{thread_id}/digest", "POST /api/threads/{thread_id}/items",
    "POST /api/threads/{thread_id}/items/{item_id}/move",
    "POST /api/threads/{thread_id}/items/{item_id}/remove",
    "POST /api/threads/{thread_id}/items/{item_id}/update",
    "POST /api/threads/{thread_id}/suggest", "POST /api/threads/{thread_id}/update",
})


@pytest.fixture()
def route_set() -> frozenset[str]:
    example = ROOT / "config" / "knowatlas.example.toml"
    data = tomllib.loads(example.read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix="ka-routes-"))
    cfg = Config(data, example)
    cfg.raw.setdefault("general", {}).update({
        "db_path": str(tmp / "k.db"),
        "content_root": str(tmp / "content"),
        "backup_dir": str(tmp / "backup"),
    })
    dl = DataLayer(cfg.db_path)
    dl.init_schema()
    try:
        app = create_app(cfg, dl, None, None, start_ingest=False)
        spec = app.openapi()["paths"]
        return frozenset(f"{m.upper()} {p}" for p, ops in spec.items() for m in ops)
    finally:
        dl.close()


def test_route_surface_is_unchanged(route_set: frozenset[str]) -> None:
    missing = EXPECTED - route_set
    extra = route_set - EXPECTED
    assert not missing and not extra, (
        "端点集合变了（这属于契约变更）：\n"
        f"  少了：{sorted(missing)}\n"
        f"  多了：{sorted(extra)}"
    )
