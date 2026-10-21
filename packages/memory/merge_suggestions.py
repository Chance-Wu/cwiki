"""记忆合并建议——自动发现相似记忆对。

扫描 active 记忆，找出相似度较高、可能适合合并的记忆对。
支持多种相似度策略：jaccard（词面）、embedding（语义）、hybrid（加权融合）。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.config import settings
from packages.domain.models import Memory
from packages.memory.similarity import HybridWeights, compute_similarity

logger = logging.getLogger(__name__)

# 余弦相似度阈值：建议最终由人工裁决，阈值取高以压低误报
DEFAULT_SIMILARITY_THRESHOLD = 0.85


@dataclass
class MergeSuggestion:
    memory_id_a: str
    memory_id_b: str
    title_a: str
    title_b: str
    similarity: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id_a": self.memory_id_a,
            "memory_id_b": self.memory_id_b,
            "title_a": self.title_a,
            "title_b": self.title_b,
            "similarity": round(self.similarity, 4),
            "reason": self.reason,
        }


async def find_merge_candidates(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    limit: int = 20,
) -> list[MergeSuggestion]:
    """找出相似度较高的 active 记忆对。

    使用统一相似度计算策略（配置在 config.yaml 的 memory.similarity_strategy）。
    为控制开销，只扫描最近更新的 500 条记忆。

    Args:
        db: 数据库会话
        workspace_id: 要扫描的 workspace
        similarity_threshold: 最小相似度（0.0-1.0）
        limit: 返回建议的最大数量

    Returns:
        MergeSuggestion 列表，按相似度降序排列
    """
    # 只扫最近更新的 500 条，控制两两比较的开销
    stmt = (
        select(
            Memory.id,
            Memory.title,
            Memory.content,
            Memory.embedding,
        )
        .where(
            Memory.workspace_id == workspace_id,
            Memory.status == "active",
        )
        .order_by(Memory.updated_at.desc())
        .limit(500)
    )
    result = await db.execute(stmt)
    memories = result.all()

    if len(memories) < 2:
        return []

    # 构建文本字典列表
    memory_items: list[dict[str, Any]] = []
    for mem_id, title, content, emb in memories:
        memory_items.append(
            {
                "id": str(mem_id),
                "title": title,
                "content": content,
                "embedding": emb,
            }
        )

    # 计算两两相似度
    suggestions: list[MergeSuggestion] = []
    n = len(memory_items)
    strategy = settings.similarity_strategy
    weights = HybridWeights(**settings.similarity_hybrid_weights)

    # 只比较 i < j 的对，避免重复计算
    for i in range(n):
        for j in range(i + 1, n):
            sim = await compute_similarity(
                memory_items[i],
                memory_items[j],
                strategy=strategy,
                weights=weights,
            )

            if sim >= similarity_threshold:
                suggestions.append(
                    MergeSuggestion(
                        memory_id_a=memory_items[i]["id"],
                        memory_id_b=memory_items[j]["id"],
                        title_a=memory_items[i]["title"],
                        title_b=memory_items[j]["title"],
                        similarity=float(sim),
                        reason=f"Similarity ({sim:.2%}, strategy={strategy})",
                    )
                )

    suggestions.sort(key=lambda s: s.similarity, reverse=True)
    return suggestions[:limit]


async def generate_merge_suggestions(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """为 workspace 生成合并建议。

    find_merge_candidates 的便捷封装，返回字典形式。
    """
    suggestions = await find_merge_candidates(
        db, workspace_id, similarity_threshold=DEFAULT_SIMILARITY_THRESHOLD, limit=limit
    )
    return [s.to_dict() for s in suggestions]
