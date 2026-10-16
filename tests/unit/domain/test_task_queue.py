"""packages/domain/task_queue.py 测试 — 入队、worker 执行、重试、清理。"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from packages.domain.task_queue import TaskQueue, TaskStatus


async def _wait_for_status(
    queue: TaskQueue, task_id: str, status: TaskStatus, timeout: float = 3.0
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        task = await queue.get_task(task_id)
        if task is not None and task.status == status:
            return
        await asyncio.sleep(0.01)
    task = await queue.get_task(task_id)
    actual = task.status if task else None
    raise AssertionError(f"Task {task_id} did not reach {status}, actual={actual}")


@pytest.fixture
async def task_queue():
    q = TaskQueue(max_workers=2)
    yield q
    await q.stop()


class TestEnqueueAndGetTask:
    async def test_enqueue_returns_unique_ids(self, task_queue: TaskQueue):
        task_queue.register("noop", lambda ctx, *a, **kw: asyncio.sleep(0))
        id1 = await task_queue.enqueue("noop", "a")
        id2 = await task_queue.enqueue("noop", "b")
        assert id1 != id2

    async def test_enqueue_dedup_same_args(self, task_queue: TaskQueue):
        task_queue.register("noop", lambda ctx, *a, **kw: asyncio.sleep(0))
        id1 = await task_queue.enqueue("noop", "x")
        id2 = await task_queue.enqueue("noop", "x")
        assert id1 == id2

    async def test_enqueue_stores_task_with_args(self, task_queue: TaskQueue):
        task_id = await task_queue.enqueue("noop", "arg1", key="value")
        task = await task_queue.get_task(task_id)
        assert task is not None
        assert task.name == "noop"
        assert task.args == ("arg1",)
        assert task.kwargs == {"key": "value"}
        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 0
        assert task.completed_at is None

    async def test_get_task_unknown_returns_none(self, task_queue: TaskQueue):
        assert await task_queue.get_task("does-not-exist") is None

    async def test_task_has_created_at(self, task_queue: TaskQueue):
        task_id = await task_queue.enqueue("noop")
        task = await task_queue.get_task(task_id)
        assert task.created_at is not None
        assert task.created_at.tzinfo is not None


class TestWorkerExecution:
    async def test_task_completes_with_result(self, task_queue: TaskQueue):
        async def add(ctx, a, b):
            return a + b

        task_queue.register("add", add)
        await task_queue.start()
        task_id = await task_queue.enqueue("add", 2, 3)
        await _wait_for_status(task_queue, task_id, TaskStatus.COMPLETED)
        task = await task_queue.get_task(task_id)
        assert task.result == 5
        assert task.error is None
        assert task.completed_at is not None

    async def test_context_passed_to_task(self, task_queue: TaskQueue):
        async def read_ctx(ctx):
            return ctx.get("shared")

        task_queue.register("read_ctx", read_ctx)
        task_queue.set_context("shared", "hello")
        await task_queue.start()
        task_id = await task_queue.enqueue("read_ctx")
        await _wait_for_status(task_queue, task_id, TaskStatus.COMPLETED)
        task = await task_queue.get_task(task_id)
        assert task.result == "hello"

    async def test_multiple_tasks_all_complete(self, task_queue: TaskQueue):
        async def identity(ctx, n):
            return n

        task_queue.register("identity", identity)
        await task_queue.start()
        ids = [await task_queue.enqueue("identity", i) for i in range(6)]
        for task_id in ids:
            await _wait_for_status(task_queue, task_id, TaskStatus.COMPLETED)
        results = sorted([(await task_queue.get_task(tid)).result for tid in ids])
        assert results == [0, 1, 2, 3, 4, 5]

    async def test_unknown_task_fails_without_retry(self, task_queue: TaskQueue):
        q = TaskQueue(max_workers=1, max_retries=0)
        try:
            await q.start()
            task_id = await q.enqueue("nonexistent_task")
            await _wait_for_status(q, task_id, TaskStatus.FAILED)
            task = await q.get_task(task_id)
            assert task.error is not None
            assert "nonexistent_task" in task.error
            assert task.retry_count == 0
        finally:
            await q.stop()

    async def test_tasks_not_processed_before_start(self, task_queue: TaskQueue):
        task_queue.register("noop", lambda ctx: asyncio.sleep(0))
        task_id = await task_queue.enqueue("noop")
        await asyncio.sleep(0.1)
        task = await task_queue.get_task(task_id)
        assert task.status == TaskStatus.PENDING

    async def test_worker_survives_empty_queue_timeout(self, task_queue: TaskQueue):
        async def noop(ctx):
            return "ok"

        task_queue.register("noop", noop)
        await task_queue.start()
        await asyncio.sleep(1.3)
        task_id = await task_queue.enqueue("noop")
        await _wait_for_status(task_queue, task_id, TaskStatus.COMPLETED)
        task = await task_queue.get_task(task_id)
        assert task.result == "ok"


class TestRetry:
    async def test_retry_then_success(self, task_queue: TaskQueue):
        attempts = {"n": 0}

        async def flaky(ctx):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("transient failure")
            return "recovered"

        q = TaskQueue(max_workers=1, max_retries=3, retry_backoff=0)
        try:
            q.register("flaky", flaky)
            await q.start()
            task_id = await q.enqueue("flaky")
            await _wait_for_status(q, task_id, TaskStatus.COMPLETED)
            task = await q.get_task(task_id)
            assert task.result == "recovered"
            assert task.retry_count == 1
            assert task.error is None
            assert attempts["n"] == 2
        finally:
            await q.stop()

    async def test_exhausted_retries_marks_failed(self, task_queue: TaskQueue):
        attempts = {"n": 0}

        async def always_fails(ctx):
            attempts["n"] += 1
            raise RuntimeError(f"failure #{attempts['n']}")

        q = TaskQueue(max_workers=1, max_retries=2, retry_backoff=0)
        try:
            q.register("always_fails", always_fails)
            await q.start()
            task_id = await q.enqueue("always_fails")
            await _wait_for_status(q, task_id, TaskStatus.FAILED)
            task = await q.get_task(task_id)
            assert task.retry_count == 2
            assert task.error == "failure #3"
            assert attempts["n"] == 3
            assert task.completed_at is not None
        finally:
            await q.stop()

    async def test_exponential_backoff_delay(self, task_queue: TaskQueue):
        attempts: list[float] = []

        async def always_fails(ctx):
            attempts.append(asyncio.get_running_loop().time())
            raise RuntimeError("fail")

        q = TaskQueue(max_workers=1, max_retries=2, retry_backoff=0.05)
        try:
            q.register("always_fails", always_fails)
            await q.start()
            task_id = await q.enqueue("always_fails")
            await _wait_for_status(q, task_id, TaskStatus.FAILED, timeout=5.0)
            assert len(attempts) == 3
            gap1 = attempts[1] - attempts[0]
            gap2 = attempts[2] - attempts[1]
            assert gap1 >= 0.04
            assert gap2 >= 0.07
            assert gap2 > gap1
        finally:
            await q.stop()

    async def test_zero_retries_fails_immediately(self, task_queue: TaskQueue):
        attempts = {"n": 0}

        async def fails_once(ctx):
            attempts["n"] += 1
            raise ValueError("boom")

        q = TaskQueue(max_workers=1, max_retries=0)
        try:
            q.register("fails_once", fails_once)
            await q.start()
            task_id = await q.enqueue("fails_once")
            await _wait_for_status(q, task_id, TaskStatus.FAILED)
            assert attempts["n"] == 1
        finally:
            await q.stop()


class TestStartStop:
    async def test_start_is_idempotent(self, task_queue: TaskQueue):
        await task_queue.start()
        await task_queue.start()
        assert len(task_queue._workers) == 2
        assert task_queue._running is True

    async def test_stop_clears_workers(self, task_queue: TaskQueue):
        await task_queue.start()
        await task_queue.stop()
        assert task_queue._workers == []
        assert task_queue._running is False

    async def test_stop_without_start_is_safe(self, task_queue: TaskQueue):
        await task_queue.stop()

    async def test_stop_is_idempotent(self, task_queue: TaskQueue):
        await task_queue.start()
        await task_queue.stop()
        await task_queue.stop()

    async def test_restart_after_stop(self, task_queue: TaskQueue):
        async def noop(ctx):
            return "ok"

        task_queue.register("noop", noop)
        await task_queue.start()
        await task_queue.stop()
        await task_queue.start()
        task_id = await task_queue.enqueue("noop")
        await _wait_for_status(task_queue, task_id, TaskStatus.COMPLETED)

    async def test_module_shutdown_stops_singleton(self):
        from packages.domain import task_queue as tq_module

        await tq_module.queue.start()
        assert tq_module.queue._running is True
        await tq_module.shutdown()
        assert tq_module.queue._running is False
        assert tq_module.queue._workers == []


class TestCleanupCompletedTasks:
    async def test_removes_stale_completed_task(self, task_queue: TaskQueue):
        async def noop(ctx):
            return None

        await task_queue.start()
        task_queue.register("noop", noop)
        task_id = await task_queue.enqueue("noop")
        await _wait_for_status(task_queue, task_id, TaskStatus.COMPLETED)
        task = await task_queue.get_task(task_id)
        task.completed_at = datetime.now(UTC) - timedelta(seconds=400)
        task_queue._cleanup_completed_tasks()
        assert await task_queue.get_task(task_id) is None

    async def test_keeps_recent_completed_task(self, task_queue: TaskQueue):
        async def noop(ctx):
            return None

        await task_queue.start()
        task_queue.register("noop", noop)
        task_id = await task_queue.enqueue("noop")
        await _wait_for_status(task_queue, task_id, TaskStatus.COMPLETED)
        task_queue._cleanup_completed_tasks()
        assert await task_queue.get_task(task_id) is not None

    async def test_keeps_pending_tasks(self, task_queue: TaskQueue):
        task_id = await task_queue.enqueue("noop")
        task_queue._cleanup_completed_tasks()
        assert await task_queue.get_task(task_id) is not None

    async def test_keeps_stale_failed_task(self, task_queue: TaskQueue):
        """死信语义：FAILED 任务不被 300 秒清理，永久保留供诊断与手动重试。"""
        q = TaskQueue(max_workers=1, max_retries=0)
        try:
            await q.start()
            task_id = await q.enqueue("unknown_task")
            await _wait_for_status(q, task_id, TaskStatus.FAILED)
            task = await q.get_task(task_id)
            task.completed_at = datetime.now(UTC) - timedelta(seconds=400)
            q._cleanup_completed_tasks()
            assert await q.get_task(task_id) is not None
        finally:
            await q.stop()

    async def test_cleanup_triggered_after_threshold(self, task_queue: TaskQueue):
        async def noop(ctx):
            return None

        await task_queue.start()
        task_queue.register("noop", noop)

        stale_id = await task_queue.enqueue("noop")
        await _wait_for_status(task_queue, stale_id, TaskStatus.COMPLETED)
        stale_task = await task_queue.get_task(stale_id)
        stale_task.completed_at = datetime.now(UTC) - timedelta(seconds=400)

        task_queue._tasks_since_cleanup = 49
        trigger_id = await task_queue.enqueue("noop")
        await _wait_for_status(task_queue, trigger_id, TaskStatus.COMPLETED)

        assert task_queue._tasks_since_cleanup == 0
        assert await task_queue.get_task(stale_id) is None
        assert await task_queue.get_task(trigger_id) is not None


class TestSnapshot:
    async def test_empty_queue_all_zero(self, task_queue: TaskQueue):
        snap = task_queue.snapshot()
        assert snap["counts"] == {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        assert snap["oldest_pending_age_seconds"] is None
        assert snap["oldest_running_age_seconds"] is None
        assert snap["retry"] == {"retrying": 0, "average_retry_count": 0.0, "max_retry_count": 0}
        assert snap["failed"] == {"total": 0, "items": []}

    async def test_counts_and_ages(self, task_queue: TaskQueue):
        for i in range(5):
            await task_queue.enqueue("noop", f"arg{i}")
        # 直接改状态构造各状态样本：snapshot 只读，不依赖 worker 执行
        tasks = list(task_queue._tasks.values())
        tasks[0].status = TaskStatus.RUNNING
        tasks[1].status = TaskStatus.COMPLETED
        tasks[2].status = TaskStatus.FAILED

        snap = task_queue.snapshot()
        assert snap["counts"] == {"pending": 2, "running": 1, "completed": 1, "failed": 1}
        # 年龄按 created_at 距 now 计算，刚入队应接近 0 但非 None
        assert snap["oldest_pending_age_seconds"] is not None
        assert snap["oldest_pending_age_seconds"] >= 0
        assert snap["oldest_running_age_seconds"] is not None
        assert snap["oldest_running_age_seconds"] >= 0

    async def test_oldest_age_none_when_status_absent(self, task_queue: TaskQueue):
        task_id = await task_queue.enqueue("noop")
        task_queue._tasks[task_id].status = TaskStatus.RUNNING
        snap = task_queue.snapshot()
        assert snap["oldest_pending_age_seconds"] is None
        assert snap["oldest_running_age_seconds"] is not None

    async def test_retry_stats(self, task_queue: TaskQueue):
        id1 = await task_queue.enqueue("noop", "a")
        id2 = await task_queue.enqueue("noop", "b")
        await task_queue.enqueue("noop", "c")
        task_queue._tasks[id1].retry_count = 2
        task_queue._tasks[id2].retry_count = 1
        # id3 保持 0，拉低平均：均值应覆盖全部任务而非仅重试中任务
        snap = task_queue.snapshot()
        assert snap["retry"]["retrying"] == 2
        assert snap["retry"]["average_retry_count"] == pytest.approx(1.0)
        assert snap["retry"]["max_retry_count"] == 2

    async def test_retrying_counts_only_pending(self, task_queue: TaskQueue):
        task_id = await task_queue.enqueue("noop")
        task_queue._tasks[task_id].status = TaskStatus.RUNNING
        task_queue._tasks[task_id].retry_count = 5
        snap = task_queue.snapshot()
        # RUNNING 任务的 retry_count 是历史遗留，不计入"重试中"
        assert snap["retry"]["retrying"] == 0
        assert snap["retry"]["max_retry_count"] == 5

    async def test_failed_details_sorted_desc(self, task_queue: TaskQueue):
        base = datetime.now(UTC)
        ids = [await task_queue.enqueue("noop", f"arg{i}") for i in range(3)]
        for i, tid in enumerate(ids):
            task = task_queue._tasks[tid]
            task.status = TaskStatus.FAILED
            task.error = f"boom {i}"
            task.retry_count = i
            task.completed_at = base - timedelta(seconds=i)
        snap = task_queue.snapshot()
        assert snap["failed"]["total"] == 3
        items = snap["failed"]["items"]
        # 最新失败在前（completed_at 降序）
        assert [item["id"] for item in items] == [ids[0], ids[1], ids[2]]
        first = items[0]
        assert first["name"] == "noop"
        assert first["error"] == "boom 0"
        assert first["retry_count"] == 0
        assert first["created_at"] is not None
        assert first["completed_at"] is not None

    async def test_failed_items_truncated_but_total_kept(self, task_queue: TaskQueue):
        ids = [await task_queue.enqueue("noop", f"arg{i}") for i in range(60)]
        base = datetime.now(UTC)
        for i, tid in enumerate(ids):
            task = task_queue._tasks[tid]
            task.status = TaskStatus.FAILED
            task.completed_at = base - timedelta(seconds=i)
        snap = task_queue.snapshot()
        assert snap["counts"]["failed"] == 60
        assert snap["failed"]["total"] == 60
        assert len(snap["failed"]["items"]) == 50
        # 截断保留最新的 50 条：最老的 10 条被丢弃
        expected_first = ids[0]
        assert snap["failed"]["items"][0]["id"] == expected_first


class TestRetryFailed:
    async def _make_failed_task(self, name: str = "unknown_task") -> tuple[TaskQueue, str]:
        q = TaskQueue(max_workers=1, max_retries=0)
        await q.start()
        task_id = await q.enqueue(name)
        await _wait_for_status(q, task_id, TaskStatus.FAILED)
        return q, task_id

    async def test_resets_state_and_rebuilds_dedup_key(self):
        q, task_id = await self._make_failed_task()
        try:
            assert await q.retry_failed(task_id) is True
            task = await q.get_task(task_id)
            assert task.status == TaskStatus.PENDING
            assert task.error is None
            # retry_count 归零：手动重试是新一轮重试预算
            assert task.retry_count == 0
            assert task.completed_at is None
            dedup_key = (task.name, q._make_dedup_args_key(task.args, task.kwargs))
            assert q._pending_keys[dedup_key] == task_id
        finally:
            await q.stop()

    async def test_unknown_id_returns_false(self, task_queue: TaskQueue):
        assert await task_queue.retry_failed("no-such-id") is False

    async def test_non_failed_status_returns_false(self, task_queue: TaskQueue):
        task_id = await task_queue.enqueue("noop")
        assert await task_queue.retry_failed(task_id) is False
        task_queue._tasks[task_id].status = TaskStatus.COMPLETED
        assert await task_queue.retry_failed(task_id) is False

    async def test_retried_task_executes_successfully(self):
        attempts = {"n": 0}

        async def flaky(ctx):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("first attempt fails")
            return "recovered"

        q = TaskQueue(max_workers=1, max_retries=0, retry_backoff=0)
        try:
            q.register("flaky", flaky)
            await q.start()
            task_id = await q.enqueue("flaky")
            await _wait_for_status(q, task_id, TaskStatus.FAILED)
            assert await q.retry_failed(task_id) is True
            await _wait_for_status(q, task_id, TaskStatus.COMPLETED)
            task = await q.get_task(task_id)
            assert task.result == "recovered"
            assert attempts["n"] == 2
            assert task.retry_count == 0
        finally:
            await q.stop()
