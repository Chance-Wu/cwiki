"""记忆合并建议——自动发现相似记忆对。

扫描 active 记忆，找出 embedding 相似度较高、可能适合合并的记忆对。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Memory
from packages.retrieval.vector_utils import batch_cosine_similarities

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
    """找出 embedding 相似度较高的 active 记忆对。

    Args:
        db: 数据库会话
        workspace_id: 要扫描的 workspace
        similarity_threshold: 最小余弦相似度（0.0-1.0）
        limit: 返回建议的最大数量

    Returns:
        MergeSuggestion 列表，按相似度降序排列
    """
    # 只扫最近更新的 500 条，控制两两比较的开销
    stmt = (
        select(Memory.id, Memory.title, Memory.content, Memory.embedding)
        .where(
            Memory.workspace_id == workspace_id,
            Memory.status == "active",
            Memory.embedding.isnot(None),
        )
        .order_by(Memory.updated_at.desc())
        .limit(500)
    )
    result = await db.execute(stmt)
    memories = result.all()

    if len(memories) < 2:
        return []

    memory_ids: list[str] = []
    memory_titles: list[str] = []
    memory_embeddings: list[list[float]] = []

    for mem_id, title, _content, emb in memories:
        if emb is not None and len(emb) > 0:
            memory_ids.append(str(mem_id))
            memory_titles.append(title)
            memory_embeddings.append(emb)

    if len(memory_embeddings) < 2:
        return []

    # 计算两两相似度
    suggestions: list[MergeSuggestion] = []
    n = len(memory_embeddings)

    # 只比较 i < j 的对，避免重复计算
    for i in range(n):
        # 一次性算出记忆 i 与其后所有 j > i 的相似度（批量内积）
        query_emb = memory_embeddings[i]
        compare_embs = memory_embeddings[i + 1 :]

        if not compare_embs:
            continue

        similarities = batch_cosine_similarities(query_emb, compare_embs)

        for j, sim in enumerate(similarities):
            if sim >= similarity_threshold:
                idx_j = i + 1 + j
                suggestions.append(
                    MergeSuggestion(
                        memory_id_a=memory_ids[i],
                        memory_id_b=memory_ids[idx_j],
                        title_a=memory_titles[i],
                        title_b=memory_titles[idx_j],
                        similarity=float(sim),
                        reason=f"High semantic similarity ({sim:.2%})",
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
