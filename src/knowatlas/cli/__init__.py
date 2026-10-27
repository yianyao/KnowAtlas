"""CLI 子命令注册与参数解析（完整方案 §7；argparse，不引 click）。"""

# 拆分自 src/knowatlas/cli.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


# 对外入口保持 knowatlas.cli 不变（测试/脚本按 cli._cmd_* 取用，勿改）
from .parser import build_parser
from ._shared import EXIT_BUSINESS, _EXIT_OK, _EXIT_SKIP, _EXIT_USAGE, _apply_serve_overrides, _open, _warn_if_llm_unavailable
from .cmd_entry import _cmd_kadd, _cmd_kinit
from .cmd_sync import _cmd_ksync
from .cmd_ops import _cmd_kbackup, _cmd_kcheck, _cmd_kexport, _cmd_ktest, _cmd_serve
from .cmd_points import _cmd_kauto, _cmd_kpeimport, _cmd_kpoints, _cmd_kpoints_triage
from .cmd_quality import _cmd_kaging, _cmd_kerrata
import sys
from typing import Sequence
from ..errors import KnowAtlasError
from ._shared import EXIT_BUSINESS


_COMMANDS = {
    "kinit": _cmd_kinit,
    "kadd": _cmd_kadd,
    "ksync": _cmd_ksync,
    "serve": _cmd_serve,
    "kexport": _cmd_kexport,
    "kbackup": _cmd_kbackup,
    "ktest": _cmd_ktest,
    "kcheck": _cmd_kcheck,
    "kpoints": _cmd_kpoints,
    "kaging": _cmd_kaging,
    "kerrata": _cmd_kerrata,
    "kpeimport": _cmd_kpeimport,
    "kauto": _cmd_kauto,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS[args.command]
    try:
        return handler(args)
    except KnowAtlasError as exc:
        print(f"错误（{type(exc).__name__}）：{exc}", file=sys.stderr)
        if exc.hint:
            print(f"下一步：{exc.hint}", file=sys.stderr)
        return EXIT_BUSINESS
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return EXIT_BUSINESS
