"""会话笔记端点（P1——两阶段提交）。

内容完整性约定：
- 数据库存全文，不在捕获阶段摘要化或截断；
- 列表默认返回 ``content_preview``，详情 ``GET /session-notes/{id}`` 返回全文；
- 内部消费者（checkpoint 等）可用 ``view=full`` 拉全文，保持向后兼容。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import (
    get_current_agent,
    get_db,
    get_or_404,
    require_scope,
    resolve_workspace,
)
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import AgentSession, SessionNote, Workspace
from packages.domain.schemas import (
    PaginatedResponse,
    SessionNoteCreate,
    SessionNoteFormalize,
    SessionNoteRead,
)

router = APIRouter(prefix=API_V1_PREFIX, tags=["session-notes"])

PREVIEW_CHARS = 280


def _preview(content: str, limit: int = PREVIEW_CHARS) -> str:
    """生成列表预览；只用于展示，不改变入库全文。"""
    text = " ".join(content.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _note_read(
    note: SessionNote,
    *,
    host: str | None,
    workspace_name: str | None,
    include_content: bool,
) -> SessionNoteRead:
    return SessionNoteRead(
        id=note.id,
        session_id=note.session_id,
        workspace_id=note.workspace_id,
        content=note.content if include_content else None,
        content_preview=_preview(note.content),
        content_length=len(note.content),
        signal_type=note.signal_type,
        formalized=note.formalized,
        formalized_memory_id=note.formalized_memory_id,
        candidate_id=note.candidate_id,
        discarded_at=note.discarded_at,
        host=host,
        workspace_name=workspace_name,
        created_at=note.created_at,
    )


@router.post("/session-notes", response_model=SessionNoteRead, status_code=201)
async def create_session_note(
    body: SessionNoteCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    session_id: uuid.UUID = Query(..., description="Agent session ID"),
    workspace_id: str = Query(..., min_length=1, description="工作区（名称或 UUID）"),
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("notes:write"))] = None,
) -> SessionNoteRead:
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    note = SessionNote(
        id=uuid.uuid4(),
        session_id=session_id,
        workspace_id=resolved_ws_id,
        content=body.content,
        signal_type=body.signal_type,
        candidate_id=body.candidate_id,
    )
    db.add(note)
    await db.flush()
    await db.refresh(note)

    host: str | None = None
    workspace_name: str | None = None
    session = await db.get(AgentSession, session_id)
    if session is not None:
        host = session.agent
    ws = await db.get(Workspace, resolved_ws_id)
    if ws is not None:
        workspace_name = ws.name
    return _note_read(note, host=host, workspace_name=workspace_name, include_content=True)


@router.get("/session-notes", response_model=PaginatedResponse[SessionNoteRead])
async def list_session_notes(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    session_id: uuid.UUID | None = Query(None),
    formalized: bool | None = Query(None),
    signal_type: str | None = Query(None),
    include_discarded: bool = Query(False, description="是否包含已丢弃的笔记"),
    view: Literal["preview", "full"] = Query(
        "preview",
        description="preview 只返回预览；full 返回全文（内部消费者使用）",
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[SessionNoteRead]:
    if not workspace_id and not session_id:
        # 收件箱视图（全部工作区的待整理）必须可用：两个过滤都不传
        # 时不报错，返回全部工作区的笔记。API 保留 workspace_id/session_id
        # 作为可选过滤器，与 capture 统计口径一致。
        pass

    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    conditions = []
    if resolved_ws_id is not None:
        conditions.append(SessionNote.workspace_id == resolved_ws_id)
    if session_id is not None:
        conditions.append(SessionNote.session_id == session_id)
    if formalized is not None:
        conditions.append(SessionNote.formalized == formalized)
    if signal_type:
        conditions.append(SessionNote.signal_type == signal_type)
    if not include_discarded:
        conditions.append(SessionNote.discarded_at.is_(None))

    count_stmt = select(func.count(SessionNote.id)).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(SessionNote, AgentSession.agent, Workspace.name)
        .outerjoin(AgentSession, SessionNote.session_id == AgentSession.id)
        .outerjoin(Workspace, SessionNote.workspace_id == Workspace.id)
        .where(*conditions)
        .order_by(SessionNote.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    items = [
        _note_read(
            note,
            host=host,
            workspace_name=workspace_name,
            include_content=view == "full",
        )
        for note, host, workspace_name in rows
    ]

    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/session-notes/search")
async def search_session_notes(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str = Query(..., min_length=1, description="工作区（名称或 UUID）"),
    q: str = Query(..., min_length=1),
    signal_type: str | None = Query(None),
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    q_escaped = q.replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{q_escaped}%"

    base_conditions = [
        SessionNote.workspace_id == resolved_ws_id,
        SessionNote.created_at >= cutoff,
        SessionNote.content.like(pattern, escape="\\"),
    ]
    if signal_type:
        base_conditions.append(SessionNote.signal_type == signal_type)

    count_stmt = select(func.count(SessionNote.id)).where(*base_conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(SessionNote, AgentSession.agent, Workspace.name)
        .outerjoin(AgentSession, SessionNote.session_id == AgentSession.id)
        .outerjoin(Workspace, SessionNote.workspace_id == Workspace.id)
        .where(*base_conditions)
        .order_by(SessionNote.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    return {
        "items": [
            _note_read(
                note, host=host, workspace_name=workspace_name, include_content=True
            ).model_dump()
            for note, host, workspace_name in rows
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/session-notes/{note_id}", response_model=SessionNoteRead)
async def get_session_note(
    note_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> SessionNoteRead:
    note = await get_or_404(db, SessionNote, note_id)
    session = await db.get(AgentSession, note.session_id)
    ws = await db.get(Workspace, note.workspace_id)
    return _note_read(
        note,
        host=session.agent if session else None,
        workspace_name=ws.name if ws else None,
        include_content=True,
    )


@router.patch("/session-notes/{note_id}/formalize", response_model=SessionNoteRead)
async def formalize_note(
    note_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: SessionNoteFormalize | None = Body(None),
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("notes:write"))] = None,
) -> SessionNoteRead:
    note = await get_or_404(db, SessionNote, note_id)

    note.formalized = True
    if body is not None:
        if body.candidate_id is not None:
            note.candidate_id = body.candidate_id
        if body.memory_id is not None:
            note.formalized_memory_id = body.memory_id

    await db.flush()
    await db.refresh(note)

    session = await db.get(AgentSession, note.session_id)
    ws = await db.get(Workspace, note.workspace_id)
    return _note_read(
        note,
        host=session.agent if session else None,
        workspace_name=ws.name if ws else None,
        include_content=True,
    )


@router.delete("/session-notes/{note_id}", status_code=204)
async def discard_note(
    note_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("notes:write"))] = None,
) -> None:
    """软删除笔记：标记 discarded_at，不在列表显示。"""
    note = await get_or_404(db, SessionNote, note_id)
    note.discarded_at = datetime.now(UTC)
    await db.flush()
