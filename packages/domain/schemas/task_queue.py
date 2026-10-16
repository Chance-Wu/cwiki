"""任务队列诊断 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TaskQueueCounts(BaseModel):
    """各状态任务计数。"""

    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0


class TaskQueueRetryStats(BaseModel):
    """重试统计。"""

    # 重试中：PENDING 且 retry_count > 0
    retrying: int = 0
    # 全部任务的平均重试次数（含 0 次任务）
    average_retry_count: float = 0.0
    max_retry_count: int = 0


class FailedTaskItem(BaseModel):
    """单个 FAILED 任务的死信明细。"""

    id: str
    name: str
    error: str | None = None
    retry_count: int = 0
    created_at: datetime
    completed_at: datetime | None = None


class TaskQueueFailedInfo(BaseModel):
    """FAILED 任务汇总。

    total 为全量计数，items 截断至队列侧上限（50 条）防响应过大。
    """

    total: int = 0
    items: list[FailedTaskItem] = Field(default_factory=list)


class TaskQueueStatusResponse(BaseModel):
    """任务队列只读快照：诊断积压、卡死与失败风暴。"""

    counts: TaskQueueCounts
    oldest_pending_age_seconds: float | None = None
    oldest_running_age_seconds: float | None = None
    retry: TaskQueueRetryStats
    failed: TaskQueueFailedInfo


class TaskQueueRetryRequest(BaseModel):
    """手动重试 FAILED 任务的请求体。"""

    task_id: str


class TaskQueueRetryResponse(BaseModel):
    """手动重试成功后的响应体。"""

    task_id: str
    status: str
