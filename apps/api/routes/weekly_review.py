"""本周学习回顾聚合：新增、复习、掌握度提升、高频复用、待整理，
以及三类行动项——未决冲突、已过时记忆、知识缺口（近 7 天无果检索）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import (
    Memory,
    MemoryConflict,
    MemoryUsage,
    RetrievalTrace,
    ReviewHistory,
    ReviewSchedule,
    SessionNote,
)

router = APIRouter(prefix=API_V1_PREFIX, tags=["review-weekly"])

# 召回缺口门槛：近 7 天被检索到这么多次、却一次也没被 used/cited，
# 才认为「排进来了但没帮上忙」，而不是偶然误召回
RETRIEVAL_GAP_MIN_HITS = 3


@router.get("/review/weekly")
async def weekly_review(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    now = datetime.now(UTC).replace(tzinfo=None)
    cutoff = now - timedelta(days=7)
    start = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)

    new_memories = (
        await db.execute(
            select(func.count(Memory.id)).where(
                Memory.workspace_id == resolved_ws_id,
                Memory.status == "active",
                Memory.created_at >= cutoff,
            )
        )
    ).scalar() or 0

    review_row = (
        await db.execute(
            select(func.count(ReviewHistory.id), func.avg(ReviewHistory.quality)).where(
                ReviewHistory.workspace_id == resolved_ws_id,
                ReviewHistory.reviewed_at >= cutoff,
            )
        )
    ).one()
    reviewed = review_row[0] or 0
    avg_quality = round(float(review_row[1]), 2) if review_row[1] is not None else None

    mastered_up = (
        await db.execute(
            select(func.count(ReviewHistory.id)).where(
                ReviewHistory.workspace_id == resolved_ws_id,
                ReviewHistory.reviewed_at >= cutoff,
                ReviewHistory.mastery_level_before.in_(("new", "learning", "familiar")),
                ReviewHistory.mastery_level_after.in_(("proficient", "mastered")),
            )
        )
    ).scalar() or 0

    # Stages are independent observations, not linked funnel conversions.
    retrieved_count = func.count(case((MemoryUsage.stage == "retrieved", MemoryUsage.id)))
    used_count = func.count(case((MemoryUsage.stage == "used", MemoryUsage.id)))
    cited_count = func.count(case((MemoryUsage.stage == "cited", MemoryUsage.id)))
    reuse_count = func.count(case((MemoryUsage.stage.in_(("used", "cited")), MemoryUsage.id)))
    usage_rows = (
        await db.execute(
            select(
                Memory.id,
                Memory.title,
                retrieved_count,
                used_count,
                cited_count,
            )
            .join(MemoryUsage, MemoryUsage.memory_id == Memory.id)
            .where(
                Memory.workspace_id == resolved_ws_id,
                Memory.status == "active",
                MemoryUsage.workspace_id == resolved_ws_id,
                MemoryUsage.created_at >= cutoff,
                MemoryUsage.created_at <= now,
            )
            .group_by(Memory.id, Memory.title)
            .having(reuse_count > 0)
            .order_by(reuse_count.desc(), retrieved_count.desc(), Memory.id.asc())
            .limit(5)
        )
    ).all()

    due_now = (
        await db.execute(
            select(func.count(ReviewSchedule.id))
            .join(Memory, ReviewSchedule.memory_id == Memory.id)
            .where(
                Memory.workspace_id == resolved_ws_id,
                Memory.status == "active",
                ReviewSchedule.next_review <= now,
            )
        )
    ).scalar() or 0

    pending_notes = (
        await db.execute(
            select(func.count(SessionNote.id)).where(
                SessionNote.workspace_id == resolved_ws_id,
                SessionNote.formalized.is_(False),
                SessionNote.discarded_at.is_(None),
            )
        )
    ).scalar() or 0

    # ---- 行动项 1：未决冲突 ----
    open_conflicts = (
        await db.execute(
            select(MemoryConflict.id, MemoryConflict.description, MemoryConflict.created_at)
            .where(
                MemoryConflict.workspace_id == resolved_ws_id,
                MemoryConflict.status == "open",
            )
            .order_by(MemoryConflict.created_at.asc())
            .limit(10)
        )
    ).all()

    # ---- 行动项 2：已过时（valid_to < 现在）但仍 active 的记忆 ----
    stale_rows = (
        await db.execute(
            select(Memory.id, Memory.title, Memory.valid_to)
            .where(
                Memory.workspace_id == resolved_ws_id,
                Memory.status == "active",
                Memory.valid_to.is_not(None),
                Memory.valid_to < now,
            )
            .order_by(Memory.valid_to.asc())
            .limit(10)
        )
    ).all()

    # ---- 行动项 4：召回缺口——命中多次却从未被用/引用的记忆 ----
    # 命中说明检索把它排进来了，交付为 0 说明内容没帮上忙（可能已过时或描述与问题不符）
    # 用一个高于偶然命中的门槛，避免单次误召回就占用周报版面
    retrieval_gap_rows = (
        await db.execute(
            select(Memory.id, Memory.title, retrieved_count, reuse_count)
            .join(MemoryUsage, MemoryUsage.memory_id == Memory.id)
            .where(
                Memory.workspace_id == resolved_ws_id,
                Memory.status == "active",
                MemoryUsage.workspace_id == resolved_ws_id,
                MemoryUsage.created_at >= cutoff,
                MemoryUsage.created_at <= now,
            )
            .group_by(Memory.id, Memory.title)
            .having(retrieved_count >= RETRIEVAL_GAP_MIN_HITS)
            .having(reuse_count == 0)
            .order_by(retrieved_count.desc(), Memory.id.asc())
            .limit(5)
        )
    ).all()

    # ---- 行动项 5：库内近似重复——写入累积出的重复条目，按需合并 ----
    # 只扫最近更新的 200 条，周报是首页请求，不能让 O(n²) 拖慢首屏
    from packages.memory.duplicate_scan import find_duplicate_pairs

    duplicate_scan = await find_duplicate_pairs(
        db,
        workspace_id=resolved_ws_id,
        limit=3,
        max_scan=200,
    )

    # ---- 行动项 3：知识缺口——近 7 天"无结果"检索的关键词 ----
    gap_rows = (
        await db.execute(
            select(RetrievalTrace.keyword, func.count(RetrievalTrace.id))
            .where(
                RetrievalTrace.workspace_id == resolved_ws_id,
                RetrievalTrace.created_at >= cutoff,
                RetrievalTrace.returned_count == 0,
            )
            .group_by(RetrievalTrace.keyword)
            .order_by(func.count(RetrievalTrace.id).desc())
            .limit(5)
        )
    ).all()

    return {
        "workspace_id": str(resolved_ws_id),
        "period_start": start.date().isoformat(),
        "period_end": now.date().isoformat(),
        "new_memories": new_memories,
        "reviewed": reviewed,
        "avg_quality": avg_quality,
        "mastered_up": mastered_up,
        "due_now": due_now,
        "pending_notes": pending_notes,
        "most_used": [
            {
                "memory_id": str(mid),
                "title": title,
                "uses": used + cited,
                "retrievals": retrieved,
                "context_uses": used,
                "citations": cited,
            }
            for mid, title, retrieved, used, cited in usage_rows
        ],
        "actions": {
            "conflicts": [
                {
                    "id": str(cid),
                    "description": description,
                    "created_at": created_at.isoformat() if created_at else None,
                }
                for cid, description, created_at in open_conflicts
            ],
            "stale_memories": [
                {
                    "memory_id": str(mid),
                    "title": title,
                    "valid_to": valid_to.isoformat() if valid_to else None,
                }
                for mid, title, valid_to in stale_rows
            ],
            "knowledge_gaps": [
                {"query": query, "attempts": attempts} for query, attempts in gap_rows
            ],
            "duplicate_pairs": duplicate_scan["pairs"],
            "retrieval_gaps": [
                {
                    "memory_id": str(mid),
                    "title": title,
                    "retrievals": retrieved,
                    "deliveries": delivered,
                }
                for mid, title, retrieved, delivered in retrieval_gap_rows
            ],
        },
    }
