"""护栏：DataLayer 公开方法名快照。

拆分 `datalayer/db.py` 时，方法名/可见性必须逐字不动（调用方遍布全库）。
改公开方法集合属于契约变更：先写工单，再更新这份快照。
"""
from __future__ import annotations

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
    "sweep_expired_rejections", "threads_for_entry", "timeline_data", "transaction",
    "update_thread", "update_thread_item", "upsert_conv_messages", "upsert_entries",
    "vacuum_into",
})


def _public_methods() -> frozenset[str]:
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
