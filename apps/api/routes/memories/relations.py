"""记忆关系端点（关系图查询与手动关系管理）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db
from apps.api.routes.memories._router import router
from apps.api.routes.memories._shared import _MEMORY_NO_EMBED
from packages.domain.models import Memory, MemoryRelation
from packages.domain.schemas import RelationCreate, RelationUpdate


@router.get("/{memory_id}/relations")
async def get_memory_relations(
    memory_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    depth: int = Query(1, ge=1, le=3),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """获取记忆关系图，最多展开 depth 层。"""
    try:
        uid = uuid.UUID(memory_id)
    except ValueError:
        return {
            "memory_id": memory_id,
            "relations": [],
            "related_memories": [],
            "total_relations": 0,
        }

    memory = await db.get(Memory, uid, options=_MEMORY_NO_EMBED)
    if memory is None:
        return {
            "memory_id": memory_id,
            "relations": [],
            "related_memories": [],
            "total_relations": 0,
        }

    relations: list[dict[str, Any]] = []
    visited: set[uuid.UUID] = {uid}
    frontier = [uid]

    for _ in range(depth):
        if not frontier:
            break
        stmt = (
            select(MemoryRelation)
            .where(
                (MemoryRelation.source_memory_id.in_(frontier))
                | (MemoryRelation.target_memory_id.in_(frontier))
            )
            .limit(50)
        )
        result = await db.execute(stmt)
        next_frontier: list[uuid.UUID] = []
        for rel in result.scalars().all():
            relations.append(
                {
                    "id": str(rel.id),
                    "source_memory_id": str(rel.source_memory_id),
                    "target_memory_id": str(rel.target_memory_id),
                    "relation_type": rel.relation_type,
                    "confidence": rel.confidence,
                }
            )
            other = (
                rel.target_memory_id if rel.source_memory_id in visited else rel.source_memory_id
            )
            if other not in visited:
                visited.add(other)
                next_frontier.append(other)
        frontier = next_frontier

    related_ids = visited - {uid}
    related_memories = []
    if related_ids:
        mem_stmt = select(Memory.id, Memory.title, Memory.type).where(
            Memory.id.in_(list(related_ids))
        )
        result = await db.execute(mem_stmt)
        for row in result.all():
            related_memories.append(
                {
                    "id": str(row._mapping[Memory.id]),
                    "title": row._mapping[Memory.title],
                    "type": row._mapping[Memory.type],
                }
            )

    return {
        "memory_id": memory_id,
        "relations": relations,
        "related_memories": related_memories,
        "total_relations": len(relations),
    }


@router.post("/{memory_id}/relations", status_code=status.HTTP_201_CREATED)
async def create_memory_relation(
    memory_id: str,
    body: RelationCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """手动创建两条记忆之间的关系。"""
    try:
        source_uid = uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "无效的 memory_id")

    source = await db.get(Memory, source_uid, options=_MEMORY_NO_EMBED)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "源记忆不存在")

    target = await db.get(Memory, body.target_memory_id, options=_MEMORY_NO_EMBED)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "目标记忆不存在")

    if source_uid == body.target_memory_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能与自身建立关系")

    stmt = select(MemoryRelation).where(
        MemoryRelation.source_memory_id == source_uid,
        MemoryRelation.target_memory_id == body.target_memory_id,
        MemoryRelation.relation_type == body.relation_type,
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该关系已存在")

    relation = MemoryRelation(
        id=uuid.uuid4(),
        source_memory_id=source_uid,
        target_memory_id=body.target_memory_id,
        relation_type=body.relation_type,
        confidence=body.confidence,
        created_at=datetime.now(UTC),
    )
    db.add(relation)
    await db.commit()
    await db.refresh(relation)

    return {
        "id": str(relation.id),
        "source_memory_id": str(relation.source_memory_id),
        "target_memory_id": str(relation.target_memory_id),
        "relation_type": relation.relation_type,
        "confidence": relation.confidence,
    }


@router.delete("/{memory_id}/relations/{relation_id}")
async def delete_memory_relation(
    memory_id: str,
    relation_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, str]:
    """删除指定的记忆关系。"""
    try:
        rel_uid = uuid.UUID(relation_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "无效的 relation_id")

    relation = await db.get(MemoryRelation, rel_uid)
    if relation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "关系不存在")

    await db.delete(relation)
    await db.commit()
    return {"status": "deleted", "id": relation_id}


@router.patch("/{memory_id}/relations/{relation_id}")
async def update_memory_relation(
    memory_id: str,
    relation_id: str,
    body: RelationUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """更新关系的类型或置信度。"""
    try:
        rel_uid = uuid.UUID(relation_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "无效的 relation_id")

    relation = await db.get(MemoryRelation, rel_uid)
    if relation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "关系不存在")

    if body.relation_type is not None:
        relation.relation_type = body.relation_type
    if body.confidence is not None:
        relation.confidence = body.confidence

    await db.commit()
    await db.refresh(relation)

    return {
        "id": str(relation.id),
        "source_memory_id": str(relation.source_memory_id),
        "target_memory_id": str(relation.target_memory_id),
        "relation_type": relation.relation_type,
        "confidence": relation.confidence,
    }
