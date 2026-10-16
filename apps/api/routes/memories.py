"""已验证记忆端点。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, noload

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
from apps.api.routes.memory_status import invalidate_memory_status_caches
from apps.api.routes.search import invalidate_search_cache
from packages.domain.config import API_V1_PREFIX, settings
from packages.domain.database import async_session_maker
from packages.domain.models import (
    Evidence,
    Memory,
    MemoryFeedback,
    MemoryLifecycleEvent,
    MemoryRelation,
    MemoryUsage,
    MemoryVersion,
    RetrievalTrace,
    RetrievalTraceItem,
)
from packages.domain.schemas import (
    EvidenceRead,
    MemoryFeedbackListResponse,
    MemoryFeedbackRead,
    MemoryRead,
    MemoryRetrievalHistory,
    MemoryRetrievalHit,
    MemoryStatus,
    MemoryType,
    MemoryUpdate,
    MemoryVersionRead,
    PaginatedResponse,
)
from packages.domain.schemas.memory import MemoryContent
from packages.domain.task_queue import queue as task_queue
from packages.domain.text_utils import format_memory_for_embedding
from packages.memory.service import snapshot_and_advance
from packages.memory.similarity import jaccard_similarity
from packages.memory.utility_aggregation import aggregate_utility_scores, latest_used_at
from packages.retrieval.optimizer import optimize_memory

logger = logging.getLogger(__name__)

# 合并建议的 TTL 缓存（计算开销大）
_merge_suggestions_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_MERGE_SUGGESTIONS_CACHE_TTL = 300.0  # 5 分钟


def invalidate_merge_suggestions_cache(workspace_id: str) -> None:
    """使指定工作区的合并建议缓存失效。"""
    _merge_suggestions_cache.pop(workspace_id, None)


router = APIRouter(prefix=f"{API_V1_PREFIX}/memories", tags=["memories"])

_MEMORY_NO_EMBED = (defer(Memory.embedding),)


@router.get("/merge-suggestions")
async def get_merge_suggestions(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    limit: int = Query(10, ge=1, le=50),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """基于相似度建议可合并的记忆对。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)

    # 先查缓存
    cache_key = f"{resolved_ws_id}:{limit}"
    now = time.monotonic()
    if cache_key in _merge_suggestions_cache:
        cached_time, cached_data = _merge_suggestions_cache[cache_key]
        if now - cached_time < _MERGE_SUGGESTIONS_CACHE_TTL:
            return cached_data

    rel_stmt = (
        select(MemoryRelation)
        .join(Memory, Memory.id == MemoryRelation.source_memory_id)
        .where(
            Memory.workspace_id == resolved_ws_id,
            Memory.status == "active",
            MemoryRelation.confidence >= 0.6,
        )
        .order_by(MemoryRelation.confidence.desc())
        .limit(limit * 2)
    )
    rel_result = await db.execute(rel_stmt)
    relations = rel_result.scalars().all()

    all_memory_ids: set[uuid.UUID] = set()
    for rel in relations:
        all_memory_ids.add(rel.source_memory_id)
        all_memory_ids.add(rel.target_memory_id)

    mem_map: dict[str, Memory] = {}
    if all_memory_ids:
        mem_stmt = select(Memory).where(Memory.id.in_(list(all_memory_ids)))
        mem_result = await db.execute(mem_stmt)
        mem_map = {str(m.id): m for m in mem_result.scalars().all()}

    seen_pairs: set[tuple[str, str]] = set()
    suggestions: list[dict[str, Any]] = []

    for rel in relations:
        ids = sorted([str(rel.source_memory_id), str(rel.target_memory_id)])
        pair = (ids[0], ids[1])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        if len(suggestions) >= limit:
            break

        src_id = rel.source_memory_id
        tgt_id = rel.target_memory_id
        src_mem = mem_map.get(str(src_id))
        tgt_mem = mem_map.get(str(tgt_id))
        if not src_mem or not tgt_mem:
            continue

        suggestions.append(
            {
                "source_id": str(src_id),
                "source_title": src_mem.title,
                "source_content_preview": src_mem.content[:200],
                "target_id": str(tgt_id),
                "target_title": tgt_mem.title,
                "target_content_preview": tgt_mem.content[:200],
                "similarity": round(rel.confidence, 3),
                "relation_type": rel.relation_type,
            }
        )

    if len(suggestions) < limit:
        stmt = (
            select(Memory.id, Memory.title, Memory.content)
            .where(Memory.workspace_id == resolved_ws_id, Memory.status == "active")
            .limit(settings.merge_suggestions_limit)
        )
        result = await db.execute(stmt)
        all_memories = result.all()

        existing_ids = set()
        for s in suggestions:
            existing_ids.add(s["source_id"])
            existing_ids.add(s["target_id"])

        uncovered = [(mid, t, c) for mid, t, c in all_memories if str(mid) not in existing_ids]

        if uncovered:
            from packages.retrieval.engine import get_retrieval_engine

            # 复用检索引擎的 BM25 缓存索引，避免现场重建
            engine = get_retrieval_engine()
            bm25 = await engine.get_bm25_index(db, resolved_ws_id)

            id_to_idx: dict[str, int] = {}
            for idx, (mid, title, content) in enumerate(uncovered):
                doc_id = str(mid)
                id_to_idx[doc_id] = idx

            # 第一趟：BM25 预过滤，收集范围外命中的额外 ID
            bm25_candidates: dict[str, list[str]] = {}
            extra_ids: set[str] = set()
            for mid, title, content in uncovered:
                doc_id = str(mid)
                candidates = bm25.search(
                    format_memory_for_embedding(title, content),
                    top_k=settings.merge_suggestions_top_k,
                )
                valid = [oid for oid, _ in candidates if oid != doc_id]
                bm25_candidates[doc_id] = valid
                for oid in valid:
                    if oid not in id_to_idx:
                        extra_ids.add(oid)

            # 批量加载 uncovered 集合之外的 BM25 命中数据
            extra_data: dict[str, tuple[str, str]] = {}
            if extra_ids:
                extra_uuids = [uuid.UUID(mid) for mid in extra_ids]
                extra_stmt = select(Memory.id, Memory.title, Memory.content).where(
                    Memory.id.in_(extra_uuids)
                )
                extra_result = await db.execute(extra_stmt)
                for row in extra_result.all():
                    extra_data[str(row.id)] = (row.title, row.content)

            seen_pairs_inner: set[tuple[str, str]] = set()
            for mid, title, content in uncovered:
                if len(suggestions) >= limit:
                    break
                doc_id = str(mid)
                for other_id in bm25_candidates[doc_id]:
                    if len(suggestions) >= limit:
                        break
                    pair_key = (min(doc_id, other_id), max(doc_id, other_id))
                    if pair_key in seen_pairs_inner:
                        continue
                    seen_pairs_inner.add(pair_key)

                    other_idx = id_to_idx.get(other_id)
                    if other_idx is not None:
                        _other_mid, other_title, other_content = uncovered[other_idx]
                    elif other_id in extra_data:
                        other_title, other_content = extra_data[other_id]
                    else:
                        continue

                    sim = jaccard_similarity(
                        format_memory_for_embedding(title, content),
                        format_memory_for_embedding(other_title, other_content),
                    )
                    if sim > settings.merge_suggestions_threshold:
                        suggestions.append(
                            {
                                "source_id": doc_id,
                                "source_title": title,
                                "source_content_preview": content[:200],
                                "target_id": other_id,
                                "target_title": other_title,
                                "target_content_preview": other_content[:200],
                                "similarity": round(sim, 3),
                                "relation_type": "related",
                            }
                        )

    # 读取 worker 生成的整理建议时间戳
    generated_at: str | None = None
    try:
        from pathlib import Path as _Path

        suggestions_path = _Path.home() / ".cwiki" / "state" / "consolidation_suggestions.json"
        if suggestions_path.exists():
            data = json.loads(await asyncio.to_thread(suggestions_path.read_text, encoding="utf-8"))
            generated_at = data.get("generated_at")
    except (OSError, json.JSONDecodeError, ValueError):
        logger.warning("Failed to load consolidation suggestions", exc_info=True)

    response: dict[str, Any] = {
        "items": suggestions,
        "total": len(suggestions),
        "generated_at": generated_at,
    }

    # 写入缓存
    _merge_suggestions_cache[cache_key] = (time.monotonic(), response)

    return response


