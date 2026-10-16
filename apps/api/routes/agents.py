"""Agent CRUD 端点。"""

from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from packages.domain.config import API_V1_PREFIX, parasitic_evolution_config
from packages.domain.models import Agent, AgentProfile
from packages.domain.schemas import (
    AgentCreate,
    AgentProfileRead,
    AgentProfileUpdate,
    AgentRead,
    PaginatedResponse,
)

router = APIRouter(prefix=f"{API_V1_PREFIX}/agents", tags=["agents"])


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def register_agent(
    body: AgentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("agents:write"))] = None,
) -> AgentRead:
    """在工作区中注册一个新 Agent。"""
    agent = Agent(
        workspace_id=body.workspace_id,
        name=body.name,
        type=body.type,
        adapter=body.adapter,
        version=body.version,
        capabilities=body.capabilities,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return AgentRead.model_validate(agent)


@router.get("", response_model=PaginatedResponse[AgentRead])
async def list_agents(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[AgentRead]:
    """列出 Agent，可按 workspace 过滤。"""
    stmt = select(Agent)
    count_stmt = select(func.count(Agent.id))

    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    conditions = []
    if resolved_ws_id:
        conditions.append(Agent.workspace_id == resolved_ws_id)
    stmt, count_stmt = apply_optional_filters(stmt, count_stmt, conditions)

    total, agents = await execute_paginated(
        db, stmt, count_stmt, Agent.created_at.desc(), offset, limit
    )

    return PaginatedResponse(
        items=[AgentRead.model_validate(a) for a in agents],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> AgentRead:
    """按 ID 获取 Agent。"""
    agent = await get_or_404(db, Agent, agent_id)
    return AgentRead.model_validate(agent)


# ---------------------------------------------------------------------------
# Agent Profile（寄生演化功能，P4-41）
# ---------------------------------------------------------------------------


@router.get("/profiles/{workspace_id}/{agent_id}", response_model=AgentProfileRead)
async def get_agent_profile(
    workspace_id: str,
    agent_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> AgentProfileRead:
    if not parasitic_evolution_config.agent_profile_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent profile disabled")

    result = await db.execute(
        select(AgentProfile).where(
            AgentProfile.workspace_id == workspace_id,
            AgentProfile.agent_id == agent_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile for agent {agent_id} in workspace {workspace_id} not found",
        )
    return AgentProfileRead.from_orm_with_json(profile)


@router.put("/profiles/{workspace_id}/{agent_id}", response_model=AgentProfileRead)
async def update_agent_profile(
    workspace_id: str,
    agent_id: str,
    body: AgentProfileUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("agents:write"))] = None,
) -> AgentProfileRead:
    if not parasitic_evolution_config.agent_profile_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent profile disabled")

    result = await db.execute(
        select(AgentProfile).where(
            AgentProfile.workspace_id == workspace_id,
            AgentProfile.agent_id == agent_id,
        )
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = AgentProfile(workspace_id=workspace_id, agent_id=agent_id)
        db.add(profile)

    update_data = body.model_dump(exclude_unset=True)
    json_list_fields = ["preferred_signal_types", "preferred_memory_types", "preferred_nudge_types"]
    for field, value in update_data.items():
        if field in json_list_fields and value is not None:
            setattr(profile, field, json.dumps(value))
        elif value is not None:
            setattr(profile, field, value)

    await db.flush()
    await db.refresh(profile)
    return AgentProfileRead.from_orm_with_json(profile)
