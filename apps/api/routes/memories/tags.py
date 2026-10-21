"""标签管理端点（/v1/tags）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import Memory
from packages.domain.schemas import TagMergeRequest, TagRenameRequest

tags_router = APIRouter(prefix=f"{API_V1_PREFIX}/tags", tags=["tags"])


@tags_router.get("")
async def list_tags(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """列出 workspace 下所有标签及使用计数。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    stmt = select(Memory.tags).where(Memory.status == "active")
    if resolved_ws_id:
        stmt = stmt.where(Memory.workspace_id == resolved_ws_id)

    result = await db.execute(stmt)
    tag_counts: dict[str, int] = {}
    for row in result.all():
        mem_tags = row[0] or []
        for tag in mem_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    sorted_tags = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))
    return {
        "tags": [{"name": name, "count": count} for name, count in sorted_tags],
        "total": len(tag_counts),
    }


@tags_router.put("/{tag_name}")
async def rename_tag(
    tag_name: str,
    body: TagRenameRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """重命名标签（跨工作区或指定工作区）。"""
    new_name = body.new_name.strip().lower()
    if not new_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新标签名不能为空")

    old_name = tag_name.strip().lower()
    if old_name == new_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新旧标签名相同")

    stmt = select(Memory).where(Memory.status == "active")
    if workspace_id:
        resolved = await resolve_workspace(workspace_id, db)
        if resolved:
            stmt = stmt.where(Memory.workspace_id == resolved)
    # SQLite JSON 数组匹配：包含旧标签名的记忆
    stmt = stmt.where(Memory.tags.cast(String).contains(f'"{old_name}"'))

    result = await db.execute(stmt)
    memories = result.scalars().all()

    updated_count = 0
    for memory in memories:
        tags = memory.tags or []
        if old_name in tags:
            new_tags = [new_name if t == old_name else t for t in tags]
            memory.tags = new_tags
            updated_count += 1

    await db.commit()
    return {"old_name": old_name, "new_name": new_name, "updated_count": updated_count}


@tags_router.post("/merge")
async def merge_tags(
    body: TagMergeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """将多个标签合并为一个目标标签。"""
    target = body.target_tag.strip().lower()
    if not target:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "目标标签名不能为空")

    sources = [s.strip().lower() for s in body.source_tags if s.strip()]
    if target in sources:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "目标标签不能在源标签列表中")

    stmt = select(Memory).where(Memory.status == "active")
    if workspace_id:
        resolved = await resolve_workspace(workspace_id, db)
        if resolved:
            stmt = stmt.where(Memory.workspace_id == resolved)

    # 查找包含任一源标签的记忆
    conditions = [Memory.tags.cast(String).contains(f'"{s}"') for s in sources]
    stmt = stmt.where(or_(*conditions))

    result = await db.execute(stmt)
    memories = result.scalars().all()

    updated_count = 0
    for memory in memories:
        tags = memory.tags or []
        has_source = any(s in tags for s in sources)
        if not has_source:
            continue
        new_tags = [t for t in tags if t not in sources]
        if target not in new_tags:
            new_tags.append(target)
        memory.tags = new_tags
        updated_count += 1

    await db.commit()
    return {
        "source_tags": sources,
        "target_tag": target,
        "updated_count": updated_count,
    }


@tags_router.delete("/{tag_name}")
async def delete_tag(
    tag_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """从所有记忆中删除指定标签。"""
    tag = tag_name.strip().lower()
    if not tag:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "标签名不能为空")

    stmt = select(Memory).where(Memory.status == "active")
    if workspace_id:
        resolved = await resolve_workspace(workspace_id, db)
        if resolved:
            stmt = stmt.where(Memory.workspace_id == resolved)
    stmt = stmt.where(Memory.tags.cast(String).contains(f'"{tag}"'))

    result = await db.execute(stmt)
    memories = result.scalars().all()

    updated_count = 0
    for memory in memories:
        tags = memory.tags or []
        if tag in tags:
            memory.tags = [t for t in tags if t != tag]
            updated_count += 1

    await db.commit()
    return {"tag": tag, "updated_count": updated_count}
