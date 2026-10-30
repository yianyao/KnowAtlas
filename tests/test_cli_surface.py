"""护栏：CLI 子命令与参数集合快照。

拆分 `cli.py` 时，13 个子命令、每个选项的短/长名与位置参数必须逐字不动。
新增/删除参数是用户可见接口变更：先写工单，再更新这份快照。
"""
from __future__ import annotations

from knowatlas.cli import build_parser

EXPECTED: dict[str, list[str]] = {
    "kadd": [
        "--help", "-h", "urls",
    ],
    "kaging": [
        "--dry-run", "--help", "--lifecycle", "--limit", "--points", "--sweep", "-h",
    ],
    "kauto": [
        "--activate-only", "--dry-run", "--help", "--limit", "--no-activate", "--no-aging", "-h",
    ],
    "kbackup": [
        "--help", "--keep", "--no-throttle", "--restore", "--snap", "--verify", "-h",
    ],
    "kcheck": [
        "--dry-run", "--gc-content", "--gc-days", "--help", "--limit", "--qps", "-h",
    ],
    "kerrata": [
        "--backfill-codes", "--dry-run", "--from-json", "--help", "--limit", "--points",
        "--scan", "-h",
    ],
    "kexport": [
        "--format", "--help", "--out", "-h",
    ],
    "kinit": [
        "--help", "-h",
    ],
    "kpeimport": [
        "--dry-run", "--entry", "--help", "--limit", "--match", "--no-backup", "--replace", "-h",
        "out_dir",
    ],
    "kpoints": [
        "--dry-run", "--entry", "--from-json", "--help", "--limit", "--purge-points",
        "--retry-blocked", "--triage", "-h",
    ],
    "ksync": [
        "--cluster-report", "--dedupe-scan", "--dry-run", "--embed", "--embed-force", "--entry",
        "--errata-scan", "--expand", "--expand-limit", "--fetch-limit", "--freshness-scan",
        "--full", "--help", "--incremental", "--limit", "--prune-missing", "--purge-reason",
        "--purge-source", "--reclassify", "--source", "--value-scan", "-h",
    ],
    "ktest": [
        "--dry-run", "--help", "--seed-from-log", "-h", "what",
    ],
    "serve": [
        "--help", "--host", "--port", "-h",
    ],
}


def _surface() -> dict[str, list[str]]:
    parser = build_parser()
    subs = {}
    for action in parser._subparsers._group_actions:  # noqa: SLF001
        subs.update(action.choices)
    out = {}
    for name, sub in sorted(subs.items()):
        flags: list[str] = []
        for a in sub._actions:  # noqa: SLF001
            flags.extend(a.option_strings or [a.dest])
        out[name] = sorted(flags)
    return out


def test_subcommand_count() -> None:
    assert len(EXPECTED) == 13


def test_cli_surface_is_unchanged() -> None:
    got = _surface()
    assert set(got) == set(EXPECTED), f"子命令变了：{sorted(set(got) ^ set(EXPECTED))}"
    for name in sorted(EXPECTED):
        assert got[name] == EXPECTED[name], (
            f"`{name}` 的参数变了：\n  少了：{sorted(set(EXPECTED[name]) - set(got[name]))}\n"
            f"  多了：{sorted(set(got[name]) - set(EXPECTED[name]))}"
        )
