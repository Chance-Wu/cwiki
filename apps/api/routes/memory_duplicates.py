"""记忆库内重复检测端点：找出高度相似却尚未合并的 active 记忆对。

面向「日常写入累积出近似重复」的场景，与写入时的候选查重互补：
那里是候选对全库，这里是全库记忆两两比较，结果只作建议，不自动合并。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db
from packages.domain.config import API_V1_PREFIX
from packages.memory.duplicate_scan import DEFAULT_MAX_SCAN, find_duplicate_pairs

# 独立 router：与 memories 包的共享 router 分开，否则同一 router 被
# include 两次会让 /v1/memories 下所有端点重复注册
router = APIRouter(prefix=f"{API_V1_PREFIX}/memories", tags=["memories"])


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
