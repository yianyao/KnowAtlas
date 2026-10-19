"""kadd 端到端（完整方案 §12 步骤 5–7 的验收：本地 HTTP fixture，M1 Gate 判据的雏形）。"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from knowatlas.pipeline.kadd import ingest_url

FIXTURE_HTML = (
    "<html><head><title>SQLite 数据库入库实践</title></head><body>"
    "<article><h1>SQLite 数据库入库实践</h1>"
    + ("<p>数据库索引与查询优化要点，覆盖 WAL 模式与 FTS5 全文检索。" * 8)
    + "</article></body></html>"
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802  stdlib 命名
        body = FIXTURE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_kadd_full_chain(cfg, dl, registries, server):
    locators, semantics = registries
    url = f"{server}/article"
    summary = ingest_url(cfg, dl, locators, semantics, url, "run0000000000001")
    assert summary["status"] == "created"
    assert summary["fetched"] and summary["categorized"]

    entry = dl.get_entry(summary["entry_id"])
    assert entry.title == "SQLite 数据库入库实践"
    assert entry.content_hash and dl.get_content(entry.content_hash)
    cats = dl.get_entry_categories(entry.id)
    assert any(c["path"].endswith("数据库") for c in cats)

    logs = dl.get_task_log()
    assert any(x["action"] == "import" and x["target"] == entry.id for x in logs)

    # 幂等：同一 URL（canonical 命中）不重复建条目
    again = ingest_url(cfg, dl, locators, semantics, url, "run0000000000002")
    assert again["status"] == "duplicate"
    assert again["entry_id"] == summary["entry_id"]


def test_kadd_title_only_on_fetch_failure(cfg, dl, registries):
    locators, semantics = registries
    summary = ingest_url(cfg, dl, locators, semantics, "https://127.0.0.1:1/nope", "run0000000000003")
    assert summary["fetched"] is False
    entry = dl.get_entry(summary["entry_id"])
    assert entry.title  # 标题级条目仍在（进暂存区）
    assert dl.get_entry_categories(entry.id) == []  # 未归类 → 未分类暂存区
