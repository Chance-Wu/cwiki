"""memories 路由共享状态与辅助函数。"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from packages.domain.models import Memory, MemoryUsage

logger = logging.getLogger(__name__)

# 合并建议的 TTL 缓存（计算开销大）
_merge_suggestions_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_MERGE_SUGGESTIONS_CACHE_TTL = 300.0  # 5 分钟


def invalidate_merge_suggestions_cache(workspace_id: str) -> None:
    """使指定工作区的合并建议缓存失效。"""
    _merge_suggestions_cache.pop(workspace_id, None)


_MEMORY_NO_EMBED = (defer(Memory.embedding),)


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
