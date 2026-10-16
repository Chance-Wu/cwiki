"""记忆路由共享的文件同步工具。

file_sync 机制：DB 是权威源，Markdown 文件是可读镜像。路由在提交
事务后调用 sync_memory_to_file 把已提交状态写回 MD + 索引；写入
默认静默失败（下次启动扫描可恢复），worker 侧可开启 raise_on_error
让任务队列重试，保证最终一致。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from apps.api.deps import get_file_store, get_memory_indexer
from packages.domain.models import Workspace
from packages.storage.file_store import MemoryFile

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from packages.domain.models import Memory

logger = logging.getLogger(__name__)


def memory_to_file(memory: Memory) -> MemoryFile:
    return MemoryFile(
        id=str(memory.id),
        title=memory.title,
        content=memory.content,
        type=memory.type,
        version=getattr(memory, "version", 1),
        status=getattr(memory, "status", "active"),
        source=getattr(memory, "source", "mcp"),
        created=memory.created_at,
        updated=memory.updated_at,
        confidence=getattr(memory, "confidence", None),
        importance=getattr(memory, "importance", None),
        usage_count=getattr(memory, "usage_count", 0),
        last_used_at=getattr(memory, "last_used_at", None),
        is_permanent=getattr(memory, "is_permanent", False),
        metadata=getattr(memory, "metadata_", None),
    )


async def sync_memory_to_file(
    memory: Memory,
    db: AsyncSession,
    embedding: list[float] | None = None,
    save_index: bool = False,
    skip_vector_index: bool = False,
    raise_on_error: bool = False,
) -> bool:
    """把已提交的 DB 状态镜像到文件；worker 侧可选择抛错以触发队列重试。"""
    try:
        file_store = get_file_store()
        indexer = get_memory_indexer()

        ws_result = await db.execute(
            select(Workspace.name).where(Workspace.id == memory.workspace_id)
        )
        workspace_name = ws_result.scalar_one_or_none()

        mf = memory_to_file(memory)
        mf.workspace = workspace_name
        # 标题变更会导致文件路径变化：先写新文件，再清理旧路径，避免遗留孤儿镜像
        old_path = await asyncio.to_thread(
            file_store._find_file_by_id, workspace_name or "chat", mf.type, mf.id
        )
        mf.file_path = await asyncio.to_thread(file_store.save, mf, workspace_name=workspace_name)
        if old_path is not None and old_path != mf.file_path:
            await asyncio.to_thread(old_path.unlink, missing_ok=True)
        # 非激活记忆（archived 等）与缺向量的记忆都不应留在向量索引中
        update_vector = not skip_vector_index and mf.status == "active"
        await indexer.index_memory(mf, embedding=embedding, update_vector=update_vector)
        if mf.status != "active" or (skip_vector_index and memory.embedding is None):
            indexer.vector_index.remove(mf.id)
        if save_index:
            await asyncio.to_thread(indexer.vector_index.save)
        return True
    except Exception:
        logger.warning("Failed to sync memory %s to file store", memory.id, exc_info=True)
        if raise_on_error:
            raise
        return False