@router.get("/merge-suggestions/embedding")
async def get_merge_suggestions_embedding(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    limit: int = Query(10, ge=1, le=50),
    similarity_threshold: float = Query(0.85, ge=0.0, le=1.0, description="最小余弦相似度"),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """基于 embedding 余弦相似度建议可合并的记忆对。

    用语义相似度（向量）发现措辞不同但可能可合并的记忆。
    """
    from packages.memory.merge_suggestions import find_merge_candidates

    resolved_ws_id = await resolve_workspace(workspace_id, db)

    suggestions = await find_merge_candidates(
        db,
        workspace_id=resolved_ws_id,
        similarity_threshold=similarity_threshold,
        limit=limit,
    )

    return {
        "items": [s.to_dict() for s in suggestions],
        "total": len(suggestions),
        "similarity_threshold": similarity_threshold,
        "method": "embedding_cosine",
    }


@router.post("/consolidate")
async def trigger_consolidate(
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """触发自动整理分析以发现相似记忆。

    入队 auto_consolidate_similar 任务后立即返回；
    结果稍后可通过 GET /merge-suggestions 查看。
    """
    from packages.domain.config import parasitic_evolution_config

    if not parasitic_evolution_config.auto_consolidate_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auto-consolidation is disabled. Enable it in config.yaml first.",
        )

    await task_queue.enqueue("auto_consolidate_similar", {})

    return {
        "status": "enqueued",
        "message": "Consolidation analysis started. Results will be available shortly.",
    }


class MergeRequest(BaseModel):
    source_memory_id: uuid.UUID
    target_memory_id: uuid.UUID
    merged_content: MemoryContent

    def model_post_init(self, __context: Any, /) -> None:
        if self.source_memory_id == self.target_memory_id:
            raise ValueError("Cannot merge a memory with itself")


@router.post("/merge")
async def merge_memories_post(
    body: MergeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("reviews:write"))] = None,
) -> dict[str, Any]:
    """把 source 记忆合并进 target，并归档 source（可恢复、留痕）。"""
    source = await get_or_404(
        db,
        Memory,
        body.source_memory_id,
        detail=f"Source memory {body.source_memory_id} not found",
        options=_MEMORY_NO_EMBED,
    )
    target = await get_or_404(
        db,
        Memory,
        body.target_memory_id,
        detail=f"Target memory {body.target_memory_id} not found",
        options=_MEMORY_NO_EMBED,
    )

    if source.workspace_id != target.workspace_id:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot merge across workspaces: source={source.workspace_id}, target={target.workspace_id}",
        )

    await snapshot_and_advance(
        db,
        target,
        change_type="merge",
        changed_by_type="human",
        reason=f"Merged from memory {source.id}",
    )
    target.content = body.merged_content
    target.embedding = None

    lifecycle_event = MemoryLifecycleEvent(
        id=uuid.uuid4(),
        memory_id=source.id,
        event_type="merged",
    )
    db.add(lifecycle_event)

    rel = MemoryRelation(
        id=uuid.uuid4(),
        source_memory_id=target.id,
        target_memory_id=source.id,
        relation_type="supersedes",
        confidence=1.0,
    )
    db.add(rel)

    source_id = source.id
    # 归档而非物理删除：保留追溯与恢复能力（与 worker auto_merge 路径一致）
    source.status = "archived"
    await db.commit()
    await db.refresh(target)
    await db.refresh(source)

    # 逐条收敛文件镜像：target 写新内容，source 写归档状态并从向量索引移除；
    # 失败由启动扫描与队列重试兜底
    for memory in (target, source):
        await sync_memory_to_file(memory, db, skip_vector_index=True, save_index=True)
    # 尽力而为：向量化失败可在下次启动时恢复；source 已有 embedding，任务只会移除其向量
    try:
        await task_queue.enqueue("generate_embedding", str(target.id))
        await task_queue.enqueue("generate_embedding", str(source_id))
    except Exception:
        logger.warning("Embedding enqueue failed for merged memory %s", target.id, exc_info=True)

    invalidate_search_cache()
    invalidate_context_cache()
    invalidate_memory_status_caches()

    return {
        "merged_memory_id": str(target.id),
        "archived_memory_id": str(source_id),
    }


