"""批次 92 真库点层重整驱动（幂等续跑）：分批提炼式重抽，每批打印进度。

用法：
    python scripts/batch92_reextract.py            # 游标续跑（推荐，可重复执行）
    python scripts/batch92_reextract.py --purge-first  # 先清空旧点层再全量重抽

环境：KNOWATLAS_HOME=%USERPROFILE%\\.knowatlas；LLM 走 config（siliconflow）。
每轮 limit=10，池空或零产出即停，总轮次上限 30。幂等依据：已产出溯源指针的
条目自动跳过（point_source_entry_ids 游标）；--purge-first 清 points 即清游标。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knowatlas.config import load_config
from knowatlas.datalayer.db import DataLayer
from knowatlas.logging_setup import setup_logging
from knowatlas.pipeline.points import run_points_extract
from knowatlas.semantic.llm import LlmClient


def main() -> int:
    purge_first = "--purge-first" in sys.argv
    cfg = load_config()
    setup_logging(cfg.log_level)
    dl = DataLayer(cfg.db_path)
    dl.init_schema()
    llm = LlmClient.from_config(cfg)
    print(f"llm_enabled={llm is not None}", flush=True)
    if llm is None:
        print("LLM 未启用，中止（提炼需要 LLM）", flush=True)
        return 2
    if purge_first:
        n = dl.purge_points(reason="批次92 重整：清旧点层按提炼式口径重抽")
        print(f"purge_points -> {n}", flush=True)
    total_created = total_linked = total_err = 0
    t0 = time.time()
    for rnd in range(1, 31):
        stats = run_points_extract(cfg, dl, limit=10, llm=llm)
        total_created += stats.get("points_created", 0)
        total_linked += stats.get("points_linked", 0)
        total_err += len(stats.get("errors", []))
        print(f"[round {rnd}] {json.dumps(stats, ensure_ascii=False)}", flush=True)
        for err in stats.get("errors", [])[:5]:
            print(f"  ERROR {err['entry_id'][:12]} {err['title'][:36]}：{err['error']}",
                  flush=True)
        if stats.get("processed", 0) == 0:
            print("池空/零产出，结束", flush=True)
            break
    print(f"DONE created={total_created} linked={total_linked} errors={total_err} "
          f"elapsed={time.time()-t0:.0f}s", flush=True)
    dl.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
