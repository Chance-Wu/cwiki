"""轻量级内存任务队列：后台异步处理，支持磁盘持久化。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PERSIST_PATH = Path.home() / ".cwiki" / "state" / "task_queue.json"


class TaskStatus(str, Enum):
    """任务状态机：pending → running → completed/failed；失败未超重试上限则回到 pending。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    """队列任务条目：执行参数、状态与重试计数。"""

    id: str
    name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    retry_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


TaskFunc = Callable[..., Awaitable[Any]]


class TaskQueue:
    """带异步 worker 的简易内存任务队列。"""

    # 已完成任务的保留时长（秒）：供结果查询，超时后被清理
    # FAILED 任务例外：永久保留（死信语义）——失败任务需长期供诊断与手动重试，
    # 若也被 300 秒清理，失败原因和重放入口都会丢失
    _TASK_RETENTION_SECONDS = 300

    # snapshot 中 FAILED 明细的截断上限：防止失败风暴时响应过大；全量计数仍保留
    _FAILED_SNAPSHOT_LIMIT = 50

    def __init__(
        self,
        max_workers: int = 4,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        persist_path: Path | None = None,
    ) -> None:
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._tasks: dict[str, Task] = {}
        self._functions: dict[str, TaskFunc] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._max_workers = max_workers
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._running = False
        self._context: dict[str, Any] = {}
        self._tasks_since_cleanup = 0
        self._active_workers = 0
        self._pending_keys: dict[tuple[str, str], str] = {}
        self._persist_dirty = False
        self._persist_task: asyncio.Task[None] | None = None
        # 持久化路径可注入：测试与故障注入需隔离真机 ~/.cwiki/state
        self._persist_path = persist_path or _PERSIST_PATH

    def register(self, name: str, func: TaskFunc) -> None:
        """注册任务函数。"""
        self._functions[name] = func

    def set_context(self, key: str, value: Any) -> None:
        """设置任务执行时共享的上下文。"""
        self._context[key] = value

    async def enqueue(self, name: str, *args: Any, **kwargs: Any) -> str:
        """将任务入队后台执行。

        若已有相同 name+args 的 PENDING 任务在排队，则直接返回其
        task_id（去重），避免重复执行。
        """
        dedup_key = (name, self._make_dedup_args_key(args, kwargs))
        if dedup_key in self._pending_keys:
            existing_id = self._pending_keys[dedup_key]
            logger.debug("Dedup: task %s already pending as %s", name, existing_id)
            return existing_id

        task_id = str(uuid.uuid4())
        task = Task(id=task_id, name=name, args=args, kwargs=kwargs)
        self._tasks[task_id] = task
        self._pending_keys[dedup_key] = task_id
        self._persist_dirty = True
        await self._queue.put(task)
        logger.debug("Enqueued task %s with id %s", name, task_id)
        return task_id

    @staticmethod
    def _make_dedup_args_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        import json

        parts = [json.dumps(a, default=str, sort_keys=True) for a in args]
        parts += [
            f"{k}={json.dumps(v, default=str, sort_keys=True)}" for k, v in sorted(kwargs.items())
        ]
        return "|".join(parts)

    async def get_task(self, task_id: str) -> Task | None:
        """查询任务状态与结果。"""
        return self._tasks.get(task_id)

    async def start(self) -> None:
        """启动 worker，并从磁盘恢复上次未完成的任务。"""
        if self._running:
            return

        # 恢复上次运行遗留的 PENDING 任务与 FAILED 死信
        restored_pending, restored_failed = self._restore_persisted()
        for task in list(self._tasks.values()):
            if task.status == TaskStatus.PENDING:
                dedup_key = (task.name, self._make_dedup_args_key(task.args, task.kwargs))
                self._pending_keys[dedup_key] = task.id
                await self._queue.put(task)

        self._running = True
        for i in range(self._max_workers):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)
        self._persist_task = asyncio.create_task(self._persist_loop())
        logger.info(
            "Started %d task workers (restored %d pending, %d dead-letter)",
            self._max_workers,
            restored_pending,
            restored_failed,
        )

    async def stop(self, timeout: float = 10.0) -> None:
        """优雅停止全部 worker。

        先置 _running=False 拒绝新任务，等待执行中任务完成（最多
        timeout 秒），再取消 worker 协程。
        """
        self._running = False
        if self._active_workers > 0:
            logger.info(
                "Waiting for %d active worker(s) to finish (timeout=%.1fs)",
                self._active_workers,
                timeout,
            )
            deadline = asyncio.get_running_loop().time() + timeout
            while self._active_workers > 0 and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.1)
            if self._active_workers > 0:
                logger.warning(
                    "Timed out waiting for %d worker(s), cancelling",
                    self._active_workers,
                )
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        if self._persist_task:
            self._persist_task.cancel()
            try:
                await self._persist_task
            except asyncio.CancelledError:
                pass
            self._persist_task = None
        self._pending_keys.clear()

        # 关闭前把剩余 PENDING 任务落盘
        self._persist_dirty = True
        self._persist_snapshot()
        logger.info("Stopped task workers")

    async def _worker_loop(self, worker_id: int) -> None:
        """worker 循环：从队列取任务并执行。"""
        logger.debug("Worker %d started", worker_id)
        idle_backoff = 1.0  # 空闲时递增退避，减少 CPU 占用
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=idle_backoff)
                idle_backoff = 1.0  # 有任务时重置退避
            except TimeoutError:
                # 空闲时间递增，最高 30 秒
                idle_backoff = min(idle_backoff * 1.5, 30.0)
                continue
            except asyncio.CancelledError:
                break

            self._active_workers += 1
            try:
                dedup_key = (task.name, self._make_dedup_args_key(task.args, task.kwargs))
                # 任务开始执行即移除去重键：相同参数的新任务可再次入队
                self._pending_keys.pop(dedup_key, None)

                try:
                    task.status = TaskStatus.RUNNING
                    func = self._functions.get(task.name)
                    if not func:
                        raise ValueError(f"Unknown task: {task.name}")

                    logger.debug("Worker %d executing task %s (%s)", worker_id, task.name, task.id)
                    task.result = await func(self._context, *task.args, **task.kwargs)
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now(UTC)

                except Exception as e:
                    if task.retry_count < self._max_retries:
                        task.retry_count += 1
                        task.status = TaskStatus.PENDING
                        task.error = None
                        logger.warning(
                            "Task %s failed (attempt %d/%d), retrying: %s",
                            task.id,
                            task.retry_count,
                            self._max_retries,
                            e,
                        )
                        delay = self._retry_backoff * 2 ** (task.retry_count - 1)
                        # 指数退避后延迟重入队，不阻塞当前 worker
                        self._pending_keys[dedup_key] = task.id
                        asyncio.create_task(self._deferred_reenqueue(task, delay))
                    else:
                        logger.exception(
                            "Task %s failed after %d retries", task.id, task.retry_count
                        )
                        task.status = TaskStatus.FAILED
                        task.error = str(e)
                        task.completed_at = datetime.now(UTC)
                        # 死信需落盘：否则文件里仍是 PENDING，重启后会被
                        # 当作待执行任务重新跑一遍已耗尽重试预算的任务
                        self._persist_dirty = True

                finally:
                    self._queue.task_done()
                    self._tasks_since_cleanup += 1
                    if self._tasks_since_cleanup >= 50:
                        self._cleanup_completed_tasks()
                        self._tasks_since_cleanup = 0
                        self._persist_snapshot()
            finally:
                self._active_workers -= 1

    async def _deferred_reenqueue(self, task: Task, delay: float) -> None:
        """延迟一段时间后重新入队，不阻塞 worker。"""
        await asyncio.sleep(delay)
        await self._queue.put(task)

    async def _persist_loop(self) -> None:
        """定期把脏状态刷盘（每 2 秒）。"""
        while self._running:
            await asyncio.sleep(2.0)
            if self._persist_dirty:
                self._persist_snapshot()

    def _cleanup_completed_tasks(self) -> None:
        """清理超过保留期的已完成任务。

        FAILED 任务不参与清理（死信语义）：永久保留供诊断失败原因
        与手动重试，避免失败证据随时间丢失。
        """
        now = datetime.now(UTC)
        stale_ids = [
            tid
            for tid, t in self._tasks.items()
            if t.status == TaskStatus.COMPLETED
            and t.completed_at is not None
            and (now - t.completed_at).total_seconds() > self._TASK_RETENTION_SECONDS
        ]
        for tid in stale_ids:
            del self._tasks[tid]
        if stale_ids:
            self._persist_dirty = True
            logger.debug("Cleaned up %d stale tasks", len(stale_ids))

    def snapshot(self) -> dict[str, Any]:
        """只读快照：诊断队列积压、卡死与失败风暴。

        返回各状态计数、最老 pending/running 任务年龄、重试统计与
        FAILED 明细（死信列表，截断至 _FAILED_SNAPSHOT_LIMIT 条，
        全量计数见 counts.failed 与 failed.total）。
        不修改任何队列状态。
        """
        now = datetime.now(UTC)
        counts = {status.value: 0 for status in TaskStatus}
        oldest_pending: float | None = None
        oldest_running: float | None = None
        retrying = 0
        retry_total = 0
        retry_max = 0
        failed: list[dict[str, Any]] = []

        for t in self._tasks.values():
            counts[t.status.value] += 1
            retry_total += t.retry_count
            retry_max = max(retry_max, t.retry_count)
            age = (now - t.created_at).total_seconds()
            if t.status == TaskStatus.PENDING:
                # 年龄取最大值：最老任务最可能卡死
                if oldest_pending is None or age > oldest_pending:
                    oldest_pending = age
                if t.retry_count > 0:
                    retrying += 1
            elif t.status == TaskStatus.RUNNING:
                if oldest_running is None or age > oldest_running:
                    oldest_running = age
            elif t.status == TaskStatus.FAILED:
                failed.append(
                    {
                        "id": t.id,
                        "name": t.name,
                        "error": t.error,
                        "retry_count": t.retry_count,
                        "created_at": t.created_at,
                        "completed_at": t.completed_at,
                    }
                )

        # 最新失败排前：失败风暴时优先看到最近的错误
        failed.sort(key=lambda item: item["completed_at"] or item["created_at"], reverse=True)

        total = len(self._tasks)
        return {
            "counts": counts,
            "oldest_pending_age_seconds": oldest_pending,
            "oldest_running_age_seconds": oldest_running,
            "retry": {
                "retrying": retrying,
                "average_retry_count": retry_total / total if total else 0.0,
                "max_retry_count": retry_max,
            },
            "failed": {
                "total": len(failed),
                "items": failed[: self._FAILED_SNAPSHOT_LIMIT],
            },
        }

    async def retry_failed(self, task_id: str) -> bool:
        """手动重试 FAILED 任务（死信重放），重置为 PENDING 重新入队。

        retry_count 归零：手动重试是新一轮重试预算，否则已达上限的
        任务入队后会被 worker 立即再次标记 FAILED，重放永远无效。
        任务不存在或状态非 FAILED 时返回 False。
        """
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.FAILED:
            return False

        task.status = TaskStatus.PENDING
        task.error = None
        task.retry_count = 0
        task.completed_at = None
        # 重建 dedup key：FAILED 期间该键已被 worker 移除，不重建会导致
        # 相同参数的新任务与本次重放去重逻辑失效
        dedup_key = (task.name, self._make_dedup_args_key(task.args, task.kwargs))
        self._pending_keys[dedup_key] = task.id
        self._persist_dirty = True
        await self._queue.put(task)
        logger.info("Task %s manually re-enqueued after failure", task_id)
        return True

    def clear_failed(self, task_id: str | None = None) -> int:
        """清理 FAILED 死信任务。

        不传 task_id 时清理全部 FAILED 任务；传 task_id 时只清理指定任务。
        返回实际清理数量。
        """
        if task_id:
            task = self._tasks.get(task_id)
            if task is None or task.status != TaskStatus.FAILED:
                return 0
            del self._tasks[task_id]
            self._persist_dirty = True
            logger.info("Cleared failed task %s", task_id)
            return 1

        cleared = 0
        failed_ids = [tid for tid, t in self._tasks.items() if t.status == TaskStatus.FAILED]
        for tid in failed_ids:
            del self._tasks[tid]
            cleared += 1
        if cleared:
            self._persist_dirty = True
            logger.info("Cleared %d failed tasks", cleared)
        return cleared

    # ── 持久化 ───────────────────────────────────────────────────

    def _persist_snapshot(self) -> None:
        """原子地把 PENDING 与 FAILED 任务写入磁盘（状态变化时调用）。

        PENDING 用于重启续跑（at-least-once）；FAILED 是死信的持久
        形态 —— 死信若仅存内存，进程重启后失败证据与手动重放入口
        一起消失。RUNNING 不落盘：崩溃后由上次快照中的 PENDING 恢复，
        语义为重复执行。
        """
        if not self._persist_dirty:
            return
        self._persist_dirty = False

        entries = [
            {
                "id": t.id,
                "name": t.name,
                "args": list(t.args),
                "kwargs": t.kwargs,
                "retry_count": t.retry_count,
                "created_at": t.created_at.isoformat(),
                "status": t.status.value,
                "error": t.error,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in self._tasks.values()
            if t.status in (TaskStatus.PENDING, TaskStatus.FAILED)
        ]
        if not entries:
            self._persist_path.unlink(missing_ok=True)
            return

        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再 os.replace 原子替换，避免崩溃留下半写文件
            fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=self._persist_path.parent)
            try:
                os.close(fd)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(entries, f, default=str)
                os.replace(tmp, self._persist_path)
            except Exception:
                Path(tmp).unlink(missing_ok=True)
                raise
        except Exception as e:
            logger.warning("Failed to persist task queue: %s", e)

    def _restore_persisted(self) -> tuple[int, int]:
        """从磁盘恢复 PENDING 与 FAILED 任务，返回 ``(pending, failed)`` 数量。

        FAILED 死信恢复后仍处于 FAILED 状态，等待手动 retry_failed；
        旧版快照（无 status 字段）与异常状态一律按 PENDING 恢复。
        单条损坏记录跳过，不阻塞其余恢复。
        """
        if not self._persist_path.exists():
            return 0, 0
        try:
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("Failed to restore task queue: %s", e)
            return 0, 0

        restored_pending = 0
        restored_failed = 0
        for entry in data:
            task_id = entry.get("id")
            if not task_id or task_id in self._tasks:
                continue
            try:
                created_at = datetime.fromisoformat(entry["created_at"])
                completed_at_raw = entry.get("completed_at")
                completed_at = (
                    datetime.fromisoformat(completed_at_raw) if completed_at_raw else None
                )
                status_raw = entry.get("status", TaskStatus.PENDING.value)
                if status_raw == TaskStatus.FAILED.value:
                    status = TaskStatus.FAILED
                    restored_failed += 1
                elif status_raw == TaskStatus.PENDING.value:
                    status = TaskStatus.PENDING
                    restored_pending += 1
                else:
                    # RUNNING 等只可能来自异常快照 —— 按 PENDING 恢复（at-least-once）
                    logger.warning(
                        "Snapshot task %s has unexpected status %r, restoring as pending",
                        task_id,
                        status_raw,
                    )
                    status = TaskStatus.PENDING
                    restored_pending += 1
                task = Task(
                    id=task_id,
                    name=entry["name"],
                    args=tuple(entry.get("args", [])),
                    kwargs=entry.get("kwargs", {}),
                    status=status,
                    retry_count=entry.get("retry_count", 0),
                    created_at=created_at,
                    error=entry.get("error"),
                    completed_at=completed_at,
                )
                self._tasks[task_id] = task
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping corrupt snapshot entry %s: %s", task_id, exc)

        if restored_pending or restored_failed:
            logger.info(
                "Restored %d pending, %d dead-letter tasks from disk",
                restored_pending,
                restored_failed,
            )
        return restored_pending, restored_failed


queue = TaskQueue(max_workers=2)  # 优化：从 4 减少到 2，降低空闲时资源占用


async def startup() -> None:
    """初始化任务队列并注册任务函数。"""
    from apps.worker.tasks import recover_orphaned_candidates, register_tasks
    from packages.retrieval.embedding import get_embedding_service

    register_tasks(queue)
    queue.set_context("embedding_service", get_embedding_service())
    queue.set_context("queue", queue)
    await queue.start()
    await recover_orphaned_candidates(queue)


async def shutdown() -> None:
    """关闭任务队列。"""
    await queue.stop()
