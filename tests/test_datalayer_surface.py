"""护栏：DataLayer 公开方法名快照。

拆分 `datalayer/db.py` 时，方法名/可见性必须逐字不动（调用方遍布全库）。
改公开方法集合属于契约变更：先写工单，再更新这份快照。
"""
from __future__ import annotations

import functools
import inspect
import random
import tempfile
import tomllib
from pathlib import Path

from knowatlas.config import Config
from knowatlas.datalayer.db import DataLayer

ROOT = Path(__file__).resolve().parents[1]

EXPECTED = frozenset({
    "activation_times", "add_regress_case", "add_thread_item", "all_categories_dag",
    "all_category_paths", "all_entry_categories", "all_entry_locators", "all_point_vectors",
    "all_points_text", "all_vectors", "archive_missing", "attach_category", "attach_locator",
    "attach_parent", "category_names", "close", "cloud_data", "cloud_facet",
    "cloud_facet_points", "cloud_point_data", "count_entries", "count_point_vectors",
    "count_points", "count_regress_cases", "count_uncategorized", "count_vectors",
    "create_category", "create_thread", "delete_empty_categories", "delete_thread",
    "delete_vectors", "detach_category", "detach_parent", "entries_by_host",
    "entry_category_ids", "find_by_canonical", "find_by_content_hash", "find_by_locator",
    "find_canonical_group", "finish_run", "gc_orphan_contents", "get_category",
    "get_category_by_path", "get_category_paths", "get_content", "get_content_preview",
    "get_entries_by_ids", "get_entries_for_categories", "get_entry", "get_entry_categories",
    "get_entry_detail", "get_graph_data", "get_graph_overview", "get_graph_subtree",
    "get_point_hit", "get_point_meta", "get_stats", "get_task_log", "get_thread", "get_tree",
    "get_uncategorized", "get_vector", "hard_points_without_fact_check", "init_schema",
    "list_by_errata_flag", "list_by_freshness_flag", "list_by_link_status", "list_by_value_flag",
    "list_conv_messages", "list_entries", "list_points", "list_regress_cases",
    "list_task_log_actions", "list_threads", "log_task", "manual_category_paths",
    "merge_categories", "merge_entries", "merge_meta", "merge_meta_of_point", "move_category",
    "move_thread_item", "point_kind_counts", "point_source_entry_ids", "point_source_map",
    "point_sources_of", "points_fact_check_counts", "points_fingerprint", "points_of_entries",
    "points_of_kind", "points_without_kind", "points_wrong_queue",
    "points_wrong_without_reason_code", "prune_fragment_categories", "purge_entry_points",
    "purge_points", "purge_source", "put_content", "put_point", "put_point_vectors",
    "put_vectors", "radiate", "recent_runs", "remove_thread_item", "rename_category",
    "reorder_thread_items", "reverse_reach", "search_entries_direct", "search_fts",
    "search_graph", "search_points", "set_conv_thread", "set_point_aging", "set_status",
    "set_thread_digest", "start_run", "status_map", "subtree_category_ids",
    "sweep_expired_rejections", "task_overview", "threads_for_entry", "timeline_data", "transaction",
    "update_thread", "update_thread_item", "upsert_conv_messages", "upsert_entries",
    "vacuum_into",
})


def _make_dl() -> DataLayer:
    example = ROOT / "config" / "knowatlas.example.toml"
    data = tomllib.loads(example.read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix="ka-dl-"))
    cfg = Config(data, example)
    cfg.raw.setdefault("general", {}).update({
        "db_path": str(tmp / "k.db"),
        "content_root": str(tmp / "content"),
        "backup_dir": str(tmp / "backup"),
    })
    dl = DataLayer(cfg.db_path)
    dl.init_schema()
    return dl


def _public_methods() -> frozenset[str]:
    dl = _make_dl()
    try:
        return frozenset(
            n for n in dir(dl) if not n.startswith("_") and callable(getattr(dl, n))
        )
    finally:
        dl.close()


def test_datalayer_surface_is_unchanged() -> None:
    got = _public_methods()
    missing = EXPECTED - got
    extra = got - EXPECTED
    assert not missing and not extra, (
        "DataLayer 公开方法变了：\n"
        f"  少了：{sorted(missing)}\n"
        f"  多了：{sorted(extra)}"
    )


class _LockSpy:
    """记录 RLock 的获取次数与最大重入深度；其余属性透传真实锁。"""

    def __init__(self, inner) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "depth", 0)
        object.__setattr__(self, "acquires", 0)

    def __enter__(self):
        object.__setattr__(self, "depth", self.depth + 1)
        object.__setattr__(self, "acquires", self.acquires + 1)
        return self._inner.__enter__()

    def __exit__(self, *exc):
        object.__setattr__(self, "depth", self.depth - 1)
        return self._inner.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _zero_arg_methods(dl: DataLayer) -> set[str]:
    """类层面看签名（实例上的属性是 functools.partial(self._guard, fn)，签名已被 *args 吞掉）。"""
    out: set[str] = set()
    for name in dir(type(dl)):
        if name.startswith("_"):
            continue
        member = getattr(type(dl), name)
        if not callable(member):
            continue
        try:
            params = [
                p for p in inspect.signature(member).parameters.values()
                if p.name not in ("self", "cls")
            ]
        except (TypeError, ValueError):
            continue
        if all(p.default is not inspect.Parameter.empty or p.kind in (
            inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD
        ) for p in params):
            out.add(name)
    return out


def test_public_methods_are_lock_guarded() -> None:
    """`_guard` 必须按 MRO 扫到每个公开方法。

    拆分 `db.py` 成 mixin 后，若 `__init__` 只扫 `vars(type(self))`，父类方法收不到
    `_guard`，锁静默失效——并发测试不一定抓得住，所以这里静态断言「每个公开方法都是
    包装后的 partial」，再随机抽 3 个零参方法实测调用期间确实持锁（_guard 用 RLock）。
    """
    dl = _make_dl()
    try:
        wrapped = {n for n, v in vars(dl).items() if isinstance(v, functools.partial)}
        public = {
            n for n in dir(type(dl))
            if not n.startswith("_") and callable(getattr(type(dl), n))
        }
        unwrapped = public - {"transaction"} - wrapped
        assert not unwrapped, f"未加锁的公开方法（MRO 扫描漏了）：{sorted(unwrapped)}"

        candidates = sorted(_zero_arg_methods(dl) - {"close", "transaction"})
        assert len(candidates) >= 3
        picks = random.Random(20261028).sample(candidates, 3)
        spy = _LockSpy(dl._lock)
        dl._lock = spy
        try:
            for name in picks:
                before = spy.acquires
                getattr(dl, name)()
                assert spy.acquires > before, f"{name}() 调用期间未持有 self._lock"
                assert spy.depth == 0, f"{name}() 退出后锁未释放（depth={spy.depth}）"
        finally:
            dl._lock = spy._inner
    finally:
        dl.close()
