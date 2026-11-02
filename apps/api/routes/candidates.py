"""候选记忆端点。"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import (
    apply_optional_filters,
    execute_paginated,
    get_current_agent,
    get_db,
    get_or_404,
    require_scope,
    resolve_workspace,
)
from packages.domain.config import API_V1_PREFIX, settings
from packages.domain.models import CandidateMemory, Workspace
from packages.domain.schemas import (
    CandidateMemoryCreate,
    CandidateMemoryCreateResponse,
    CandidateMemoryRead,
    CandidateStatus,
    MemoryType,
    PaginatedResponse,
    SimilarItemRead,
)
from packages.domain.task_queue import queue
from packages.memory.service import ContentFormatError, create_candidate

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_V1_PREFIX}/candidates", tags=["candidates"])


@router.post("", response_model=CandidateMemoryCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_candidate_endpoint(
    body: CandidateMemoryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("candidates:write"))] = None,
) -> CandidateMemoryCreateResponse:
    """创建待人工审核的候选记忆。

    返回创建的候选，以及提交时发现的相似已有记忆或待审候选。
    """
    resolved_ws_id = await resolve_workspace(body.workspace_id, db)
    try:
        candidate, similar_items, created = await create_candidate(
            db=db,
            workspace_id=resolved_ws_id,
            title=body.title,
            content=body.content,
            type=body.type,
            tags=body.tags,
            is_permanent=body.is_permanent,
            permanent_reason=body.permanent_reason,
            source=body.source,
            confidence=body.confidence or 0.5,
            importance=body.importance or 0.5,
            project_id=body.project_id,
            episode_id=body.episode_id,
            client_write_id=body.client_write_id,
            legacy_client_write_id=body.legacy_client_write_id,
        )
    except ContentFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    if created:
        # 去重：同一 client_write_id 幂等，只有真正新建时才失效缓存并入队生成向量
        from apps.api.routes.memory_status import invalidate_memory_status_caches

        invalidate_memory_status_caches()
        await queue.enqueue("generate_candidate_embedding", str(candidate.id))

    similar_items_response = [
        SimilarItemRead(
            id=item.id,
            title=item.title,
            content_preview=item.content_preview,
            similarity=item.similarity,
            source=item.source,
        )
        for item in similar_items
    ]

    hint = None
    if similar_items:
        top_similarity = similar_items[0].similarity if similar_items else 0
        if top_similarity >= settings.consolidate_threshold:
            top_title = similar_items[0].title
            hint = (
                f"与已有记忆「{top_title}」相似度 {top_similarity:.0%}，"
                "建议使用 memory_update 更新已有记忆而非重复提交。"
            )
        else:
            hint = "发现相似记忆。如果是纠正错误，请保留原提交；如果是重复，可忽略。"

    return CandidateMemoryCreateResponse(
        candidate=CandidateMemoryRead.model_validate(candidate),
        similar_items=similar_items_response,
        hint=hint,
        created=created,
    )


@router.get("", response_model=PaginatedResponse[CandidateMemoryRead])
async def list_candidates(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    candidate_status: CandidateStatus | None = Query(None, alias="status"),
    memory_type: MemoryType | None = Query(None, alias="type"),
    source: str | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    min_quality_gate: float | None = Query(None, ge=0, le=1),
    min_value: float | None = Query(None, ge=0, le=1),
    max_duplicate: float | None = Query(None, ge=0, le=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[CandidateMemoryRead]:
    """列出候选记忆，支持可选过滤。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    stmt = select(CandidateMemory)
    count_stmt = select(func.count(CandidateMemory.id))

    conditions = []
    if resolved_ws_id:
        conditions.append(CandidateMemory.workspace_id == resolved_ws_id)
    if candidate_status:
        conditions.append(CandidateMemory.status == candidate_status)
    if memory_type:
        conditions.append(CandidateMemory.type == memory_type)
    if source:
        conditions.append(CandidateMemory.source == source)
    if project_id:
        conditions.append(CandidateMemory.project_id == project_id)
    if min_quality_gate is not None:
        conditions.append(CandidateMemory.quality_gate_score >= min_quality_gate)
    if min_value is not None:
        conditions.append(CandidateMemory.value_score >= min_value)
    if max_duplicate is not None:
        conditions.append(CandidateMemory.duplicate_probability <= max_duplicate)
    stmt, count_stmt = apply_optional_filters(stmt, count_stmt, conditions)

    # 收件箱按审核优先级排序（低分 = 高优先级），未评分的排在后面，
    # 同优先级按提交时间倒序；旧行为纯 created_at 会让高分垃圾堵住低分重要候选
    order_by = (
        case((CandidateMemory.review_priority.is_(None), 1), else_=0),
        CandidateMemory.review_priority.asc(),
        CandidateMemory.created_at.desc(),
    )
    total, candidates = await execute_paginated(db, stmt, count_stmt, order_by, offset, limit)

    # 批量取 workspace 名称用于展示
    workspace_ids = {c.workspace_id for c in candidates}
    workspace_names: dict[uuid.UUID, str] = {}
    if workspace_ids:
        ws_result = await db.execute(select(Workspace).where(Workspace.id.in_(workspace_ids)))
        for ws in ws_result.scalars().all():
            workspace_names[ws.id] = ws.name

    items = []
    for c in candidates:
        data = CandidateMemoryRead.model_validate(c)
        data.workspace_name = workspace_names.get(c.workspace_id)
        items.append(data)

    return PaginatedResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{candidate_id}", response_model=CandidateMemoryRead)
