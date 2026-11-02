"""记忆路由共享的文件同步工具。

DB 是权威源，Markdown 是镜像。记忆变更在同一事务中写入
file_sync_job；后台按主库当前状态重放，成功后仅确认本批意图。
删除意图不依赖 memory 外键，避免清理失败后重建复活已删除记忆。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from apps.api.deps import get_file_store, get_memory_indexer
from packages.domain.models import FileSyncJob, Workspace
from packages.storage.file_store import MemoryFile
from packages.storage.meta_export import export_memory_meta, export_workspaces_meta
from packages.storage.meta_store import MetaStore

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
        tags=list(getattr(memory, "tags", None) or []),
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


async def sync_workspaces_to_file(db: AsyncSession) -> bool:
    """把工作区快照写入 ``_meta/_workspaces.json``。

    工作区在 DB 中新建后立即调用，避免重建时只能在下次全量导出后
    才恢复出空工作区。失败只记日志，不阻塞请求。
    """
    try:
        file_store = get_file_store()
    except RuntimeError:
        logger.warning("FileStore not initialized; skip _workspaces.json export")
        return False
    try:
        await export_workspaces_meta(db, file_store.base_path / "_meta")
        return True
    except Exception:
        logger.exception("Failed to export _meta/_workspaces.json")
        return False


async def resolve_workspace_name(db: AsyncSession, workspace_id: uuid.UUID) -> str | None:
    """解析工作区名；文件与索引路径都依赖它。"""
    result = await db.execute(select(Workspace.name).where(Workspace.id == workspace_id))
    return result.scalar_one_or_none()


async def delete_memory_assets(
    memory_id: uuid.UUID | str,
    workspace_name: str | None,
    memory_type: str,
    title: str,
    *,
    file_path: str | None = None,
    save_index: bool = True,
) -> bool:
    """删除已提交 DB 删除的记忆文件资产：MD / index.db / vectors.npz / _meta。

    必须在 DB 删除提交后调用；失败返回 False，由事务内的持久意图重放。
    按 ID 清理全部路径，重复执行安全。
    """
    try:
        file_store = get_file_store()
        indexer = get_memory_indexer()
        await indexer.remove_from_index(str(memory_id))
        indexer.vector_index.remove(str(memory_id))
        # 按 ID 清理所有旧类型/旧工作区镜像；不信任外部提供的路径。
        paths = await asyncio.to_thread(file_store.find_all_by_id, str(memory_id))
        for target in paths:
            await asyncio.to_thread(target.unlink, missing_ok=True)
        await asyncio.to_thread(
            MetaStore(file_store.base_path / "_meta").delete_memory,
            str(memory_id),
        )
        if save_index:
            await asyncio.to_thread(indexer.vector_index.save)
        return True
    except Exception:
        logger.exception("Failed to remove assets for deleted memory %s", memory_id)
        return False


async def replay_file_sync_jobs(db: AsyncSession, limit: int = 100) -> int:
    """Repair from current DB state, acknowledge only the selected intents.

    New edits made during I/O have different intent IDs and remain pending.
    Failed writes/deletes are retained across process restarts.
    """
    from packages.domain.models import Memory

    jobs = list(
        (
            await db.scalars(
                select(FileSyncJob).order_by(FileSyncJob.created_at, FileSyncJob.id).limit(limit)
            )
        ).all()
    )
    by_memory: dict[uuid.UUID, list[uuid.UUID]] = {}
    for job in jobs:
        by_memory.setdefault(job.memory_id, []).append(job.id)
    repaired = 0
    for memory_id, job_ids in by_memory.items():
        memory = await db.get(Memory, memory_id, populate_existing=True)
        if memory is None:
            ok = await delete_memory_assets(memory_id, None, "", "")
        else:
            ok = await sync_memory_to_file(
                memory,
                db,
                embedding=memory.embedding,
                skip_vector_index=memory.embedding is None,
                save_index=True,
            )
        if ok:
            await db.execute(delete(FileSyncJob).where(FileSyncJob.id.in_(job_ids)))
            await db.commit()
            repaired += 1
        else:
            await db.rollback()
    return repaired


async def run_file_sync_recovery() -> None:
    """Bounded retry loop; initialized storage is required before starting it."""
    from packages.domain.database import async_session_maker

    while True:
        try:
            async with async_session_maker() as db:
                await replay_file_sync_jobs(db)
        except Exception:
            logger.exception("Memory mirror repair failed; intents retained for retry")
        await asyncio.sleep(5)


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
        # 标题、类型、workspace 都会改变路径。先原子写新文件，再清理同 ID 镜像。
        old_paths = await asyncio.to_thread(file_store.find_all_by_id, mf.id)
        mf.file_path = await asyncio.to_thread(file_store.save, mf, workspace_name=workspace_name)
        for old_path in old_paths:
            if old_path != mf.file_path:
                await asyncio.to_thread(old_path.unlink, missing_ok=True)
        # 非激活记忆（superseded/deprecated 等）与缺向量的记忆都不应留在向量索引中
        update_vector = not skip_vector_index and mf.status == "active"
        await indexer.index_memory(mf, embedding=embedding, update_vector=update_vector)
        if mf.status != "active" or (skip_vector_index and memory.embedding is None):
            indexer.vector_index.remove(mf.id)
        if save_index:
            await asyncio.to_thread(indexer.vector_index.save)

        # 元数据也是恢复副本；失败必须保留待同步意图，不能报告全部成功。
        await export_memory_meta(db, memory.id, file_store.base_path / "_meta")
        return True
    except Exception:
        # 放行请求但必须响亮：失败意味着 MD 镜像与 DB 静默偏差，
        # 重建 DB（以 MD 为源）时会丢这条记忆。
        logger.exception(
            "Failed to sync memory %s to file store; MD mirror is now stale", memory.id
        )
        if raise_on_error:
            raise
        return False
