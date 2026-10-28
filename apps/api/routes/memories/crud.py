"""记忆 CRUD 端点（list / get / patch / optimize / lifecycle）。"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

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
from apps.api.file_sync import sync_memory_to_file
from apps.api.routes.context import invalidate_context_cache
from apps.api.routes.memories._router import router
from apps.api.routes.memories._shared import _MEMORY_NO_EMBED, _latest_usage_map
from apps.api.routes.memory_status import invalidate_memory_status_caches
from apps.api.routes.search import invalidate_search_cache
from packages.domain.database import async_session_maker
from packages.domain.models import (
    Evidence,
    Memory,
    MemoryLifecycleEvent,
    MemoryVersion,
)
from packages.domain.schemas import (
    EvidenceRead,
    MemoryRead,
    MemoryStatus,
    MemoryType,
    MemoryUpdate,
    MemoryVersionRead,
    PaginatedResponse,
)
from packages.domain.task_queue import queue as task_queue
from packages.memory.service import snapshot_and_advance
from packages.memory.tag_query import memory_has_tag
from packages.memory.utility_aggregation import aggregate_utility_scores, latest_used_at
from packages.retrieval.optimizer import optimize_memory

logger = logging.getLogger(__name__)


@router.get("", response_model=PaginatedResponse)
async def list_memories(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    memory_type: MemoryType | None = Query(None, alias="type"),
    memory_status: MemoryStatus | None = Query(None, alias="status"),
    project_id: uuid.UUID | None = Query(None),
    tags: str | None = Query(None, description="按标签过滤，逗号分隔（AND 逻辑）"),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    max_confidence: float | None = Query(None, ge=0.0, le=1.0),
    min_importance: float | None = Query(None, ge=0.0, le=1.0),
    max_importance: float | None = Query(None, ge=0.0, le=1.0),
    usage: str | None = Query(
        None, pattern="^(unused|low|medium|high)$", description="使用频率分箱过滤"
    ),
    decay: str | None = Query(
        None, pattern="^(fresh|aging|stale)$", description="衰减分箱过滤（最后使用或创建时间）"
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[MemoryRead]:
    """列出已验证记忆，支持可选过滤。"""
    stmt = select(Memory).options(defer(Memory.embedding))
    count_stmt = select(func.count(Memory.id))

    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    conditions = []
    if resolved_ws_id:
        conditions.append(Memory.workspace_id == resolved_ws_id)
    if memory_type:
        conditions.append(Memory.type == memory_type)
    if memory_status:
        conditions.append(Memory.status == memory_status)
    if project_id:
        conditions.append(Memory.project_id == project_id)
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        for tag in tag_list:
            conditions.append(memory_has_tag(tag))
    if min_confidence is not None:
        conditions.append(Memory.confidence >= min_confidence)
    if max_confidence is not None:
        conditions.append(Memory.confidence <= max_confidence)
    if min_importance is not None:
        conditions.append(Memory.importance >= min_importance)
    if max_importance is not None:
        conditions.append(Memory.importance <= max_importance)
    if usage == "unused":
        conditions.append(Memory.usage_count == 0)
    elif usage == "low":
        conditions.append(and_(Memory.usage_count >= 1, Memory.usage_count < 5))
    elif usage == "medium":
        conditions.append(and_(Memory.usage_count >= 5, Memory.usage_count < 20))
    elif usage == "high":
        conditions.append(Memory.usage_count >= 20)
    if decay is not None:
        # 与质量分布口径一致：从未使用过的按创建时间计
        anchor = func.coalesce(Memory.last_used_at, Memory.created_at)
        age_days = func.julianday("now") - func.julianday(anchor)
        if decay == "fresh":
            conditions.append(age_days < 30)
        elif decay == "aging":
            conditions.append(and_(age_days >= 30, age_days < 90))
        else:
            conditions.append(age_days >= 90)
    stmt, count_stmt = apply_optional_filters(stmt, count_stmt, conditions)

    total, memories = await execute_paginated(
        db, stmt, count_stmt, Memory.updated_at.desc(), offset, limit
    )

    # 效用分只对当前页现场计算（分页 10-50 条，三条 GROUP BY 成本可控），
    # 与检索引擎共用同一聚合实现保证口径一致；聚合异常返回空映射，
    # 此时所有条目 utility_score 为 null（未算过）而非 0
    utility_map = await aggregate_utility_scores(db, memories)

    # last_used_at 口径：memory.last_used_at 列只在导入/重建时落值，
    # 运行期检索命中只写 memory_usage 流水，故取两者较新者；
    # 两处都没有（从未被命中且无历史值）则为 null
    usage_max_map = await _latest_usage_map(db, memories)

    items: list[MemoryRead] = []
    for m in memories:
        item = MemoryRead.model_validate(m)
        item.utility_score = utility_map.get(str(m.id))
        item.last_used_at = latest_used_at(m.last_used_at, usage_max_map.get(m.id))
        items.append(item)

    return PaginatedResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{memory_id}")
async def get_memory(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """获取记忆及其版本与证据。"""
    memory = await get_or_404(db, Memory, memory_id, options=_MEMORY_NO_EMBED)

    async def _fetch_evidence() -> list[Any]:
        async with async_session_maker() as evidence_session:
            result = await evidence_session.execute(
                select(Evidence).where(Evidence.memory_id == memory_id).limit(100)
            )
            return list(result.scalars().all())

    versions_result, evidence_list = await asyncio.gather(
        db.execute(
            select(MemoryVersion)
            .where(MemoryVersion.memory_id == memory_id)
            .order_by(MemoryVersion.version.desc())
            .limit(50)
        ),
        _fetch_evidence(),
    )
    versions = versions_result.scalars().all()

    return {
        "memory": MemoryRead.model_validate(memory),
        "versions": [MemoryVersionRead.model_validate(v) for v in versions],
        "evidence": [EvidenceRead.model_validate(e) for e in evidence_list],
    }


@router.patch("/{memory_id}", response_model=MemoryRead)
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("reviews:write"))] = None,
) -> MemoryRead:
    """更新记忆——产生新版本。"""
    # 此处必须加载 embedding：sync_memory_to_file 与恢复路径都要读它，
    # 延迟加载列在异步上下文中会惰性抛错。
    memory = await get_or_404(db, Memory, memory_id)

    from packages.domain.config import parasitic_evolution_config

    await snapshot_and_advance(
        db,
        memory,
        change_type="edit",
        changed_by_type="agent",
        changed_by_id=getattr(_identity, "agent_id", None),
        reason=body.change_summary or body.reason,
        expected_version=body.expected_version,
        record_version=parasitic_evolution_config.memory_version_tracking_enabled,
    )

    old_status = memory.status
    if body.title is not None:
        memory.title = body.title
    if body.content is not None:
        from packages.domain.text_utils import normalize_memory_content

        memory.content = normalize_memory_content(body.content)
    if body.status is not None:
        # Epic 4: 状态转换合法性校验
        from packages.memory.lifecycle import validate_memory_status_transition

        validate_memory_status_transition(memory.status, body.status)
        memory.status = body.status
    if body.confidence is not None:
        memory.confidence = body.confidence
    if body.importance is not None:
        memory.importance = body.importance
    if body.tags is not None:
        from packages.memory.service import normalize_tags

        memory.tags = normalize_tags(body.tags)
    if body.is_permanent is not None:
        memory.is_permanent = body.is_permanent
        memory.permanent_reason = body.permanent_reason

    rebuild_embedding = body.title is not None or body.content is not None
    if rebuild_embedding:
        # 置空 embedding 即"待生成"标记，由启动扫描/队列恢复
        memory.embedding = None

    if body.status is not None and body.status != old_status:
        # 归档单独记 event_type=archived，供演化指标统计（status_changed 不细分目标状态）
        lifecycle_event = MemoryLifecycleEvent(
            id=uuid.uuid4(),
            memory_id=memory_id,
            event_type="archived" if body.status == "archived" else "status_changed",
            metadata_json=json.dumps({"old_status": old_status, "new_status": body.status}),
        )
    else:
        lifecycle_event = MemoryLifecycleEvent(
            id=uuid.uuid4(),
            memory_id=memory_id,
            event_type="updated",
        )
    db.add(lifecycle_event)

    await db.commit()
    await db.refresh(memory)
    response = MemoryRead.model_validate(memory)

    status_left_active = old_status == "active" and memory.status != "active"
    status_restored_active = old_status != "active" and memory.status == "active"
    if status_restored_active and memory.embedding is not None:
        # 恢复激活：重新注入向量并立即持久化索引
        await sync_memory_to_file(memory, db, embedding=memory.embedding, save_index=True)
    elif status_left_active:
        # 非激活记忆把向量从内存和磁盘一并移除
        await sync_memory_to_file(memory, db, skip_vector_index=True, save_index=True)
    else:
        await sync_memory_to_file(memory, db, skip_vector_index=True)

    # 尽力而为：缺失的向量由下次启动扫描恢复
    if memory.status == "active" and memory.embedding is None:
        try:
            await task_queue.enqueue("generate_embedding", str(memory_id))
        except Exception:
            logger.warning(
                "Embedding enqueue failed for memory %s; startup will recover it",
                memory_id,
                exc_info=True,
            )

    invalidate_search_cache()
    invalidate_context_cache()
    invalidate_memory_status_caches(str(memory_id))

    return response


@router.post("/{memory_id}/optimize")
async def optimize_memory_endpoint(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("reviews:write"))] = None,
) -> dict[str, Any]:
    """用 LLM 生成记忆优化建议（仅预览，不落库）。"""
    memory = await get_or_404(db, Memory, memory_id, options=_MEMORY_NO_EMBED)

    optimized = await optimize_memory(
        title=memory.title,
        content=memory.content,
        memory_type=memory.type,
    )
    if optimized is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM optimization unavailable (check OPENAI_API_KEY)",
        )

    return {
        "original_title": memory.title,
        "original_content": memory.content,
        "optimized_title": optimized.title,
        "optimized_content": optimized.content,
        "changes": optimized.changes,
    }


@router.get("/{memory_id}/lifecycle")
async def get_memory_lifecycle(
    memory_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    try:
        uid = uuid.UUID(memory_id)
    except ValueError:
        return {
            "memory_id": memory_id,
            "current_status": "unknown",
            "timeline": [],
            "age_days": None,
            "event_count": 0,
        }

    memory = await db.get(Memory, uid, options=_MEMORY_NO_EMBED)
    if memory is None:
        return {
            "memory_id": memory_id,
            "current_status": "unknown",
            "timeline": [],
            "age_days": None,
            "event_count": 0,
        }

    # 尽力而为：生命周期时间线属补充信息，失败不阻断响应
    try:
        result = await db.execute(
            select(MemoryLifecycleEvent)
            .where(MemoryLifecycleEvent.memory_id == uid)
            .order_by(MemoryLifecycleEvent.created_at.asc())
            .limit(100)
        )
        events = result.scalars().all()
    except Exception:
        logger.warning("Failed to load lifecycle events for memory %s", uid, exc_info=True)
        events = []

    timeline = []
    for e in events:
        metadata = None
        if e.metadata_json:
            try:
                metadata = json.loads(e.metadata_json)
            except (json.JSONDecodeError, TypeError):
                metadata = None
        timeline.append(
            {
                "event_type": e.event_type,
                "timestamp": e.created_at.isoformat() if e.created_at else None,
                "metadata": metadata,
            }
        )

    current_status = memory.status
    age_days = None
    if memory.created_at:
        created_at = memory.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        age_days = (datetime.now(UTC) - created_at).days

    return {
        "memory_id": memory_id,
        "current_status": current_status,
        "timeline": timeline,
        "age_days": age_days,
        "event_count": len(events),
    }