async def get_candidate(
    candidate_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> CandidateMemoryRead:
    """按 ID 获取候选记忆。"""
    candidate = await get_or_404(db, CandidateMemory, candidate_id)
    return CandidateMemoryRead.model_validate(candidate)


RESTORABLE_STATUSES = {"quarantined", "rejected", "deferred", "discarded", "needs_enrichment"}


@router.post("/{candidate_id}/restore", response_model=CandidateMemoryRead)
async def restore_candidate(
    candidate_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("reviews:write"))] = None,
) -> CandidateMemoryRead:
    """把隔离/拒绝/暂缓/待补全的候选恢复为待人工审核。"""
    candidate = await get_or_404(db, CandidateMemory, candidate_id)
    if candidate.status not in RESTORABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Candidate in '{candidate.status}' status cannot be restored",
        )
    candidate.status = "pending_review"
    await db.commit()
    await db.refresh(candidate)

    from apps.api.routes.memory_status import invalidate_memory_status_caches

    invalidate_memory_status_caches()
    return CandidateMemoryRead.model_validate(candidate)


@router.post("/{candidate_id}/revert-auto-approve", response_model=CandidateMemoryRead)
async def revert_auto_approve(
    candidate_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    reviewer_id: str | None = Query(None, max_length=128),
    reason: str | None = Query(None, max_length=500),
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("reviews:write"))] = None,
) -> CandidateMemoryRead:
    """撤销自动生效：物理删除生成的正式记忆，候选回到 pending_review。

    生成的记忆 ID 记录在 auto_approve Review 的 reason JSON 中；
    删除后不可恢复，候选重新进入审核队列，可再次编辑/批准。
    """
    import json as _json

    from packages.domain.models.memory import Memory, Review

    candidate = await get_or_404(db, CandidateMemory, candidate_id)
    auto_review_stmt = (
        select(Review)
        .where(
            Review.candidate_id == candidate_id,
            Review.action == "auto_approve",
            Review.reviewer_type == "system",
        )
        .order_by(Review.created_at.desc())
    )
    auto_review = (await db.execute(auto_review_stmt)).scalars().first()
    if auto_review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No auto_approve review found for this candidate",
        )
    try:
        reason_data = _json.loads(auto_review.reason or "{}")
        memory_id = reason_data.get("memory_id")
        expected_version = reason_data.get("memory_version")
    except (TypeError, ValueError):
        memory_id = None
        expected_version = None
    if not memory_id or not isinstance(expected_version, int):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Auto-approve review is missing the creation version; memory was preserved",
        )

    memory = await get_or_404(db, Memory, uuid.UUID(memory_id))
    if memory.status != "active" or memory.version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Memory changed after auto-approve; revert was not applied. "
                "The memory, version, and evidence were preserved."
            ),
        )

    from apps.api.file_sync import (
        delete_memory_assets,
        resolve_workspace_name,
    )
    from apps.api.routes.context import invalidate_context_cache
    from apps.api.routes.memory_status import invalidate_memory_status_caches
    from apps.api.routes.search import invalidate_search_cache

    workspace_name = await resolve_workspace_name(db, memory.workspace_id)
    memory_type = memory.type
    title = memory.title
    memory_uuid = memory.id

    # Guard the deletion itself: a concurrent update wins if it changes the
    # version after the read above, leaving the memory and its evidence intact.
    delete_result = await db.execute(
        delete(Memory)
        .where(
            Memory.id == memory_uuid,
            Memory.status == "active",
            Memory.version == expected_version,
        )
        .returning(Memory.id)
    )
    if delete_result.scalar_one_or_none() is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Memory changed concurrently; revert was not applied. "
                "The memory, version, and evidence were preserved."
            ),
        )

    db.add(
        Review(
            candidate_id=candidate_id,
            reviewer_type="human",
            reviewer_id=reviewer_id,
            action="revert_auto_approve",
            reason=reason,
        )
    )
    # 候选回到待审，允许重新编辑/批准；否则 approved 是终态，撤销后无法再次生成
    candidate.status = "pending_review"
    await db.commit()

    await delete_memory_assets(memory_uuid, workspace_name, memory_type, title)
    logger.info("Auto-approve reverted: memory %s deleted", memory_uuid)
    invalidate_search_cache()
    invalidate_context_cache()
    invalidate_memory_status_caches(str(memory_uuid))

    await db.refresh(candidate)
    return CandidateMemoryRead.model_validate(candidate)
