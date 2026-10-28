"""记忆质量端点：反馈与冲突。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, get_or_404, require_scope, resolve_workspace
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import Memory, MemoryConflict, MemoryFeedback, MemoryUsage
from packages.domain.schemas import (
    MemoryConflictRead,
    MemoryFeedbackCreate,
    MemoryFeedbackRead,
)


class ResolveConflictBody(BaseModel):
    resolution: str = Field(min_length=1)


router = APIRouter(prefix=API_V1_PREFIX, tags=["memory-quality"])


# ---------------------------------------------------------------------------
# 反馈端点
# ---------------------------------------------------------------------------


@router.post("/feedback", response_model=MemoryFeedbackRead, status_code=201)
async def create_feedback(
    body: MemoryFeedbackCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("feedback:write"))] = None,
) -> MemoryFeedbackRead:
    await get_or_404(db, Memory, body.memory_id, options=(defer(Memory.embedding),))

    resolved_ws_id = await resolve_workspace(body.workspace_id, db)

    feedback = MemoryFeedback(
        id=uuid.uuid4(),
        workspace_id=resolved_ws_id,
        memory_id=body.memory_id,
        feedback_type=body.feedback_type,
        source_type=body.source_type,
        source_id=body.source_id,
        reason=body.reason,
    )
    db.add(feedback)
    if body.feedback_type == "useful":
        # useful 反馈 = 该记忆被实际引用且有效 → 记一条 cited 使用流水，
        # 为 utility 的 agent_usage 分量提供生产者（此前该分量恒为 0）
        db.add(
            MemoryUsage(
                workspace_id=resolved_ws_id,
                memory_id=body.memory_id,
                stage="cited",
            )
        )
    await db.commit()
    await db.refresh(feedback)
    return MemoryFeedbackRead.model_validate(feedback)


@router.get("/feedback/summary/{memory_id}")
async def get_feedback_summary(
    memory_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    try:
        uid = uuid.UUID(memory_id)
    except ValueError:
        return {
            "memory_id": memory_id,
            "useful": 0,
            "not_useful": 0,
            "outdated": 0,
            "wrong": 0,
            "total": 0,
        }
    result = await db.execute(
        select(
            MemoryFeedback.feedback_type,
            func.count(MemoryFeedback.id),
        )
        .where(MemoryFeedback.memory_id == uid)
        .group_by(MemoryFeedback.feedback_type)
    )
    counts = {row[0]: row[1] for row in result.all()}
    return {
        "memory_id": memory_id,
        "useful": counts.get("useful", 0),
        "not_useful": counts.get("not_useful", 0),
        "outdated": counts.get("outdated", 0),
        "wrong": counts.get("wrong", 0),
        "total": sum(counts.values()),
    }


# ---------------------------------------------------------------------------
# 冲突端点
# ---------------------------------------------------------------------------


@router.get("/conflicts/all", response_model=list[MemoryConflictRead])
async def list_all_conflicts(
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
    status: str = Query("open", pattern=r"^(open|resolved|all)$"),
    limit: int = Query(20, ge=1, le=200),
) -> list[MemoryConflictRead]:
    stmt_query = select(MemoryConflict).order_by(MemoryConflict.created_at.desc()).limit(limit)
    if status != "all":
        stmt_query = stmt_query.where(MemoryConflict.status == status)
    result = await db.execute(stmt_query)
    return [MemoryConflictRead.model_validate(c) for c in result.scalars().all()]


@router.post("/conflicts/{conflict_id}/resolve", response_model=MemoryConflictRead)
async def resolve_conflict(
    conflict_id: uuid.UUID,
    body: ResolveConflictBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("conflicts:write"))] = None,
) -> MemoryConflictRead:
    conflict = await get_or_404(db, MemoryConflict, conflict_id)

    if conflict.status == "resolved":
        raise HTTPException(status_code=409, detail="Conflict already resolved")

    conflict.status = "resolved"
    conflict.resolution = body.resolution
    conflict.resolved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(conflict)
    return MemoryConflictRead.model_validate(conflict)
