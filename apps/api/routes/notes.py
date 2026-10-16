"""会话笔记端点（P1——两阶段提交）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import (
    execute_paginated,
    get_current_agent,
    get_db,
    get_or_404,
    require_scope,
    resolve_workspace,
)
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import SessionNote
from packages.domain.schemas import (
    PaginatedResponse,
    SessionNoteCreate,
    SessionNoteRead,
)

router = APIRouter(prefix=API_V1_PREFIX, tags=["session-notes"])


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
    )
    db.add(note)
    await db.flush()
    await db.refresh(note)
    return SessionNoteRead.model_validate(note)


@router.get("/session-notes", response_model=PaginatedResponse[SessionNoteRead])
async def list_session_notes(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    session_id: uuid.UUID | None = Query(None),
    formalized: bool | None = Query(None),
    signal_type: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[SessionNoteRead]:
    if not workspace_id and not session_id:
        raise HTTPException(status_code=400, detail="workspace_id or session_id is required")

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

    stmt = select(SessionNote).where(*conditions)
    count_stmt = select(func.count(SessionNote.id)).where(*conditions)

    total, notes = await execute_paginated(
        db, stmt, count_stmt, SessionNote.created_at.desc(), offset, limit
    )

    return PaginatedResponse(
        items=[SessionNoteRead.model_validate(n) for n in notes],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch("/session-notes/{note_id}/formalize", response_model=SessionNoteRead)
async def formalize_note(
    note_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    memory_id: uuid.UUID | None = Body(None, embed=True),
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("notes:write"))] = None,
) -> SessionNoteRead:
    note = await get_or_404(db, SessionNote, note_id)

    note.formalized = True
    if memory_id:
        note.formalized_memory_id = memory_id

    await db.flush()
    await db.refresh(note)
    return SessionNoteRead.model_validate(note)


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
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = select(SessionNote).where(*base_conditions)
    stmt = stmt.order_by(SessionNote.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    notes = result.scalars().all()

    return {
        "items": [SessionNoteRead.model_validate(n).model_dump() for n in notes],
        "total": total,
        "offset": offset,
        "limit": limit,
    }
