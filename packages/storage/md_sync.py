"""Markdown → DB 单条同步：手改 MD 后把正文/标题/类型/标签/状态写回主库。

运行时 DB 是检索权威，但用户直接编辑 Markdown 是受支持的工作方式。
本模块只处理"已存在于 DB 的记忆"的单条正向同步：
- 版本快照 + 乐观锁由 snapshot_and_advance 负责；
- 标题/正文变化会清空 embedding，由调用方重新入队向量任务；
- workspace、source、confidence/importance 不从 MD 覆盖。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Memory
from packages.domain.text_utils import normalize_memory_content
from packages.domain.types import TYPE_DEFINITIONS
from packages.memory.service import normalize_tags, snapshot_and_advance
from packages.storage.file_store import MemoryFile

logger = logging.getLogger(__name__)

_ALLOWED_STATUS = {"active", "superseded", "conflicted", "deprecated"}


@dataclass
class MdSyncResult:
    status: str  # updated | unchanged | missing_memory | invalid
    memory_id: str
    changed_fields: list[str] = field(default_factory=list)
    needs_embedding: bool = False


async def sync_memory_from_markdown(
    db: AsyncSession,
    memory_file: MemoryFile,
    *,
    changed_by: str = "file_sync",
    meta_dir: Path | None = None,
) -> MdSyncResult:
    """把一份 Markdown 的变更同步到已有 DB 记忆；不新建记忆。"""
    try:
        memory_id = uuid.UUID(str(memory_file.id))
    except (ValueError, AttributeError):
        return MdSyncResult(status="missing_memory", memory_id=str(memory_file.id))

    memory = (await db.execute(select(Memory).where(Memory.id == memory_id))).scalar_one_or_none()
    if memory is None:
        return MdSyncResult(status="missing_memory", memory_id=str(memory_id))
    # 重试镜像与 watchdog 可能交错；旧版本镜像不能反向覆盖较新的主库。
    if memory_file.version < memory.version:
        logger.warning("Skip stale MD mirror for %s", memory_id)
        return MdSyncResult(status="invalid", memory_id=str(memory_id))

    if memory_file.type not in TYPE_DEFINITIONS:
        logger.warning("Skip MD sync for %s: invalid type %r", memory_id, memory_file.type)
        return MdSyncResult(status="invalid", memory_id=str(memory_id))
    if memory_file.status not in _ALLOWED_STATUS:
        logger.warning("Skip MD sync for %s: invalid status %r", memory_id, memory_file.status)
        return MdSyncResult(status="invalid", memory_id=str(memory_id))

    desired_content = normalize_memory_content(memory_file.content)
    desired_tags = normalize_tags(memory_file.tags)
    changed: list[str] = []
    if memory.title.strip() != memory_file.title.strip():
        changed.append("title")
    if memory.content.strip() != desired_content.strip():
        changed.append("content")
    if memory.type != memory_file.type:
        changed.append("type")
    if sorted(memory.tags or []) != sorted(desired_tags):
        changed.append("tags")
    if memory.status != memory_file.status:
        changed.append("status")

    if not changed:
        return MdSyncResult(status="unchanged", memory_id=str(memory_id))

    await snapshot_and_advance(
        db,
        memory,
        change_type="file_edit",
        changed_by_type=changed_by,
        reason="Markdown file edited",
    )
    if "title" in changed:
        memory.title = memory_file.title.strip()
    if "content" in changed:
        memory.content = desired_content
    if "type" in changed:
        memory.type = memory_file.type
    if "tags" in changed:
        memory.tags = desired_tags
    if "status" in changed:
        memory.status = memory_file.status

    needs_embedding = "title" in changed or "content" in changed
    if needs_embedding:
        memory.embedding = None

    await db.flush()

    try:
        from packages.storage.meta_export import export_memory_meta

        await export_memory_meta(db, memory.id, meta_dir)
    except Exception:
        logger.warning("Failed to export _meta after MD sync for %s", memory_id, exc_info=True)

    logger.info("Synced Markdown→DB for %s: %s", memory_id, ", ".join(changed))
    return MdSyncResult(
        status="updated",
        memory_id=str(memory_id),
        changed_fields=changed,
        needs_embedding=needs_embedding,
    )