async def _latest_usage_map(
    db: AsyncSession,
    memories: Sequence[Memory],
) -> dict[uuid.UUID, datetime]:
    """按 memory_id 批量取 memory_usage 流水里最近一次命中的时间。

    与效用聚合同思路：只查当前页的 id（分页 10-50 条），一次 GROUP BY
    避免逐条发查询。
    """
    ids = [m.id for m in memories]
    if not ids:
        return {}
    result = await db.execute(
        select(MemoryUsage.memory_id, func.max(MemoryUsage.created_at))
        .where(MemoryUsage.memory_id.in_(ids))
        .group_by(MemoryUsage.memory_id)
    )
    return {row[0]: row[1] for row in result.all()}


@router.get("", response_model=PaginatedResponse)
async def list_memories(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    memory_type: MemoryType | None = Query(None, alias="type"),
    memory_status: MemoryStatus | None = Query(None, alias="status"),
    project_id: uuid.UUID | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[MemoryRead]:
    """列出已验证记忆，支持可选过滤。"""
    stmt = select(Memory).options(
        defer(Memory.embedding),
        noload(Memory.versions),
        noload(Memory.evidences),
    )
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
    if body.is_permanent is not None:
        memory.is_permanent = body.is_permanent
        memory.permanent_reason = body.permanent_reason

    rebuild_embedding = body.title is not None or body.content is not None
    if rebuild_embedding:
        # 置空 embedding 即"待生成"标记，由启动扫描/队列恢复
        memory.embedding = None

    if body.status is not None and body.status != old_status:
        lifecycle_event = MemoryLifecycleEvent(
            id=uuid.uuid4(),
            memory_id=memory_id,
            event_type="status_changed",
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
