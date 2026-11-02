"""周期调度器 initial_delay：启动即入队、未到期不提前触发。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from packages.domain.scheduler import PeriodicScheduler


async def test_initial_delay_zero_enqueues_immediately():
    queue = AsyncMock()
    scheduler = PeriodicScheduler(queue=queue)
    scheduler.add("meta_export", 3600, initial_delay=0)

    await scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()

    queue.enqueue.assert_awaited_once_with("meta_export")


async def test_initial_delay_defers_first_enqueue():
    queue = AsyncMock()
    scheduler = PeriodicScheduler(queue=queue)
    scheduler.add("meta_export", 3600, initial_delay=60)

    await scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()

    queue.enqueue.assert_not_awaited()


async def test_default_initial_delay_is_full_interval():
    queue = AsyncMock()
    scheduler = PeriodicScheduler(queue=queue)
    scheduler.add("meta_export", 60)

    await scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()

    queue.enqueue.assert_not_awaited()


@pytest.mark.parametrize("interval", [0, -1])
async def test_disabled_when_interval_not_positive(interval):
    queue = AsyncMock()
    scheduler = PeriodicScheduler(queue=queue)
    scheduler.add("meta_export", interval, initial_delay=0)

    await scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()

    queue.enqueue.assert_not_awaited()
