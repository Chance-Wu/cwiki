"""间隔重复复习端点。"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from packages.domain.config import API_V1_PREFIX
from packages.domain.schemas import (
    BatchReviewRequest,
    BatchReviewResultRead,
    ReviewItemRead,
    ReviewResultRead,
    ReviewStatsRead,
    ReviewSubmitRequest,
)
from packages.memory.review_service import get_review_service

router = APIRouter(prefix=f"{API_V1_PREFIX}/review", tags=["review"])


@router.get("/due", response_model=list[ReviewItemRead])
async def get_due_reviews(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> list[dict[str, Any]]:
    """获取到期需要复习的记忆。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()
    return await service.get_due_reviews(db, resolved_ws_id, limit)


@router.post("/{memory_id}", response_model=ReviewResultRead)
async def submit_review(
    memory_id: uuid.UUID,
    body: ReviewSubmitRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """提交记忆的复习结果。

    质量评分（0-5）：
    - 5: 完美回忆
    - 4: 犹豫后答对
    - 3: 费力答对
    - 2: 答错，但看答案后想起了
    - 1: 答错，但看到答案觉得眼熟
    - 0: 完全想不起来
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()
    try:
        result = await service.submit_review(db, memory_id, body.quality, resolved_ws_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/stats", response_model=ReviewStatsRead)
async def get_review_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """获取工作区的复习统计。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()
    return await service.get_review_stats(db, resolved_ws_id)


@router.post("/schedule/{memory_id}")
async def schedule_memory_review(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """把记忆排入间隔重复复习计划。

    通常在记忆被批准后调用，以启动其复习周期。
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()
    result = await service.schedule_memory(db, memory_id, resolved_ws_id)

    if result is None:
        return {"status": "already_scheduled", "memory_id": str(memory_id)}
    return result


@router.post("/undo/{memory_id}")
async def undo_review(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """撤销记忆最近一次复习。

    把复习计划恢复到上次复习前的状态；无历史可撤销时返回 404。
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()
    result = await service.undo_review(db, memory_id, resolved_ws_id)

    if result is None:
        raise HTTPException(status_code=404, detail="No review history to undo")
    return result


@router.post("/batch", response_model=BatchReviewResultRead)
async def batch_submit_reviews(
    body: BatchReviewRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """一次性提交多条复习结果。

    各条独立处理：某条失败（如记忆不存在）不影响其他条目。
    返回带逐条结果的汇总。
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    for item in body.reviews:
        try:
            result = await service.submit_review(db, item.memory_id, item.quality, resolved_ws_id)
            results.append(
                {
                    "memory_id": item.memory_id,
                    "success": True,
                    "error": None,
                    "result": result,
                }
            )
            succeeded += 1
        except Exception as e:
            # 单条失败只记录，继续处理剩余复习
            results.append(
                {
                    "memory_id": item.memory_id,
                    "success": False,
                    "error": str(e),
                    "result": None,
                }
            )
            failed += 1

    return {
        "results": results,
        "total": len(body.reviews),
        "succeeded": succeeded,
        "failed": failed,
    }
