"""周期调度器——在 FastAPI lifespan 内运行，按固定间隔触发 TaskQueue 任务。

轻量实现：每个注册任务一个 asyncio 协程循环，sleep → enqueue → sleep。
TaskQueue 的去重机制保证同一任务未消费完时不会重复入队。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from packages.domain.task_queue import TaskQueue

logger = logging.getLogger(__name__)


@dataclass
class ScheduleEntry:
    """单条周期任务配置。"""

    task_name: str
    interval_seconds: float
    enabled: bool = True


@dataclass
class PeriodicScheduler:
    """按固定间隔向 TaskQueue 入队任务。"""

    queue: TaskQueue
    entries: list[ScheduleEntry] = field(default_factory=list)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list, repr=False)
    _stopped: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def add(self, task_name: str, interval_seconds: float, enabled: bool = True) -> None:
        self.entries.append(ScheduleEntry(task_name, interval_seconds, enabled))

    async def start(self) -> None:
        """启动全部周期任务协程。"""
        self._stopped.clear()
        for entry in self.entries:
            if not entry.enabled or entry.interval_seconds <= 0:
                logger.debug(
                    "Scheduler: skip %s (enabled=%s, interval=%s)",
                    entry.task_name,
                    entry.enabled,
                    entry.interval_seconds,
                )
                continue
            task = asyncio.create_task(self._run_loop(entry), name=f"scheduler:{entry.task_name}")
            self._tasks.append(task)
            logger.info("Scheduler: %s every %.0fs", entry.task_name, entry.interval_seconds)

    async def stop(self) -> None:
        """停止全部周期任务协程。"""
        self._stopped.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Scheduler stopped")

    async def _run_loop(self, entry: ScheduleEntry) -> None:
        """单条周期任务的循环：sleep → enqueue → sleep。"""
        try:
            while not self._stopped.is_set():
                await asyncio.sleep(entry.interval_seconds)
                if self._stopped.is_set():
                    break
                try:
                    await self.queue.enqueue(entry.task_name)
                    logger.debug("Scheduler: enqueued %s", entry.task_name)
                except Exception:
                    logger.warning(
                        "Scheduler: failed to enqueue %s",
                        entry.task_name,
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            pass
