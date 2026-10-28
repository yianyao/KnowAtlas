"""任务视图（`GET /api/tasks` + `dl.task_overview`）护栏。

对应工单 `docs/design/变更工单-2026-10-28-任务视图API.md`。数据源是 `runs` 表。

为什么测试直接插 `runs` 行而不是调 `start_run`：`start_run`/`finish_run` 用 `_now()`
取当前时间，同一秒内的两行无法断言「取最新」；显式时间才能把并列与倒序都钉死。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from knowatlas.web.app import create_app


def _seed(dl, run_id: str, kind: str, started: str,
          finished: str | None = None, **stats) -> None:
    with dl.transaction() as conn:
        conn.execute(
            "INSERT INTO runs (id, kind, started_at, finished_at, stats)"
            " VALUES (?,?,?,?,?)",
            (run_id, kind, started, finished,
             json.dumps(stats, ensure_ascii=False, sort_keys=True)),
        )


def _counts(dl) -> tuple[int, int]:
    """只读口子：runs / task_log 的行数（走公开方法，不碰私有连接）。"""
    return len(dl.recent_runs(1000)), len(dl.get_task_log(1000))


def test_task_overview_picks_latest_per_kind(dl):
    """每类取最新一轮；试跑、未完成都要透出，且不影响其他类的统计。"""
    _seed(dl, "a1", "kauto", "2026-10-27T22:00:00+08:00", "2026-10-27T22:00:03+08:00",
          activated=1, errors=0, dry_run=False)
    _seed(dl, "a2", "kauto", "2026-10-27T23:00:00+08:00", "2026-10-27T23:00:05+08:00",
          activated=9, errors=2, dry_run=True)
    _seed(dl, "b1", "kaging", "2026-10-27T22:30:00+08:00", None, candidates=5)

    out = dl.task_overview()

    assert [k["kind"] for k in out["kinds"]] == ["kauto", "kaging"]   # 按 last_at 倒序
    kinds = {k["kind"]: k for k in out["kinds"]}

    assert kinds["kauto"]["runs"] == 2
    assert kinds["kauto"]["unfinished"] == 0
    last = kinds["kauto"]["last"]
    assert last["id"] == "a2"                    # 22:00 vs 23:00 → 取晚的
    assert last["dry_run"] is True
    assert last["duration_s"] == 5.0
    assert last["stats"]["activated"] == 9

    assert kinds["kaging"]["unfinished"] == 1
    assert kinds["kaging"]["last"]["unfinished"] is True
    assert kinds["kaging"]["last"]["duration_s"] is None   # finished_at 为空

    assert out["unfinished_total"] == 1
    assert [r["id"] for r in out["recent"]] == ["a2", "b1", "a1"]


def test_task_overview_recent_is_clamped(dl):
    for i in range(5):
        _seed(dl, f"r{i}", "kauto", f"2026-10-27T2{i}:00:00+08:00",
              f"2026-10-27T2{i}:00:01+08:00")
    assert len(dl.task_overview(recent=2)["recent"]) == 2
    assert len(dl.task_overview(recent=0)["recent"]) == 1     # 下界 1
    assert len(dl.task_overview(recent=500)["recent"]) == 5   # 上界 100，实际只有 5 行


def test_task_overview_tolerates_bad_timestamps(dl):
    """坏时间串不能让整个视图 500：时长给 None，其它字段照常。"""
    _seed(dl, "x1", "kauto", "not-a-time", "2026-10-27T22:00:00+08:00")
    row = dl.task_overview()["kinds"][0]["last"]
    assert row["duration_s"] is None
    assert row["started_at"] == "not-a-time"


def test_task_overview_empty_db(dl):
    out = dl.task_overview()
    assert out == {"kinds": [], "recent": [], "unfinished_total": 0}


@pytest.fixture
def client(cfg, dl, registries, monkeypatch):
    monkeypatch.setenv(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")), "test-token-123")
    locators, semantics = registries
    app = create_app(cfg, dl, locators, semantics)
    return TestClient(app, headers={"Host": "127.0.0.1:8420"})


def test_tasks_endpoint_shape_and_readonly(client, dl):
    """只读端点：不要令牌、不改库；响应形状与管理页卡片约定一致。"""
    _seed(dl, "a1", "kauto", "2026-10-27T22:00:00+08:00", "2026-10-27T22:00:04+08:00",
          activated=3, errors=0)
    before = _counts(dl)

    r = client.get("/api/tasks")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"kinds", "recent", "unfinished_total"}
    assert body["kinds"][0]["kind"] == "kauto"
    assert body["kinds"][0]["last"]["duration_s"] == 4.0
    assert set(body["recent"][0]) == {
        "id", "kind", "started_at", "finished_at", "duration_s",
        "unfinished", "dry_run", "stats",
    }
    assert _counts(dl) == before, "GET /api/tasks 不该写库"


def test_tasks_endpoint_recent_param(client, dl):
    for i in range(4):
        _seed(dl, f"r{i}", "kpoints", f"2026-10-27T2{i}:00:00+08:00",
              f"2026-10-27T2{i}:00:02+08:00")
    assert len(client.get("/api/tasks?recent=2").json()["recent"]) == 2
    assert client.get("/api/tasks?recent=abc").status_code == 422   # 非整数由 FastAPI 拦