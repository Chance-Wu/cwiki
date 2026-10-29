"""记忆合并相关端点（merge-suggestions / consolidate / merge）。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, get_or_404, require_scope, resolve_workspace
from apps.api.file_sync import sync_memory_to_file
from apps.api.routes.context import invalidate_context_cache
from apps.api.routes.memories._router import router
from apps.api.routes.memories._shared import (
    _MEMORY_NO_EMBED,
    _MERGE_SUGGESTIONS_CACHE_TTL,
    _merge_suggestions_cache,
)
from apps.api.routes.memory_status import invalidate_memory_status_caches
from apps.api.routes.search import invalidate_search_cache
from packages.domain.config import settings
from packages.domain.models import Memory, MemoryLifecycleEvent, MemoryRelation
from packages.domain.schemas.memory import MemoryContent
from packages.domain.task_queue import queue as task_queue
from packages.memory.service import snapshot_and_advance, union_tags

logger = logging.getLogger(__name__)


@router.get("/merge-suggestions")
async def get_merge_suggestions(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    limit: int = Query(10, ge=1, le=50),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """基于统一相似度策略建议可合并的记忆对。

    使用 config.yaml 的 memory.similarity_strategy 配置（jaccard/embedding/hybrid）。
    """
    from packages.memory.merge_suggestions import find_merge_candidates

    resolved_ws_id = await resolve_workspace(workspace_id, db)

    # 先查缓存
    cache_key = f"{resolved_ws_id}:{limit}:{settings.similarity_strategy}"
    now = time.monotonic()
    if cache_key in _merge_suggestions_cache:
        cached_time, cached_data = _merge_suggestions_cache[cache_key]
        if now - cached_time < _MERGE_SUGGESTIONS_CACHE_TTL:
            return cached_data

    # 使用统一的相似度计算
    suggestions = await find_merge_candidates(
        db,
        workspace_id=resolved_ws_id,
        similarity_threshold=settings.merge_suggestions_threshold,
        limit=limit,
    )

    # 转换为 API 响应格式
    items: list[dict[str, Any]] = []
    for s in suggestions:
        # 加载完整内容用于预览
        src_mem = await db.get(Memory, uuid.UUID(s.memory_id_a))
        tgt_mem = await db.get(Memory, uuid.UUID(s.memory_id_b))
        if not src_mem or not tgt_mem:
            continue

        items.append(
            {
                "source_id": s.memory_id_a,
                "source_title": s.title_a,
                "source_content_preview": src_mem.content[:200],
                "target_id": s.memory_id_b,
                "target_title": s.title_b,
                "target_content_preview": tgt_mem.content[:200],
                "similarity": round(s.similarity, 3),
                "relation_type": "similar",
                "strategy": settings.similarity_strategy,
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
        "items": items,
        "total": len(items),
        "generated_at": generated_at,
        "strategy": settings.similarity_strategy,
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
    """基于 embedding 余弦相似度建议可合并的记忆对（向后兼容端点）。

    推荐使用 GET /merge-suggestions，它使用统一的相似度策略。
    """
    from packages.memory.merge_suggestions import find_merge_candidates

    resolved_ws_id = await resolve_workspace(workspace_id, db)

    # 强制使用 embedding 策略（与统一端点区分）
    suggestions = await find_merge_candidates(
        db,
        workspace_id=resolved_ws_id,
        similarity_threshold=similarity_threshold,
        limit=limit,
        strategy="embedding",
    )

    return {
        "items": [s.to_dict() for s in suggestions],
        "total": len(suggestions),
        "similarity_threshold": similarity_threshold,
        "method": "embedding_cosine",
    }


class DismissSuggestionBody(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID
    workspace_id: str | None = None


@router.post("/merge-suggestions/dismiss")
async def dismiss_merge_suggestion(
    body: DismissSuggestionBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("reviews:write"))] = None,
) -> dict[str, Any]:
    """忽略一条合并建议：记录后不再出现在建议列表（只增不删）。"""
    from packages.memory.merge_suggestions import dismiss_pair

    resolved_ws_id = await resolve_workspace(body.workspace_id, db)
    await asyncio.to_thread(
        dismiss_pair, str(resolved_ws_id), str(body.source_id), str(body.target_id)
    )
    _merge_suggestions_cache.clear()
    return {"status": "ok"}


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

    await task_queue.enqueue("auto_consolidate_similar")

    return {
        "status": "enqueued",
        "message": "Consolidation analysis started. Results will be available shortly.",
    }


class MergeRequest(BaseModel):
    source_memory_id: uuid.UUID
    target_memory_id: uuid.UUID
    merged_content: MemoryContent
    similarity: float | None = None  # 合并时的相似度
    strategy: str | None = None  # 使用的相似度策略

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
    target.tags = union_tags(target.tags, source.tags)
    target.embedding = None

    # 创建生命周期事件，包含合并元数据
    import json

    metadata = {
        "source_id": str(source.id),
        "source_title": source.title,
        "target_id": str(target.id),
        "target_title": target.title,
    }
    if body.similarity is not None:
        metadata["similarity"] = body.similarity
    if body.strategy is not None:
        metadata["strategy"] = body.strategy

    # target 记录"接收合并"，source 记录"被合并归档"，两侧生命周期都可追溯
    for memory_id in (target.id, source.id):
        db.add(
            MemoryLifecycleEvent(
                id=uuid.uuid4(),
                memory_id=memory_id,
                event_type="merged",
                metadata_json=json.dumps(metadata, ensure_ascii=False),
            )
        )

    rel = MemoryRelation(
        id=uuid.uuid4(),
        source_memory_id=target.id,
        target_memory_id=source.id,
        relation_type="supersedes",
        confidence=1.0,
        created_by="merge",
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
