"""serve 内置的入库巡检线程（工单 2026-10-27《入库即抽点与自动老化》§2.2）。

为什么放在服务端（用户 2026-10-27 裁决 ⑤ 的未来形态）：这个工具最终是「一台机器干活、
多端点访问」的服务，自动处理不能依赖每台设备都装工具、也不能依赖谁记得敲命令。
`serve` 起来就自带巡检；`kauto --once` 是它的无界面等价物（计划任务/无 serve 场景）。

纪律：
- 单线程、串行轮次（不与自身重入），每轮都走 `run_ingest_pass` 的预算与 dead 队列；
- 任何异常只记日志，线程不退出（巡检是增强层，不能把服务拖垮）；
- `stop()` 用 Event 唤醒式退出（serve 关闭时调用），不阻塞进程退出。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("knowatlas.worker")


class IngestWorker(threading.Thread):
    """周期跑 `run_ingest_pass`；老化由 pass 内部按 `aging.interval_hours` 到点触发。"""

    def __init__(self, cfg: Any, dl: Any, locators: Any = None,
                 semantics: Any = None, *, interval: int | None = None) -> None:
        super().__init__(name="knowatlas-ingest", daemon=True)
        self.cfg = cfg
        self.dl = dl
        self.locators = locators
        self.semantics = semantics
        self.interval = int(interval or cfg.ingest_interval_seconds)
        self._stop = threading.Event()
        self.last_stats: dict[str, Any] | None = None
        self.last_error: str | None = None

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # noqa: D401 —— Thread.run
        logger.info("入库巡检启动：每 %ss 一轮（预算 %s 条/轮）",
                    self.interval, self.cfg.ingest_max_entries_per_run)
        while not self._stop.wait(self.interval):
            self.tick()

    def tick(self) -> dict[str, Any] | None:
        """跑一轮；异常吞掉并记录（返回 None）。测试可直接调它，不必起线程。"""
        from ..pipeline.ingest import run_ingest_pass

        try:
            stats = run_ingest_pass(self.cfg, self.dl, self.semantics,
                                    self.locators)
            self.last_stats = stats
            self.last_error = None
            if stats.get("activated") or stats.get("fetched") or stats.get("pipeline") \
                    or stats.get("kpe"):
                logger.info("入库巡检：激活 %s / 抓取 %s / 管道 %s / KPE %s / 新点 %s",
                            stats.get("activated"), stats.get("fetched"),
                            stats.get("pipeline"), stats.get("kpe"),
                            stats.get("points_created"))
            return stats
        except Exception as exc:  # noqa: BLE001 —— 巡检失败不拖垮服务
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("入库巡检失败：%s", self.last_error)
            return None


def start_worker(cfg: Any, dl: Any, locators: Any = None,
                 semantics: Any = None) -> IngestWorker | None:
    """按配置启动 worker；`ingest.enabled=false` 返回 None（零副作用）。"""
    if not cfg.ingest_enabled:
        logger.info("入库巡检未启用（[ingest] enabled=false）")
        return None
    worker = IngestWorker(cfg, dl, locators, semantics)
    worker.start()
    return worker


__all__ = ["IngestWorker", "start_worker"]