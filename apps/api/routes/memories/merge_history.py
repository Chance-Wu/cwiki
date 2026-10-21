"""记忆合并历史相关端点。"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from apps.api.routes.memories._router import router
from packages.domain.models import Memory, MemoryLifecycleEvent, MemoryRelation

logger = logging.getLogger(__name__)


@router.get("/merge-history")
async def get_merge_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """获取合并历史记录。

    返回最近的合并操作，包括合并时间、保留的记忆、归档的记忆等信息。
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db)

    # 查询合并相关的生命周期事件
    stmt = (
        select(MemoryLifecycleEvent)
        .join(Memory, Memory.id == MemoryLifecycleEvent.memory_id)
        .where(
            Memory.workspace_id == resolved_ws_id,
            MemoryLifecycleEvent.event_type.in_(["merged", "auto_merged"]),
        )
        .order_by(MemoryLifecycleEvent.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    # 构建合并历史列表
    merge_history: list[dict[str, Any]] = []
    for event in events:
        # 查找 supersedes 关系，获取被归档的记忆
        rel_stmt = (
            select(MemoryRelation)
            .where(
                MemoryRelation.source_memory_id == event.memory_id,
                MemoryRelation.relation_type == "supersedes",
            )
            .order_by(MemoryRelation.created_at.desc())
        )
        rel_result = await db.execute(rel_stmt)
        relations = rel_result.scalars().all()

        # 获取保留的记忆信息
        keeper_mem = await db.get(Memory, event.memory_id)
        if not keeper_mem:
            continue

        # 获取被归档的记忆信息
        archived_memories = []
        for rel in relations:
            archived_mem = await db.get(Memory, rel.target_memory_id)
            if archived_mem:
                archived_memories.append(
                    {
                        "id": str(archived_mem.id),
                        "title": archived_mem.title,
                        "status": archived_mem.status,
                    }
                )

        # 解析 metadata
        metadata = {}
        if event.metadata_json:
            try:
                import json

                metadata = json.loads(event.metadata_json)
            except Exception:
                logger.warning("Failed to parse merge event metadata", exc_info=True)

        merge_history.append(
            {
                "event_id": str(event.id),
                "merged_at": event.created_at.isoformat(),
                "event_type": event.event_type,
                "keeper_memory": {
                    "id": str(keeper_mem.id),
                    "title": keeper_mem.title,
                    "status": keeper_mem.status,
                },
                "archived_memories": archived_memories,
                "similarity": metadata.get("similarity"),
                "strategy": metadata.get("strategy"),
            }
        )

    return {
        "items": merge_history,
        "total": len(merge_history),
        "limit": limit,
        "offset": offset,
    }
