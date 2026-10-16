"""FastAPI 依赖注入。"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator, Callable, Sequence
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from packages.domain.database import async_session_maker
from packages.domain.models import Workspace
from packages.storage.file_store import FileStore
from packages.storage.indexer import MemoryIndexer

_file_store: FileStore | None = None
_memory_indexer: MemoryIndexer | None = None


def get_file_store() -> FileStore:
    """返回 FileStore 单例。"""
    if _file_store is None:
        raise RuntimeError("FileStore not initialized. Check application lifespan.")
    return _file_store


def get_memory_indexer() -> MemoryIndexer:
    """返回 MemoryIndexer 单例。"""
    if _memory_indexer is None:
        raise RuntimeError("MemoryIndexer not initialized. Check application lifespan.")
    return _memory_indexer


def init_storage_components(file_store: FileStore, indexer: MemoryIndexer) -> None:
    """初始化存储组件单例，由应用 lifespan 启动时调用。"""
    global _file_store, _memory_indexer
    _file_store = file_store
    _memory_indexer = indexer


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """yield 一个异步数据库会话。

    请求结束时自动 commit：路由内只做 flush 即可读取主键，
    统一在依赖出口提交，避免各路由遗漏事务收尾。
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


_DEFAULT_IDENTITY = AgentIdentity()


async def get_current_agent() -> AgentIdentity:
    """返回本地默认 Agent 身份（单用户模式，无认证环节）。"""
    return _DEFAULT_IDENTITY


def require_scope(required_scope: str) -> Callable[..., Any]:
    """返回空操作依赖：本地模式不校验 scope，但保留注入点以便未来扩展。"""

    async def _check() -> AgentIdentity:
        return _DEFAULT_IDENTITY

    return _check


async def get_or_404(
    db: AsyncSession,
    model: type[Any],
    id_value: Any,
    detail: str | None = None,
    options: Sequence[Any] | None = None,
) -> Any:
    """按 ID 获取模型实例，不存在则抛 HTTP 404。

    *options* 接受 SQLAlchemy 加载选项（如 ``defer(Memory.embedding)``、
    ``noload(Memory.versions)``），避免加载大字段/关联关系。
    """
    stmt = select(model).where(model.id == id_value)
    if options:
        stmt = stmt.options(*options)
    result = await db.execute(stmt)
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail or f"{model.__name__} {id_value} not found",
        )
    return obj


async def execute_paginated(
    db: AsyncSession,
    stmt: Any,
    count_stmt: Any,
    order_by: Any,
    offset: int,
    limit: int,
) -> tuple[int, Sequence[Any]]:
    """执行分页查询，返回 (total, items)。

    count 与数据查询共用同一会话，调用方事务内未提交的
    写入对两者均可见，保证总数与数据一致。
    """
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    data_result = await db.execute(stmt.order_by(order_by).offset(offset).limit(limit))
    return total, data_result.scalars().all()


def apply_optional_filters(
    stmt: Any,
    count_stmt: Any,
    conditions: list[Any],
) -> tuple[Any, Any]:
    """将 WHERE 条件同时应用到数据查询与 count 查询。"""
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    return stmt, count_stmt


async def get_workspace(
    workspace_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Workspace:
    """按 ID 获取 workspace，不存在则抛 404。"""
    return await get_or_404(db, Workspace, workspace_id)  # type: ignore[no-any-return]


async def resolve_workspace(
    workspace_id: str | None,
    db: AsyncSession,
) -> uuid.UUID:
    """按名称或 UUID 字符串解析 workspace，返回其 UUID。

    workspace_id 为空时解析到 "default" workspace（不存在则自动创建）。
    结果缓存 60 秒，减少高频请求对 DB 的重复查询。
    """
    if not workspace_id:
        workspace_id = "default"

    cached = _workspace_cache.get(workspace_id)
    if cached and (time.monotonic() - cached[1]) < _WORKSPACE_CACHE_TTL:
        return cached[0]

    try:
        ws_uuid = uuid.UUID(workspace_id)
        _workspace_cache[workspace_id] = (ws_uuid, time.monotonic())
        return ws_uuid
    except ValueError:
        pass

    result = await db.execute(select(Workspace).where(Workspace.name == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace is not None:
        _workspace_cache[workspace_id] = (workspace.id, time.monotonic())
        return workspace.id

    new_ws = Workspace(name=workspace_id)
    db.add(new_ws)
    await db.flush()
    _workspace_cache[workspace_id] = (new_ws.id, time.monotonic())
    return new_ws.id


_workspace_cache: dict[str, tuple[uuid.UUID, float]] = {}
_WORKSPACE_CACHE_TTL = 60.0


def invalidate_workspace_cache(name: str | None = None) -> None:
    """使 workspace 解析缓存失效；创建/删除 workspace 后调用。"""
    if name is None:
        _workspace_cache.clear()
    else:
        _workspace_cache.pop(name, None)
