"""FastAPI 依赖注入。"""

from __future__ import annotations

import hmac
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Sequence
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from packages.domain.config import settings
from packages.domain.database import async_session_maker
from packages.domain.models import Workspace
from packages.domain.paths import validate_path_component
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


async def get_current_agent(request: Request) -> AgentIdentity:
    """校验 Bearer token 并返回本地 Agent 身份。

    app.auth_token 未配置（默认）时保持单用户本地零鉴权体验；
    配置后要求 `Authorization: Bearer <token>`，不匹配返回 401。
    每次请求实时读 settings，支持 config 热更新后立即生效。
    """
    token = settings.api_auth_token
    if not token:
        return _DEFAULT_IDENTITY

    auth_header = request.headers.get("Authorization", "")
    supplied = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    # 常数时间比较，避免逐字节短路泄露 token 前缀
    if supplied and hmac.compare_digest(supplied, token):
        return _DEFAULT_IDENTITY

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing Authorization bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_scope(required_scope: str) -> Callable[..., Any]:
    """要求已鉴权身份；scope 目前仅声明，细粒度权限暂不做。

    鉴权本身由 get_current_agent 完成（配置 app.auth_token 后生效），
    此依赖仅保留 scope 声明注入点。
    """

    async def _check(
        agent: Annotated[AgentIdentity, Depends(get_current_agent)],
    ) -> AgentIdentity:
        return agent

    return _check


async def get_or_404(
    db: AsyncSession,
    model: type[Any],
    id_value: Any,
    detail: str | None = None,
    options: Sequence[Any] | None = None,
) -> Any:
    """按 ID 获取模型实例，不存在则抛 HTTP 404。

    *options* 接受 SQLAlchemy 加载选项（如 ``defer(Memory.embedding)``），
    避免加载大字段；关联关系默认 lazy="raise"，不会隐式加载。
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
    if isinstance(order_by, (list, tuple)):
        stmt = stmt.order_by(*order_by)
    else:
        stmt = stmt.order_by(order_by)
    data_result = await db.execute(stmt.offset(offset).limit(limit))
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
    *,
    allow_create: bool | None = None,
) -> uuid.UUID:
    """按名称或 UUID 字符串解析 workspace，返回其 UUID。

    workspace_id 为空时解析到 "default" workspace（不存在则自动创建）。
    结果缓存 60 秒，减少高频请求对 DB 的重复查询。

    名称会直接用作 Markdown 文件的路径组件：自动创建新工作区前必须通过
    validate_path_component，否则会出现"DB 有行、MD 永远写不出去、且经
    _workspaces.json 随重建复活"的三层存储永久不对称（400 拒绝）。
    已存在的工作区不复查名称——历史脏名行仍可读写，由 /workspaces/hygiene 治理。

    *allow_create*：未知名称是否自动建区。默认取 ``memory.auto_create_workspace``；
    机器来源（hook 捕获，名称由 cwd 派生）显式传 True，避免新项目丢采集数据。
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

    try:
        validate_path_component(workspace_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_workspace_name", "name": workspace_id, "reason": str(exc)},
        ) from exc

    if allow_create is None:
        allow_create = settings.auto_create_workspace
    if not allow_create and workspace_id != "default":
        # 拼写错误/历史脏名不再静默建区（曾出现 18 个区仅 7 个有记忆）
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unknown_workspace",
                "name": workspace_id,
                "hint": (
                    "工作区不存在。请先在 Web 控制台或 POST /v1/workspaces 创建，"
                    "或确认 workspace_name 与项目目录名一致。"
                ),
            },
        )

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
