"""寄生式记忆演化的可观测指标。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    CandidateMemory,
    Memory,
    Review,
    SessionNote,
)


async def compute_evolution_metrics(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    days: int = 30,
) -> dict[str, Any]:
    """统计指定 workspace 最近 N 天的演化指标。"""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    notes_created, notes_formalized = await _count_notes_stats(db, workspace_id, cutoff)
    candidates_submitted = await _count_candidates_submitted(db, workspace_id, cutoff)
    reviews_approved, reviews_rejected = await _count_review_stats(db, workspace_id, cutoff)
    memories_active, avg_confidence = await _count_memory_stats(db, workspace_id)

    total_reviews = reviews_approved + reviews_rejected
    approval_rate = round(reviews_approved / total_reviews, 2) if total_reviews > 0 else 0.0

    return {
        "period_days": days,
        "notes": {
            "created": notes_created,
            "formalized": notes_formalized,
            "formalization_rate": round(notes_formalized / notes_created, 2)
            if notes_created > 0
            else 0.0,
        },
        "submissions": {
            "total": candidates_submitted,
            "approved": reviews_approved,
            "rejected": reviews_rejected,
            "approval_rate": approval_rate,
        },
        "memory_health": {
            "active": memories_active,
            "avg_confidence": round(avg_confidence, 2) if avg_confidence else 0.0,
        },
    }


async def _count_notes_stats(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    cutoff: datetime,
) -> tuple[int, int]:
    stmt = select(
        func.count(SessionNote.id),
        func.sum(case((SessionNote.formalized == True, 1), else_=0)),
    ).where(
        SessionNote.workspace_id == workspace_id,
        SessionNote.created_at >= cutoff,
    )
    result = await db.execute(stmt)
    row = result.one()
    return (row[0] or 0, row[1] or 0)


async def _count_candidates_submitted(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    cutoff: datetime,
) -> int:
    stmt = select(func.count(CandidateMemory.id)).where(
        CandidateMemory.workspace_id == workspace_id,
        CandidateMemory.created_at >= cutoff,
    )
    result = await db.execute(stmt)
    return result.scalar_one()


async def _count_review_stats(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    cutoff: datetime,
) -> tuple[int, int]:
    # Review 本身没有 workspace_id，须经 candidate 关联才能限定范围
    stmt = (
        select(
            func.sum(case((Review.action == "approved", 1), else_=0)),
            func.sum(case((Review.action == "rejected", 1), else_=0)),
        )
        .join(CandidateMemory, Review.candidate_id == CandidateMemory.id)
        .where(
            CandidateMemory.workspace_id == workspace_id,
            Review.created_at >= cutoff,
        )
    )
    result = await db.execute(stmt)
    row = result.one()
    return (row[0] or 0, row[1] or 0)


async def _count_memory_stats(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> tuple[int, float | None]:
    stmt = select(
        func.sum(case((Memory.status == "active", 1), else_=0)),
        func.avg(case((Memory.status == "active", Memory.confidence), else_=None)),
    ).where(Memory.workspace_id == workspace_id)
    result = await db.execute(stmt)
    row = result.one()
    return (row[0] or 0, row[1])
