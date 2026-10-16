"""基于文件的记忆 API 路由。"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import (
    get_current_agent,
    get_db,
    get_file_store,
    get_memory_indexer,
    require_scope,
    resolve_workspace,
)
from apps.api.routes.context import invalidate_context_cache
from apps.api.routes.memory_status import invalidate_memory_status_caches
from apps.api.routes.search import invalidate_search_cache
from packages.domain.config import API_V1_PREFIX

logger = logging.getLogger(__name__)
from packages.domain.models import Memory
from packages.domain.schemas.common import MemoryStatus, MemoryType
from packages.domain.schemas.memory import MemoryContent, MemoryTitle
from packages.storage import config as storage_config
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.git_version import GitVersionControl
from packages.storage.indexer import MemoryIndexer

router = APIRouter(prefix=f"{API_V1_PREFIX}/file-memories", tags=["file-memories"])

git_vc = GitVersionControl(storage_config.memory_dir)

# git 统计的 TTL 缓存（底层是昂贵的子进程调用）
_git_stats_cache: tuple[float, dict[str, Any]] | None = None
_GIT_STATS_CACHE_TTL = 60.0  # 1 分钟


def invalidate_git_stats_cache() -> None:
    """使 git 统计缓存失效。"""
    global _git_stats_cache
    _git_stats_cache = None


class MemoryCreateRequest(BaseModel):
    title: MemoryTitle
    content: MemoryContent
    type: str = "fact"
    tags: list[str] = []
    related: list[str] = []


class MemoryUpdateRequest(BaseModel):
    title: MemoryTitle | None = None
    content: MemoryContent | None = None
    type: str | None = None
    tags: list[str] | None = None
    related: list[str] | None = None


@router.get("/stats")
async def get_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """获取存储统计信息。"""
    global _git_stats_cache

    indexer = get_memory_indexer()

    total_result = await db.execute(
        select(func.count()).select_from(Memory).where(Memory.status == "active")
    )
    file_count = total_result.scalar() or 0

    type_result = await db.execute(
        select(Memory.type, func.count()).where(Memory.status == "active").group_by(Memory.type)
    )
    type_distribution = {row[0]: row[1] for row in type_result.all()}

    # 检查 git 统计缓存
    now = time.monotonic()
    if _git_stats_cache is not None:
        cached_time, cached_git_stats = _git_stats_cache
        if now - cached_time < _GIT_STATS_CACHE_TTL:
            return {
                "file_count": file_count,
                "vector_count": indexer.vector_index.size(),
                "vector_index_path": str(indexer.vector_index.index_path),
                "type_distribution": type_distribution,
                **cached_git_stats,
            }

    # 计算 git 统计（开销大）
    git_commits = len(await git_vc.log(limit=1000))
    has_changes = await git_vc.has_changes()
    git_stats = {"git_commits": git_commits, "has_changes": has_changes}

    # 写入缓存
    _git_stats_cache = (now, git_stats)

    return {
        "file_count": file_count,
        "vector_count": indexer.vector_index.size(),
        "vector_index_path": str(indexer.vector_index.index_path),
        "git_commits": git_commits,
        "has_changes": has_changes,
        "type_distribution": type_distribution,
    }


@router.post("/rebuild-index")
async def rebuild_index(
    _identity: Annotated[
        AgentIdentity | None, Depends(require_scope("file-memories:write"))
    ] = None,
) -> dict[str, Any]:
    """从 Markdown 文件重建 SQLite 索引与向量索引。"""
    file_store = get_file_store()
    indexer = get_memory_indexer()
    memories = file_store.list()
    active_ids = {m.id for m in memories if m.status == "active"}
    for memory in memories:
        await indexer.index_memory(memory, update_vector=memory.id in active_ids)
    # 向量索引只保留 active 记忆，顺带清掉历史遗留的 archived/stale 条目
    orphan_ids = set(indexer.vector_index.vectors.keys()) - active_ids
    for oid in orphan_ids:
        indexer.vector_index.remove(oid)
    await asyncio.to_thread(indexer.vector_index.save)
    return {
        "message": "Index rebuilt",
        "indexed_count": len(memories),
        "vector_count": indexer.vector_index.size(),
    }


@router.get("/search/query")
async def search_memories(
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query(..., min_length=1, description="Search query"),
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    limit: int = Query(50, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """按内容检索记忆（BM25/文本检索）。"""
    indexer = get_memory_indexer()
    results = await indexer.search(q, limit=limit)

    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    # 指定 workspace 时按其过滤
    if resolved_ws_id is not None and db is not None and results:
        result_ids = [r.get("id") for r in results if r.get("id")]
        if result_ids:
            valid_ids = await db.scalars(
                select(Memory.id).where(
                    Memory.id.in_(
                        [
                            uuid.UUID(rid)
                            for rid in result_ids
                            if isinstance(rid, str) and _is_valid_uuid(rid)
                        ]
                    ),
                    Memory.workspace_id == resolved_ws_id,
                )
            )
            valid_id_set = {str(vid) for vid in valid_ids}
            results = [r for r in results if r.get("id") in valid_id_set]

    return {"results": results, "total": len(results)}


def _is_valid_uuid(s: str) -> bool:
    """检查字符串是否为合法 UUID。"""
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False


class SemanticSearchRequest(BaseModel):
    keyword: str
    # workspace 支持名称或 UUID；名称在请求时即时查 DB 解析。
    workspace_id: str | None = None
    limit: int = Field(default=10, ge=1, le=100)
    threshold: float = 0.0


@router.post("/search/semantic")
async def semantic_search_memories(
    request: SemanticSearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """按名称或 UUID 把召回限定到工作区，且仅保留 DB 中的 active 记忆。"""
    indexer = get_memory_indexer()
    allowed_ids = None
    resolved_ws_id: uuid.UUID | None = None
    if request.workspace_id is not None:
        resolved_ws_id = await resolve_workspace(request.workspace_id, db)
        ids = await db.scalars(
            select(Memory.id)
            .where(Memory.workspace_id == resolved_ws_id, Memory.status == "active")
            .limit(5000)
        )
        allowed_ids = {str(mid) for mid in ids}
    results = await indexer.semantic_search_text(
        query=request.keyword,
        limit=request.limit,
        threshold=request.threshold,
        allowed_ids=allowed_ids,
    )
    if resolved_ws_id is not None and results:
        # 异步读取向量/索引后用当前 DB 文本复核，避免写入仍在索引中
        # 时返回过期的镜像内容。
        current = await db.execute(
            select(
                Memory.id, Memory.title, Memory.content, Memory.type, Memory.version, Memory.status
            ).where(
                Memory.id.in_([uuid.UUID(row["id"]) for row in results]),
                Memory.workspace_id == resolved_ws_id,
                Memory.status == "active",
            )
        )
        by_id = {str(row.id): dict(row._mapping) for row in current}
        results = [
            {**row, **by_id[row["id"]], "id": row["id"]} for row in results if row["id"] in by_id
        ]
    return {"results": results, "total": len(results)}


@router.get("/versions")
async def get_versions(
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """获取提交历史。"""
    commits = await git_vc.log(limit=limit)
    return {"commits": commits, "total": len(commits)}


def _parse_list_field(value: str | list[str]) -> list[str]:
    """解析可能以字符串形式存储的列表字段。"""
    if isinstance(value, list):
        return value
    try:
        import ast

        result = ast.literal_eval(value)
        return result if isinstance(result, list) else []
    except (ValueError, SyntaxError):
        return []


@router.get("")
async def list_memories(
    type: MemoryType | None = Query(None),
    status: MemoryStatus | None = Query("active"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """列出记忆，支持可选过滤与分页。"""
    indexer = get_memory_indexer()
    memories = await indexer.list_memories(status=status, type=type, offset=offset, limit=limit)
    total = await indexer.count_memories(status=status, type=type)

    return {"items": memories, "total": total, "offset": offset, "limit": limit}


@router.post("")
async def create_memory(
    request: MemoryCreateRequest,
    _identity: Annotated[
        AgentIdentity | None, Depends(require_scope("file-memories:write"))
    ] = None,
) -> dict[str, Any]:
    """创建新记忆。"""
    file_store = get_file_store()
    indexer = get_memory_indexer()

    slug = request.title.lower().replace(" ", "-")
    memory = MemoryFile(
        id=f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}-{slug}",
        title=request.title,
        content=request.content,
        type=request.type,
        tags=request.tags,
        related=request.related,
    )

    # 写入文件（默认 chat 目录，之后可归入工作区）
    file_store.save(memory, workspace_name="chat")

    # 写入 SQLite 索引 + 向量
    await indexer.index_memory(memory)
    await asyncio.to_thread(indexer.vector_index.save)

    invalidate_search_cache()
    invalidate_context_cache()
    invalidate_memory_status_caches()

    return memory.to_dict()


@router.get("/{memory_id}")
async def get_memory(
    memory_id: str,
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """按 ID 获取单条记忆。"""
    indexer = get_memory_indexer()
    memory = await indexer.get_memory(memory_id)

    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    return memory


@router.put("/{memory_id}")
async def update_memory(
    memory_id: str,
    request: MemoryUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[
        AgentIdentity | None, Depends(require_scope("file-memories:write"))
    ] = None,
) -> dict[str, Any]:
    """更新已有记忆。"""
    indexer = get_memory_indexer()
    file_store = get_file_store()

    index_entry = await indexer.get_memory(memory_id)
    if not index_entry:
        raise HTTPException(status_code=404, detail="Memory not found")

    workspace_name = index_entry.get("workspace") or "chat"
    type_name = index_entry.get("type", "fact")
    title = index_entry.get("title", memory_id)

    memory = file_store.load(workspace_name, type_name, title, memory_id=memory_id)

    if not memory:
        raise HTTPException(status_code=404, detail="Memory file not found")

    old_title = memory.title
    old_type = memory.type

    # 更新字段
    if request.title is not None:
        memory.title = request.title
    if request.content is not None:
        memory.content = request.content
    if request.type is not None:
        memory.type = request.type
    if request.tags is not None:
        memory.tags = request.tags
    if request.related is not None:
        memory.related = request.related

    memory.updated = datetime.now(UTC)
    memory.version += 1

    # 标题/类型变更会改变文件路径：先删旧路径文件再保存新的
    if old_title != memory.title or old_type != memory.type:
        file_store.delete(workspace_name, old_type, old_title, memory_id=memory_id)

    # 写入文件
    file_store.save(memory, workspace_name=workspace_name)

    # 更新索引
    await indexer.index_memory(memory)
    await asyncio.to_thread(indexer.vector_index.save)

    invalidate_search_cache()
    invalidate_context_cache()
    invalidate_memory_status_caches()

    return memory.to_dict()


async def _delete_memory_entry(
    indexer: MemoryIndexer,
    file_store: FileStore,
    db: AsyncSession,
    memory_id: str,
) -> tuple[dict[str, Any], bool, bool] | None:
    """删除单条记忆的文件、索引条目与 DB 行。

    返回 (index_entry, file_deleted, db_cleaned)；记忆不在索引中
    时返回 None。向量索引持久化由调用方负责，便于批量删除时合并。
    """
    index_entry = await indexer.get_memory(memory_id)
    if not index_entry:
        return None

    workspace_name = index_entry.get("workspace") or "chat"
    type_name = index_entry.get("type", "fact")
    memory_title = index_entry.get("title", memory_id)

    file_deleted = file_store.delete(workspace_name, type_name, memory_title, memory_id=memory_id)
    await indexer.remove_from_index(memory_id)

    db_cleaned = False
    try:
        mem_uuid = uuid.UUID(memory_id)
        result = await db.execute(delete(Memory).where(Memory.id == mem_uuid))
        db_cleaned = getattr(result, "rowcount", 0) > 0
    except ValueError:
        logger.debug("Invalid UUID format for memory %s", memory_id)

    return index_entry, file_deleted, db_cleaned


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[
        AgentIdentity | None, Depends(require_scope("file-memories:write"))
    ] = None,
) -> dict[str, Any]:
    """从文件、索引与 DB 中删除记忆。"""
    indexer = get_memory_indexer()
    file_store = get_file_store()

    entry = await _delete_memory_entry(indexer, file_store, db, memory_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    _index_entry, file_deleted, db_cleaned = entry
    await asyncio.to_thread(indexer.vector_index.save)

    invalidate_search_cache()
    invalidate_context_cache()
    invalidate_memory_status_caches()

    return {
        "message": "Memory deleted",
        "file_deleted": file_deleted,
        "index_cleaned": True,
        "db_cleaned": db_cleaned,
    }


class BatchDeleteRequest(BaseModel):
    ids: list[str] = Field(..., max_length=100)


@router.post("/batch-delete")
async def batch_delete_memories(
    body: BatchDeleteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[
        AgentIdentity | None, Depends(require_scope("file-memories:write"))
    ] = None,
) -> dict[str, Any]:
    """批量删除记忆，逐条返回结果。"""
    if not body.ids:
        return {"deleted": [], "failed": []}

    indexer = get_memory_indexer()
    file_store = get_file_store()

    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    db_ids: list[uuid.UUID] = []

    for memory_id in body.ids:
        try:
            index_entry = await indexer.get_memory(memory_id)
            if not index_entry:
                failed.append({"id": memory_id, "error": "not_found"})
                continue

            workspace_name = index_entry.get("workspace") or "chat"
            type_name = index_entry.get("type", "fact")
            memory_title = index_entry.get("title", memory_id)

            file_store.delete(workspace_name, type_name, memory_title, memory_id=memory_id)
            await indexer.remove_from_index(memory_id)

            try:
                db_ids.append(uuid.UUID(memory_id))
            except ValueError:
                pass

            deleted.append(memory_id)
        except Exception as e:
            # 单条失败只记录，继续处理剩余条目
            failed.append({"id": memory_id, "error": str(e)})

    if db_ids:
        await db.execute(delete(Memory).where(Memory.id.in_(db_ids)))
        await db.commit()

    await asyncio.to_thread(indexer.vector_index.save)
    if deleted:
        invalidate_search_cache()
        invalidate_context_cache()
        invalidate_memory_status_caches()

    return {"deleted": deleted, "failed": failed}
