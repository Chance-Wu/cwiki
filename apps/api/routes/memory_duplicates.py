"""记忆库内整理：查重（找出近似重复）与合并（把一条并入另一条）。

查重面向「日常写入累积出近似重复」的场景，与写入时的候选查重互补：
那里是候选对全库，这里是全库记忆两两比较，结果只作建议。确认后调用
``POST /v1/memories/merge`` 完成合并，来源记忆保留为 superseded 以便回溯。
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db
from apps.api.file_sync import sync_memory_to_file
from apps.api.routes.context import invalidate_context_cache
from apps.api.routes.search import invalidate_search_cache
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import Memory
from packages.domain.task_queue import queue as task_queue
from packages.memory.duplicate_scan import DEFAULT_MAX_SCAN, find_duplicate_pairs
from packages.memory.merge import merge_memories

# 独立 router：与 memories 包的共享 router 分开，否则同一 router 被
# include 两次会让 /v1/memories 下所有端点重复注册
router = APIRouter(prefix=f"{API_V1_PREFIX}/memories", tags=["memories"])

logger = logging.getLogger(__name__)


@router.get("/duplicates")
async def find_duplicate_memories(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: uuid.UUID | None = Query(None, description="只扫该工作区，缺省为全部"),
    min_similarity: float = Query(0.6, ge=0.0, le=1.0, description="融合相似度下限"),
    limit: int = Query(20, ge=1, le=200),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """返回相似度达到阈值的记忆对，按相似度降序。

    融合标题/正文/关键词/embedding 四路信号，与写入时的候选查重同口径；
    某条记忆缺向量时该路按 0 计，判定退化为纯文本，分数会偏低。
    """
    result = await find_duplicate_pairs(
        db,
        workspace_id=workspace_id,
        min_similarity=min_similarity,
        limit=limit,
    )
    if result["truncated"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"active 记忆超过两两比较上限 {DEFAULT_MAX_SCAN} 条，"
                "请用 workspace_id 收窄范围后再查"
            ),
        )
    return result


class MemoryMergeRequest(BaseModel):
    """合并请求：来源并入目标。"""

    source_id: uuid.UUID = Field(description="被合并的记忆（将标记为 superseded）")
    target_id: uuid.UUID = Field(description="保留的记忆")
    merge_content: bool = Field(
        default=False,
        description="是否把来源正文追加到目标末尾（默认不动目标正文）",
    )


@router.post("/merge")
async def merge_memory_pair(
    body: MemoryMergeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """把一条记忆并入另一条：标签取并集、关系与证据改挂、来源标记 superseded。"""
    try:
        result = await merge_memories(
            db,
            source_id=body.source_id,
            target_id=body.target_id,
            merge_content=body.merge_content,
        )
    except ValueError as exc:
        status_code = 404 if str(exc) == "记忆不存在" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    await db.commit()
    for memory_id in (body.target_id, body.source_id):
        memory = (await db.execute(select(Memory).where(Memory.id == memory_id))).scalar_one()
        await sync_memory_to_file(memory, db, skip_vector_index=True, save_index=True)
    if body.merge_content:
        try:
            await task_queue.enqueue("generate_embedding", str(body.target_id))
        except Exception:
            # 入队失败不致命：启动扫描会补生成缺失向量
            logger.warning("Embedding enqueue failed after merge", exc_info=True)
    invalidate_search_cache()
    invalidate_context_cache()
    return result
