"""Workspace CRUD 端点。"""

import re
import uuid
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Row, func, select
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
from apps.api.file_sync import sync_memory_to_file
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import Memory, SessionNote, Workspace
from packages.domain.paths import validate_path_component
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


@router.get("/default", response_model=WorkspaceRead)
async def get_default_workspace(
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> WorkspaceRead:
    """返回默认工作区：active 记忆最多者，并列取最近有记忆更新。

    /workspaces 列表按创建时间倒序，列表第一项是最新创建的工作区，
    往往没有数据——前端曾把它当默认工作区导致复习页与仪表盘全零。
    """
    stmt = (
        select(Workspace)
        .outerjoin(Memory, (Memory.workspace_id == Workspace.id) & (Memory.status == "active"))
        .group_by(Workspace.id)
        .order_by(
            func.count(Memory.id).desc(),
            func.max(Memory.updated_at).desc().nulls_last(),
            # UUID 次级排序键打破时间戳并列，保证结果稳定（与列表端点约定一致）
            Workspace.created_at.desc(),
            Workspace.id,
        )
        .limit(1)
    )
    workspace = (await db.execute(stmt)).scalars().first()
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "no_workspaces"})
    return WorkspaceRead.model_validate(workspace)


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace_by_id(
    workspace: Annotated[Workspace, Depends(get_workspace)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> WorkspaceRead:
    """按 ID 获取 workspace。"""
    return WorkspaceRead.model_validate(workspace)


# ---------------------------------------------------------------------------
# 工作区治理：归并与清理历史脏工作区（哈希名 / 路径编码名）
# ---------------------------------------------------------------------------

# 一次性脏名模式：8 位十六进制哈希（179cf7e8…）与路径编码（C--Users-…）
_DIRTY_NAME_RE = re.compile(r"^([0-9a-f]{8}|[A-Za-z]--[A-Za-z0-9._-]*)$")


def _is_dirty_name(name: str) -> bool:
    return bool(_DIRTY_NAME_RE.fullmatch(name))


@router.get("/hygiene/preview")
async def workspace_hygiene_preview(
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """预览可治理的脏工作区：哈希名/路径编码名，及其记忆与笔记计数。

    只读操作；`POST /workspaces/hygiene/merge` 才执行归并。
    """
    rows = (
        await db.execute(
            select(
                Workspace,
                func.count(func.distinct(Memory.id)),
            )
            .outerjoin(Memory, Memory.workspace_id == Workspace.id)
            .group_by(Workspace.id)
        )
    ).all()

    rows_note: Sequence[Row[tuple[uuid.UUID, int]]] = (
        await db.execute(
            select(SessionNote.workspace_id, func.count(SessionNote.id)).group_by(
                SessionNote.workspace_id
            )
        )
    ).all()
    note_counts: dict[uuid.UUID, int] = {ws_id: cnt for ws_id, cnt in rows_note}

    dirty = []
    for ws, memory_count in rows:
        if not _is_dirty_name(ws.name):
            continue
        dirty.append(
            {
                "id": str(ws.id),
                "name": ws.name,
                "memories": memory_count,
                "notes": note_counts.get(ws.id, 0),
            }
        )
    dirty.sort(key=lambda item: item["name"])
    return {"workspaces": dirty, "total": len(dirty)}


class WorkspaceMergeRequest(BaseModel):
    source_workspace_id: str
    target_workspace_id: str


@router.post("/hygiene/merge")
async def workspace_hygiene_merge(
    body: WorkspaceMergeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("workspaces:write"))] = None,
) -> dict[str, Any]:
    """把一个工作区归并进另一个（记忆/笔记迁移 + 源工作区删除）。

    典型用途：清理历史脏名工作区（哈希名/路径编码名）。
    - 源工作区必须为空或显式确认迁移；目标工作区不存在时按名创建。
    - 记忆迁移：逐条改 workspace_id 并同步 MD 镜像（跨目录移动）。
    - 笔记迁移：批量改 workspace_id。
    - 源工作区下无任何记忆/笔记/会话后删除（有会话则一并迁移）。
    """
    from packages.domain.models import AgentSession

    if body.source_workspace_id == body.target_workspace_id:
        raise HTTPException(status_code=400, detail="source and target are the same workspace")

    source_id = await resolve_workspace_by_ref(body.source_workspace_id, db)
    target_id = await resolve_workspace_by_ref(body.target_workspace_id, db)

    # 迁移记忆（含 MD 镜像与向量索引；archived 一并带走）
    memories = (
        (await db.execute(select(Memory).where(Memory.workspace_id == source_id))).scalars().all()
    )
    for memory in memories:
        memory.workspace_id = target_id
    await db.flush()
    for memory in memories:
        await sync_memory_to_file(memory, db, skip_vector_index=True, save_index=True)

    # 迁移笔记与会话；两模型都有 workspace_id，分别查询避免 select(联合类型) 窄化失败
    note_rows = (
        (await db.execute(select(SessionNote).where(SessionNote.workspace_id == source_id)))
        .scalars()
        .all()
    )
    for row in note_rows:
        row.workspace_id = target_id
    session_rows = (
        (await db.execute(select(AgentSession).where(AgentSession.workspace_id == source_id)))
        .scalars()
        .all()
    )
    for sess in session_rows:
        sess.workspace_id = target_id
    await db.flush()

    # 源工作区已空 → 删除
    source = await db.get(Workspace, source_id)
    if source is not None:
        await db.delete(source)
    invalidate_workspace_cache(source.name if source else None)
    invalidate_workspace_cache()
    await db.commit()
    return {
        "source_workspace_id": str(source_id),
        "target_workspace_id": str(target_id),
        "memories_moved": len(memories),
    }


async def resolve_workspace_by_ref(ref: str, db: AsyncSession) -> uuid.UUID:
    """按名称或 UUID 解析工作区；目标不存在时自动创建（名称合法性复用校验器）。"""
    try:
        return uuid.UUID(ref)
    except ValueError:
        pass
    ws = (await db.execute(select(Workspace).where(Workspace.name == ref))).scalar_one_or_none()
    if ws is not None:
        return ws.id
    validate_path_component(ref)
    new_ws = Workspace(name=ref)
    db.add(new_ws)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "workspace_name_conflict", "name": ref}
        ) from exc
    invalidate_workspace_cache(ref)
    return new_ws.id
