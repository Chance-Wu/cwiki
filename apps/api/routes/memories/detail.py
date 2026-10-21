"""记忆详情端点（版本 / 反馈 / 检索历史）。"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, get_or_404
from apps.api.routes.memories._router import router
from apps.api.routes.memories._shared import _MEMORY_NO_EMBED
from packages.domain.models import (
    Memory,
    MemoryFeedback,
    MemoryVersion,
    RetrievalTrace,
    RetrievalTraceItem,
)
from packages.domain.schemas import (
    MemoryFeedbackListResponse,
    MemoryFeedbackRead,
    MemoryRetrievalHistory,
    MemoryRetrievalHit,
    MemoryVersionRead,
)


@router.get("/{memory_id}/versions", response_model=list[MemoryVersionRead])
async def get_memory_versions(
    memory_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(10, ge=1, le=50),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> list[MemoryVersionRead]:
    from packages.domain.config import parasitic_evolution_config

    if not parasitic_evolution_config.memory_version_tracking_enabled:
        return []

    try:
        uid = uuid.UUID(memory_id)
    except ValueError:
        return []

    stmt = (
        select(MemoryVersion)
        .where(MemoryVersion.memory_id == uid)
        .order_by(MemoryVersion.version.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()
    return [MemoryVersionRead.model_validate(v) for v in versions]


@router.get("/{memory_id}/feedback", response_model=MemoryFeedbackListResponse)
async def get_memory_feedback(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, ge=1, le=200),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> MemoryFeedbackListResponse:
    """列出该记忆的反馈明细（人工/Agent/自动，按时间倒序）。

    记忆不存在返回 404；存在但无反馈返回空列表，两种状态可区分。
    反馈的运行时唯一来源是 memory_feedback 表，_meta JSON 只是其
    Git 同步副本（重建时按 memory_id 恢复回表），两侧同源。
    """
    await get_or_404(db, Memory, memory_id, options=_MEMORY_NO_EMBED)

    result = await db.execute(
        select(MemoryFeedback)
        .where(MemoryFeedback.memory_id == memory_id)
        .order_by(MemoryFeedback.created_at.desc())
        .limit(limit)
    )
    feedbacks = result.scalars().all()
    return MemoryFeedbackListResponse(
        memory_id=memory_id,
        total=len(feedbacks),
        items=[MemoryFeedbackRead.model_validate(f) for f in feedbacks],
    )


@router.get("/{memory_id}/retrieval-history", response_model=MemoryRetrievalHistory)
async def get_memory_retrieval_history(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(5, ge=1, le=20),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> MemoryRetrievalHistory:
    """该记忆最近的检索命中历史，供详情页回答"最近在哪些查询中被命中"。

    每条含命中时的查询词、trace 创建时间、结果名次与各路信号分
    （bm25/vector/rrf/rerank/utility）及过滤原因；信号取自 trace 的
    metadata JSON，explain 关闭或旧数据无 metadata 时保持空默认。
    按命中时间倒序，默认 5 条、上限 20；total 为命中总次数（不受
    limit 截断），供前端提示"还有更多"。
    """
    await get_or_404(db, Memory, memory_id, options=_MEMORY_NO_EMBED)

    total_result = await db.execute(
        select(func.count(RetrievalTraceItem.id)).where(RetrievalTraceItem.memory_id == memory_id)
    )
    total = total_result.scalar() or 0

    result = await db.execute(
        select(RetrievalTraceItem, RetrievalTrace)
        .join(RetrievalTrace, RetrievalTrace.id == RetrievalTraceItem.trace_id)
        .where(RetrievalTraceItem.memory_id == memory_id)
        .order_by(RetrievalTrace.created_at.desc())
        .limit(limit)
    )

    mem_key = str(memory_id)
    items: list[MemoryRetrievalHit] = []
    for item_row, trace in result.all():
        # metadata 由 explain_enabled 开关控制是否落库，旧 trace 可能为 None
        metadata = trace.metadata_ if isinstance(trace.metadata_, dict) else {}
        raw_signals = metadata.get("signals", {}).get(mem_key, {})
        signals = {
            str(name): float(value)
            for name, value in raw_signals.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        # filter_reasons 是整条 trace 的平铺列表，按本记忆过滤
        filter_reasons = [
            {
                "memory_id": str(fr.get("memory_id", "")),
                "stage": str(fr.get("stage", "")),
                "reason": str(fr.get("reason", "")),
            }
            for fr in metadata.get("filter_reasons", [])
            if isinstance(fr, dict) and fr.get("memory_id") == mem_key
        ]
        items.append(
            MemoryRetrievalHit(
                trace_id=trace.id,
                query=trace.keyword,
                retrieved_at=trace.created_at,
                rank=item_row.rank,
                score=item_row.score,
                used=item_row.used,
                signals=signals,
                filter_reasons=filter_reasons,
            )
        )

    return MemoryRetrievalHistory(memory_id=memory_id, total=total, items=items)
