"""正文 wiki 双链（``[[标题]]``）到记忆关系的同步。

正文里写 ``[[另一条记忆的标题]]`` 表示显式引用；这里把它落成
``created_by="wikilink"`` 的 related 边，让知识图谱跟着正文走。

同步按「当前正文」重建该记忆的出边，因此是幂等的：链接删掉，边也删掉；
其它来源（manual / auto / review / merge…）的边不受影响，同一对记忆
已经存在这样的边时本次跳过，避免重复边。
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models.memory import Memory, MemoryRelation

logger = logging.getLogger(__name__)

# [[标题]] / [[标题#小节]] / [[标题|别名]]：只取目标标题，丢弃锚点与别名
_WIKILINK = re.compile(r"\[\[([^\[\]|#]+)(?:#[^\[\]|]*)?(?:\|[^\[\]]*)?\]\]")

# 单条记忆的链接上限：正文异常时会退化成解析炸弹，也防止一次写入造出过多边
MAX_LINKS_PER_MEMORY = 50

# created_by 列宽 16，"wikilink" 留有余量
CREATED_BY = "wikilink"


def extract_link_targets(content: str) -> list[str]:
    """按出现顺序抽取去重后的链接目标标题（大小写不敏感去重）。"""
    targets: list[str] = []
    seen: set[str] = set()
    for raw in _WIKILINK.findall(content or ""):
        title = raw.strip()
        key = title.lower()
        if not title or key in seen:
            continue
        seen.add(key)
        targets.append(title)
        if len(targets) >= MAX_LINKS_PER_MEMORY:
            break
    return targets


async def _title_index(
    db: AsyncSession, workspace_ids: set[uuid.UUID]
) -> dict[tuple[uuid.UUID, str], list[uuid.UUID]]:
    """(workspace, 小写标题) → 记忆 id 列表；同名记忆会有多个目标。"""
    if not workspace_ids:
        return {}
    rows = (
        await db.execute(
            select(Memory.workspace_id, Memory.id, Memory.title).where(
                Memory.workspace_id.in_(workspace_ids),
                Memory.status == "active",
            )
        )
    ).all()
    index: dict[tuple[uuid.UUID, str], list[uuid.UUID]] = defaultdict(list)
    for workspace_id, memory_id, title in rows:
        key = (title or "").strip().lower()
        if key:
            index[(workspace_id, key)].append(memory_id)
    return index


async def sync_wikilink_relations(
    db: AsyncSession,
    memory: Memory,
    *,
    title_index: dict[tuple[uuid.UUID, str], list[uuid.UUID]] | None = None,
) -> int:
    """按 ``memory.content`` 重建它的 wikilink 出边，返回新建的边数。

    调用方负责 commit。``title_index`` 可在批量同步时传入，避免逐条查库。
    """
    existing = (
        (
            await db.execute(
                select(MemoryRelation).where(MemoryRelation.source_memory_id == memory.id)
            )
        )
        .scalars()
        .all()
    )

    # 非 wikilink 边占用的目标不再重复建边
    occupied = {rel.target_memory_id for rel in existing if rel.created_by != CREATED_BY}
    for rel in existing:
        if rel.created_by == CREATED_BY:
            await db.delete(rel)

    targets = extract_link_targets(memory.content or "")
    if not targets:
        await db.flush()
        return 0

    index = title_index
    if index is None:
        index = await _title_index(db, {memory.workspace_id})

    created = 0
    linked: set[uuid.UUID] = set()
    for target in targets:
        for memory_id in index.get((memory.workspace_id, target.lower()), []):
            if memory_id == memory.id or memory_id in occupied or memory_id in linked:
                continue
            db.add(
                MemoryRelation(
                    source_memory_id=memory.id,
                    target_memory_id=memory_id,
                    relation_type="related",
                    confidence=1.0,
                    strength=0.0,
                    created_by=CREATED_BY,
                    source=f"wikilink:{target[:48]}",
                )
            )
            linked.add(memory_id)
            created += 1

    await db.flush()
    if created:
        logger.debug("wikilink: %s → %d 条记忆", memory.title, created)
    return created


async def sync_all_wikilinks(db: AsyncSession) -> int:
    """重建全部 active 记忆的 wikilink 边（整库重建后调用），返回边总数。"""
    memories = (await db.execute(select(Memory).where(Memory.status == "active"))).scalars().all()
    index = await _title_index(db, {m.workspace_id for m in memories})
    total = 0
    for memory in memories:
        total += await sync_wikilink_relations(db, memory, title_index=index)
    if total:
        logger.info("wikilink: 重建 %d 条正文引用边", total)
    return total
