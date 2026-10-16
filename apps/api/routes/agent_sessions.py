"""Agent 会话端点（EPIC-03）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import (
    apply_optional_filters,
    execute_paginated,
    get_current_agent,
    get_db,
    get_or_404,
    require_scope,
    resolve_workspace,
)
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import (
    Agent,
    AgentSession,
    CandidateMemory,
    MemoryLifecycleEvent,
    Session,
)
from packages.domain.schemas import (
    AgentSessionComplete,
    AgentSessionCreate,
    AgentSessionRead,
    PaginatedResponse,
    SessionCreate,
    SessionRead,
)

router = APIRouter(prefix=API_V1_PREFIX, tags=["agent-sessions"])


async def _get_or_create_agent(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    agent_name: str,
) -> uuid.UUID:
    """查找或创建用于事件采集的 Agent 记录（事件上报无需预先注册）。"""
    result = await db.execute(
        select(Agent.id).where(
            Agent.workspace_id == workspace_id,
            Agent.name == agent_name,
        )
    )
    agent_id = result.scalar_one_or_none()
    if agent_id:
        return agent_id

    agent = Agent(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name=agent_name,
        type="coding_agent",
        adapter="generic",
    )
    db.add(agent)
    await db.flush()
    return agent.id


async def _create_event_session(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    external_session_id: str,
) -> uuid.UUID:
    """为事件采集创建底层 Session 记录。"""
    session = Session(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        agent_id=agent_id,
        external_session_id=external_session_id,
    )
    db.add(session)
    await db.flush()
    return session.id


@router.post("/agent-sessions", response_model=AgentSessionRead, status_code=201)
async def create_agent_session(
    body: AgentSessionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("sessions:write"))] = None,
) -> AgentSessionRead:
    resolved_ws_id = await resolve_workspace(body.workspace_id, db)
    agent_id = await _get_or_create_agent(db, resolved_ws_id, body.agent)

    external_session_id = f"agent-session-{uuid.uuid4()}"
    event_session_id = await _create_event_session(
        db, resolved_ws_id, agent_id, external_session_id
    )

    session = AgentSession(
        id=uuid.uuid4(),
        workspace_id=resolved_ws_id,
        agent=body.agent,
        agent_version=body.agent_version,
        repository=body.repository,
        branch=body.branch,
        task=body.task,
        event_session_id=event_session_id,
        metadata_=body.metadata,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return AgentSessionRead.model_validate(session)


@router.post(
    "/agent-sessions/{session_id}/complete",
    response_model=AgentSessionRead,
)
async def complete_agent_session(
    session_id: uuid.UUID,
    body: AgentSessionComplete,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("sessions:write"))] = None,
) -> AgentSessionRead:
    session = await get_or_404(db, AgentSession, session_id)

    session.ended_at = datetime.now(UTC)
    session.outcome = body.outcome
    if body.metadata:
        existing = session.metadata_ or {}
        existing.update(body.metadata)
        session.metadata_ = existing

    await db.commit()
    await db.refresh(session)
    return AgentSessionRead.model_validate(session)


@router.get("/agent-sessions/stats")
async def get_agent_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = None,
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """基于会话与事件计算每个 Agent 的统计数据。"""
    from sqlalchemy import case

    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    stmt = select(
        AgentSession.agent,
        func.count(AgentSession.id).label("total_sessions"),
        func.sum(case((AgentSession.outcome == "success", 1), else_=0)).label("success_count"),
        func.max(AgentSession.started_at).label("last_seen_at"),
        func.avg(
            case(
                (
                    AgentSession.ended_at.is_not(None),
                    func.julianday(AgentSession.ended_at) - func.julianday(AgentSession.started_at),
                ),
            )
        ).label("avg_days"),
    ).group_by(AgentSession.agent)
    if resolved_ws_id:
        stmt = stmt.where(AgentSession.workspace_id == resolved_ws_id)

    result = await db.execute(stmt)
    agents: dict[str, dict[str, Any]] = {}
    for row in result.all():
        avg_days = row[4] or 0
        agents[row[0]] = {
            "total_sessions": row[1],
            "success_count": row[2] or 0,
            "last_seen_at": row[3].isoformat() if row[3] else None,
            "avg_duration_ms": round(float(avg_days) * 86_400_000),
            "memory_count": 0,  # 稍后统计
        }

    # 统计各 Agent 会话时间窗口内创建的记忆数（归因到会话区间而非精确时间戳）
    if agents:
        memory_events = await db.execute(
            select(MemoryLifecycleEvent.memory_id, MemoryLifecycleEvent.created_at).where(
                MemoryLifecycleEvent.event_type == "created"
            )
        )
        memory_times = memory_events.all()

        for agent_name, agent_stats in agents.items():
            agent_sessions_stmt = select(AgentSession.started_at, AgentSession.ended_at).where(
                AgentSession.agent == agent_name
            )
            if resolved_ws_id:
                agent_sessions_stmt = agent_sessions_stmt.where(
                    AgentSession.workspace_id == resolved_ws_id
                )
            sessions_result = await db.execute(agent_sessions_stmt)
            session_windows = [
                (s[0], s[1] or datetime.now(UTC)) for s in sessions_result.all() if s[0]
            ]

            count = 0
            for mem_id, mem_time in memory_times:
                if any(start <= mem_time <= end for start, end in session_windows):
                    count += 1
            agent_stats["memory_count"] = count

    memory_stmt = select(func.count(CandidateMemory.id))
    if resolved_ws_id:
        memory_stmt = memory_stmt.where(CandidateMemory.workspace_id == resolved_ws_id)

    total_memory = await db.scalar(memory_stmt) or 0

    return {"agents": agents, "total_memory_submissions": total_memory}


@router.get("/agent-sessions/{session_id}", response_model=AgentSessionRead)
async def get_agent_session(
    session_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> AgentSessionRead:
    session = await get_or_404(db, AgentSession, session_id)
    return AgentSessionRead.model_validate(session)


@router.get("/agent-sessions", response_model=PaginatedResponse[AgentSessionRead])
async def list_agent_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = None,
    agent: str | None = None,
    outcome: str | None = None,
    open_only: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[AgentSessionRead]:
    stmt = select(AgentSession)
    count_stmt = select(func.count(AgentSession.id))

    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    conditions = []
    if resolved_ws_id:
        conditions.append(AgentSession.workspace_id == resolved_ws_id)
    if agent:
        conditions.append(AgentSession.agent == agent)
    if outcome:
        conditions.append(AgentSession.outcome == outcome)
    if open_only:
        conditions.append(AgentSession.outcome.is_(None))
    if since:
        conditions.append(AgentSession.started_at >= since)
    if until:
        conditions.append(AgentSession.started_at <= until)
    stmt, count_stmt = apply_optional_filters(stmt, count_stmt, conditions)

    total, sessions = await execute_paginated(
        db, stmt, count_stmt, AgentSession.started_at.desc(), offset, limit
    )

    return PaginatedResponse(
        items=[AgentSessionRead.model_validate(s) for s in sessions],
        total=total,
        offset=offset,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# 底层 Session CRUD（原 sessions.py）
# ---------------------------------------------------------------------------


@router.post("/sessions", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> SessionRead:
    """注册新会话。"""
    session = Session(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        project_id=body.project_id,
        external_session_id=body.external_session_id,
        cwd=body.cwd,
        metadata_=body.metadata,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return SessionRead.model_validate(session)


@router.get("/sessions", response_model=PaginatedResponse[SessionRead])
async def list_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    agent_id: uuid.UUID | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[SessionRead]:
    """列出会话，支持可选过滤。"""
    stmt = select(Session)
    count_stmt = select(func.count(Session.id))

    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    conditions = []
    if resolved_ws_id:
        conditions.append(Session.workspace_id == resolved_ws_id)
    if agent_id:
        conditions.append(Session.agent_id == agent_id)
    if project_id:
        conditions.append(Session.project_id == project_id)
    stmt, count_stmt = apply_optional_filters(stmt, count_stmt, conditions)

    total, sessions = await execute_paginated(
        db, stmt, count_stmt, Session.created_at.desc(), offset, limit
    )

    return PaginatedResponse(
        items=[SessionRead.model_validate(s) for s in sessions],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/sessions/{session_id}", response_model=SessionRead)
async def get_session(
    session_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> SessionRead:
    """按 ID 获取会话。"""
    session = await get_or_404(db, Session, session_id)
    return SessionRead.model_validate(session)
