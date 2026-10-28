"""自动关系发现：基于向量相似度自动建立记忆间关系。"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Memory, MemoryRelation

logger = logging.getLogger(__name__)


async def discover_relations(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    threshold: float = 0.85,
    max_relations_per_memory: int = 10,
) -> int:
    """扫描工作区内的记忆，基于向量相似度自动创建 related 关系。

    Args:
        db: 数据库会话
        workspace_id: 工作区 ID
        threshold: 余弦相似度阈值（默认 0.85）
        max_relations_per_memory: 每条记忆最多自动创建的关系数（防止过度连接）

    Returns:
        新创建的关系数量
    """
    # 查询该工作区所有有 embedding 的 active 记忆
    stmt = (
        select(Memory)
        .where(
            Memory.workspace_id == workspace_id,
            Memory.status == "active",
            Memory.embedding.isnot(None),
        )
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    if len(memories) < 2:
        logger.debug(f"工作区 {workspace_id} 记忆数不足，跳过关系发现")
        return 0

    # 提取 embedding 向量
    memory_ids = [m.id for m in memories]
    embeddings = np.array([m.embedding for m in memories], dtype=np.float32)

    # 归一化（余弦相似度 = 点积 after 归一化）
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1  # 避免除零
    normalized = embeddings / norms

    # 计算相似度矩阵
    similarity_matrix = normalized @ normalized.T

    # 查询既有关系（避免重复创建）
    existing_stmt = select(MemoryRelation).where(
        MemoryRelation.source_memory_id.in_(memory_ids)
        | MemoryRelation.target_memory_id.in_(memory_ids)
    )
    existing_result = await db.execute(existing_stmt)
    existing_relations = existing_result.scalars().all()

    # 构建既有关系集合（双向）
    existing_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for rel in existing_relations:
        existing_pairs.add((rel.source_memory_id, rel.target_memory_id))
        existing_pairs.add((rel.target_memory_id, rel.source_memory_id))

    # 统计每条记忆已创建的关系数
    relation_count: dict[uuid.UUID, int] = {mid: 0 for mid in memory_ids}

    new_relations = []
    now = datetime.now(UTC)

    # 遍历上三角矩阵（避免重复和自环）
    for i in range(len(memories)):
        for j in range(i + 1, len(memories)):
            if relation_count[memory_ids[i]] >= max_relations_per_memory:
                continue
            if relation_count[memory_ids[j]] >= max_relations_per_memory:
                continue

            similarity = float(similarity_matrix[i, j])
            if similarity < threshold:
                continue

            # 检查是否已有关系
            if (memory_ids[i], memory_ids[j]) in existing_pairs:
                continue

            # 创建新关系
            relation = MemoryRelation(
                id=uuid.uuid4(),
                source_memory_id=memory_ids[i],
                target_memory_id=memory_ids[j],
                relation_type="related",
                confidence=similarity,  # 用相似度作为初始置信度
                strength=0.0,
                created_at=now,
            )
            new_relations.append(relation)
            relation_count[memory_ids[i]] += 1
            relation_count[memory_ids[j]] += 1

            logger.debug(
                f"自动创建关系: {memories[i].title[:30]}... <-> {memories[j].title[:30]}... "
                f"(相似度={similarity:.3f})"
            )

    # 批量写入
    if new_relations:
        db.add_all(new_relations)
        await db.commit()
        logger.info(
            f"工作区 {workspace_id} 自动创建 {len(new_relations)} 条关系 "
            f"(阈值={threshold}, 扫描记忆={len(memories)})"
        )

    return len(new_relations)
