"""任务队列诊断端点：查看队列快照与手动重试失败任务。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from packages.domain.config import API_V1_PREFIX
from packages.domain.schemas import (
    TaskQueueRetryRequest,
    TaskQueueRetryResponse,
    TaskQueueStatusResponse,
)
from packages.domain.task_queue import queue

logger = logging.getLogger(__name__)

# 创建任务队列路由组，tags 用于 OpenAPI 文档分组
router = APIRouter(tags=["task-queue"])


@router.get(f"{API_V1_PREFIX}/task-queue-status", response_model=TaskQueueStatusResponse)
async def task_queue_status() -> TaskQueueStatusResponse:
    """队列只读快照：状态计数、最老任务年龄、重试统计与 FAILED 死信明细。"""
    return TaskQueueStatusResponse.model_validate(queue.snapshot())


@router.post(f"{API_V1_PREFIX}/task-queue/retry", response_model=TaskQueueRetryResponse)
async def task_queue_retry(request: TaskQueueRetryRequest) -> TaskQueueRetryResponse:
    """手动重试 FAILED 任务：重置为 PENDING 并重新入队。"""
    retried = await queue.retry_failed(request.task_id)
    if not retried:
        # 404 同时覆盖任务不存在与状态非 FAILED 两种情况，避免向调用方泄露内部状态细节
        raise HTTPException(
            status_code=404,
            detail=f"Task not found or not in FAILED state: {request.task_id}",
        )
    return TaskQueueRetryResponse(task_id=request.task_id, status="pending")
