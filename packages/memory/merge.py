"""正式记忆合并：把一条记忆并入另一条，保留完整历史而不是物理删除。

与候选合并（``service.merge_candidate``）不同，这里两条都已是正式记忆，
合并的是「同一知识被写了两遍」的结果：标签取并集、关系与证据改挂到目标、
来源标记为 superseded。正文是否拼接由调用方决定——默认不动目标正文，
避免系统擅自改写人工内容。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Evidence, Memory, MemoryRelation, ReviewSchedule
from packages.memory.service import union_tags


def _merged_content(target: Memory, source: Memory) -> str:
    """把来源正文追加到目标末尾，标明出处以便回溯。"""
    heading = f"## 合并自《{source.title}》"
    if heading in target.content:
        return target.content
    return f"{target.content.rstrip()}\n\n{heading}\n\n{source.content.strip()}\n"


async def merge_memories(
    db: AsyncSession,
    *,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    merge_content: bool = False,
) -> dict[str, Any]:
    """把 ``source_id`` 并入 ``target_id`` 并标记来源为 superseded。

    只做 flush，由调用方 commit 并负责文件/索引同步。
    校验失败抛 ``ValueError``（消息可直接返回给调用方）。
    """
    if source_id == target_id:
        raise ValueError("不能把记忆合并到自身")

    rows = (
        (await db.execute(select(Memory).where(Memory.id.in_([source_id, target_id]))))
        .scalars()
        .all()
    )
    by_id = {memory.id: memory for memory in rows}
    source, target = by_id.get(source_id), by_id.get(target_id)
    if source is None or target is None:
        raise ValueError("记忆不存在")
    if source.workspace_id != target.workspace_id:
        raise ValueError("只能合并同一工作区内的记忆")
    if source.status != "active" or target.status != "active":
        raise ValueError("只有 active 记忆可以合并")

    added_tags = union_tags(target.tags, source.tags)
    tags_changed = list(added_tags) != list(target.tags or [])
    target.tags = added_tags

    if merge_content:
        target.content = _merged_content(target, source)
        target.embedding = None

    # 关系迁移：来源的出边/入边改指目标；改完变成自环的直接删
    relation_rows = (
        (
            await db.execute(
                select(MemoryRelation).where(
                    or_(
                        MemoryRelation.source_memory_id == source_id,
                        MemoryRelation.target_memory_id == source_id,
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    existing = {
        (src, dst, rel_type)
        for src, dst, rel_type in (
            await db.execute(
                select(
                    MemoryRelation.source_memory_id,
                    MemoryRelation.target_memory_id,
                    MemoryRelation.relation_type,
                )
            )
        ).all()
    }
    moved = dropped = 0
    for relation in relation_rows:
        existing.discard(
            (relation.source_memory_id, relation.target_memory_id, relation.relation_type)
        )
        if relation.source_memory_id == source_id:
            relation.source_memory_id = target_id
        if relation.target_memory_id == source_id:
            relation.target_memory_id = target_id
        if relation.source_memory_id == relation.target_memory_id:
            await db.delete(relation)
            dropped += 1
            continue
        key = (relation.source_memory_id, relation.target_memory_id, relation.relation_type)
        if key in existing:
            await db.delete(relation)
            dropped += 1
            continue
        existing.add(key)
        moved += 1

    evidence_moved = (
        await db.execute(
            update(Evidence).where(Evidence.memory_id == source_id).values(memory_id=target_id)
        )
    ).rowcount or 0
    # 来源不再参与复习调度，直接把计划删掉，避免 superseded 记忆仍出现在到期队列
    await db.execute(delete(ReviewSchedule).where(ReviewSchedule.memory_id == source_id))

    source.status = "superseded"
    source.updated_at = datetime.now(UTC)
    source.embedding = None

    supersede_edge = MemoryRelation(
        id=uuid.uuid4(),
        source_memory_id=target_id,
        target_memory_id=source_id,
        relation_type="supersedes",
        confidence=1.0,
        created_by="merge",
    )
    db.add(supersede_edge)
    await db.flush()

    return {
        "merged": True,
        "source_id": str(source_id),
        "target_id": str(target_id),
        "content_merged": merge_content,
        "tags": added_tags,
        "tags_changed": tags_changed,
        "relations_moved": moved,
        "relations_dropped": dropped,
        "evidences_moved": evidence_moved,
        "needs_reembedding": merge_content,
    }
