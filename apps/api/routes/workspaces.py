"""Workspace CRUD 端点。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from apps.api.auth import AgentIdentity
from apps.api.deps import (
    get_current_agent,
    get_db,
    get_workspace,
    invalidate_workspace_cache,
    require_scope,
)
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import Workspace
from packages.domain.schemas import PaginatedResponse, WorkspaceCreate, WorkspaceRead

router = APIRouter(prefix=f"{API_V1_PREFIX}/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("workspaces:write"))] = None,
) -> WorkspaceRead:
    """创建 workspace，名称已存在（含并发竞争）时拒绝。"""
    by_name = select(Workspace.id).where(Workspace.name == body.name).limit(1)
    conflict = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "workspace_name_conflict", "name": body.name},
    )
    if await db.scalar(by_name) is not None:
        raise conflict

    workspace = Workspace(name=body.name)
    db.add(workspace)
    try:
        await db.flush()
    except IntegrityError as exc:
        # 唯一键冲突由并发创建触发：先回滚恢复事务，再复查确认竞争
        await db.rollback()
        if await db.scalar(by_name) is not None:
            raise conflict from exc
        raise
    await db.refresh(workspace)
    invalidate_workspace_cache(body.name)
    return WorkspaceRead.model_validate(workspace)


@router.get("", response_model=PaginatedResponse[WorkspaceRead])
async def list_workspaces(
    db: Annotated[AsyncSession, Depends(get_db)],
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[WorkspaceRead]:
    """分页列出全部 workspace。"""
    count_result = await db.execute(select(func.count(Workspace.id)))
    total = count_result.scalar() or 0

    # UUID 作为次级排序键打破时间戳并列，保证翻页时页内容稳定
    result = await db.execute(
        select(Workspace)
        .options(
            noload(Workspace.projects),
            noload(Workspace.agents),
            noload(Workspace.sessions),
        )
        .order_by(Workspace.created_at.desc(), Workspace.id)
        .offset(offset)
        .limit(limit)
    )
    workspaces = result.scalars().all()

    return PaginatedResponse(
        items=[WorkspaceRead.model_validate(w) for w in workspaces],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace_by_id(
    workspace: Annotated[Workspace, Depends(get_workspace)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> WorkspaceRead:
    """按 ID 获取 workspace。"""
    return WorkspaceRead.model_validate(workspace)
