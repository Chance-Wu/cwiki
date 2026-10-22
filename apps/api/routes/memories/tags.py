"""标签管理端点（/v1/tags）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from apps.api.file_sync import sync_memory_to_file
from apps.api.routes.context import invalidate_context_cache
from apps.api.routes.search import invalidate_search_cache
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import Memory
from packages.domain.schemas import TagMergeRequest, TagRenameRequest
from packages.memory.service import normalize_tags
from packages.memory.tag_query import memory_has_tag

tags_router = APIRouter(prefix=f"{API_V1_PREFIX}/tags", tags=["tags"])


@tags_router.get("")
async def list_tags(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    memory_status: str | None = Query(
        None, alias="status", description="按记忆状态过滤，不传则统计全部状态"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """列出 workspace 下所有标签及使用计数（默认含归档等全部状态）。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    stmt = select(Memory.tags)
    if resolved_ws_id:
        stmt = stmt.where(Memory.workspace_id == resolved_ws_id)
    if memory_status:
        stmt = stmt.where(Memory.status == memory_status)

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


@tags_router.put("/{tag_name:path}")
async def rename_tag(
    tag_name: str,
    body: TagRenameRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """重命名标签（覆盖全部状态；跨工作区或指定工作区）。"""
    new_name = body.new_name.strip().lower()
    if not new_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新标签名不能为空")

    old_name = tag_name.strip().lower()
    if old_name == new_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新旧标签名相同")

    stmt = select(Memory)
    if workspace_id:
        resolved = await resolve_workspace(workspace_id, db)
        if resolved:
            stmt = stmt.where(Memory.workspace_id == resolved)
    stmt = stmt.where(memory_has_tag(old_name))

    result = await db.execute(stmt)
    memories = result.scalars().all()

    changed: list[Memory] = []
    for memory in memories:
        tags = memory.tags or []
        if old_name in tags:
            memory.tags = normalize_tags([new_name if t == old_name else t for t in tags])
            changed.append(memory)

    await db.commit()
    for memory in changed:
        await sync_memory_to_file(memory, db, skip_vector_index=True)
    invalidate_search_cache()
    invalidate_context_cache()
    return {
        "old_name": old_name,
        "new_name": new_name,
        "updated_count": len(changed),
    }


@tags_router.post("/merge")
async def merge_tags(
    body: TagMergeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """将多个标签合并为一个目标标签（覆盖全部状态）。"""
    target = body.target_tag.strip().lower()
    if not target:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "目标标签名不能为空")

    sources = [s.strip().lower() for s in body.source_tags if s.strip()]
    if target in sources:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "目标标签不能在源标签列表中")

    stmt = select(Memory)
    if workspace_id:
        resolved = await resolve_workspace(workspace_id, db)
        if resolved:
            stmt = stmt.where(Memory.workspace_id == resolved)

    # 查找包含任一源标签的记忆
    conditions = [memory_has_tag(s) for s in sources]
    stmt = stmt.where(or_(*conditions))

    result = await db.execute(stmt)
    memories = result.scalars().all()

    changed: list[Memory] = []
    for memory in memories:
        tags = memory.tags or []
        has_source = any(s in tags for s in sources)
        if not has_source:
            continue
        new_tags = [t for t in tags if t not in sources]
        if target not in new_tags:
            new_tags.append(target)
        memory.tags = normalize_tags(new_tags)
        changed.append(memory)

    await db.commit()
    for memory in changed:
        await sync_memory_to_file(memory, db, skip_vector_index=True)
    invalidate_search_cache()
    invalidate_context_cache()
    return {
        "source_tags": sources,
        "target_tag": target,
        "updated_count": len(changed),
    }


@tags_router.delete("/{tag_name:path}")
async def delete_tag(
    tag_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """从所有记忆（含归档等全部状态）中删除指定标签。"""
    tag = tag_name.strip().lower()
    if not tag:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "标签名不能为空")

    stmt = select(Memory)
    if workspace_id:
        resolved = await resolve_workspace(workspace_id, db)
        if resolved:
            stmt = stmt.where(Memory.workspace_id == resolved)
    stmt = stmt.where(memory_has_tag(tag))

    result = await db.execute(stmt)
    memories = result.scalars().all()

    changed: list[Memory] = []
    for memory in memories:
        tags = memory.tags or []
        if tag in tags:
            memory.tags = [t for t in tags if t != tag]
            changed.append(memory)

    await db.commit()
    for memory in changed:
        await sync_memory_to_file(memory, db, skip_vector_index=True)
    invalidate_search_cache()
    invalidate_context_cache()
    return {"tag": tag, "updated_count": len(changed)}
