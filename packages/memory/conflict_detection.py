"""写入时冲突检测：语义相近且文本矛盾时登记 MemoryConflict。

审批与自动生效共用同一实现：手动批准在记忆落库后调用，自动生效在
审批前用候选向量预检，确保 open 冲突能真正阻断自动转正。
"""

from __future__ import annotations

import logging
import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models.memory import Memory, MemoryConflict
from packages.retrieval.context.conflict import has_contradiction_text

logger = logging.getLogger(__name__)

COSINE_THRESHOLD = 0.7
# 单次检测的既有记忆上限：单用户本地库规模下足够覆盖，避免极端数据量下 O(n) 失控
_SCAN_LIMIT = 1000


async def detect_write_time_conflicts(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    content: str,
    embedding: list[float] | None,
    new_memory_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
) -> list[MemoryConflict]:
    """检查新内容与既有 active 记忆是否语义相近且存在矛盾表述。

    返回本次新建的冲突行；相同 candidate（或相同新记忆）对同一条既有
    记忆的 open 冲突不会重复登记。
    """
    if embedding is None:
        return []

    stmt = select(Memory.id, Memory.title, Memory.content, Memory.embedding).where(
        Memory.workspace_id == workspace_id,
        Memory.status == "active",
        Memory.embedding.isnot(None),
    )
    if new_memory_id is not None:
        stmt = stmt.where(Memory.id != new_memory_id)
    rows = (await db.execute(stmt.order_by(Memory.updated_at.desc()).limit(_SCAN_LIMIT))).all()
    if not rows:
        return []

    new_emb = np.array(list(embedding), dtype=np.float32)
    new_norm = np.linalg.norm(new_emb)
    if new_norm == 0:
        return []

    created: list[MemoryConflict] = []
    for row in rows:
        existing_emb = np.array(list(row.embedding), dtype=np.float32)
        existing_norm = np.linalg.norm(existing_emb)
        if existing_norm == 0:
            continue
        cosine = float(np.dot(new_emb, existing_emb) / (new_norm * existing_norm))
        if cosine <= COSINE_THRESHOLD:
            continue
        if not has_contradiction_text(content, row.content):
            continue

        conditions = [
            MemoryConflict.memory_id == row.id,
            MemoryConflict.status == "open",
        ]
        if candidate_id is not None:
            conditions.append(MemoryConflict.candidate_id == candidate_id)
        else:
            conditions.append(MemoryConflict.candidate_id.is_(None))
        existing_conflict = (
            await db.execute(select(MemoryConflict.id).where(*conditions).limit(1))
        ).scalar_one_or_none()
        if existing_conflict is not None:
            continue

        conflict = MemoryConflict(
            workspace_id=workspace_id,
            memory_id=row.id,
            candidate_id=candidate_id,
            conflict_type="contradiction",
            description=f"新内容与记忆「{row.title}」语义相近且存在矛盾表述",
            evidence={
                "similarity": round(cosine, 4),
                "new_memory_id": str(new_memory_id) if new_memory_id is not None else None,
            },
        )
        db.add(conflict)
        created.append(conflict)

    if created:
        await db.flush()
    return created
