"""事件接入端点——核心 API。

处理单条与批量事件接入，带幂等校验。事件按 Agent Event Protocol
v1 解析，敏感信息自动脱敏。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import (
    apply_optional_filters,
    execute_paginated,
    get_current_agent,
    get_db,
    require_scope,
    resolve_workspace,
)
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import Episode, Event, Session
from packages.domain.schemas import (
    BatchEventIngestResult,
    EventIngestResult,
    EventRead,
    PaginatedResponse,
)
from packages.domain.task_queue import queue
from packages.protocol.envelope import EventEnvelope, redact_envelope_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_V1_PREFIX}/events", tags=["events"])


class BatchEventIngest(BaseModel):
    """批量事件接入请求。"""

    events: list[EventEnvelope] = Field(..., min_length=1, max_length=50)


def _parse_uuid(value: str) -> uuid.UUID | None:
    """尝试把字符串解析为 UUID，失败返回 None。"""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


async def _process_single_event(
    envelope: EventEnvelope,
    db: AsyncSession,
) -> EventIngestResult:
    """处理单条事件，带幂等校验。"""
    agent_id = _parse_uuid(envelope.agent)
    session_id = _parse_uuid(envelope.session)
    workspace_id = _parse_uuid(envelope.workspace)

    if not agent_id or not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent and session are required and must be valid UUIDs",
        )

    if not workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace is required and must be a valid UUID",
        )

    existing_result = await db.execute(
        select(Event.id).where(
            Event.agent_id == agent_id,
            Event.session_id == session_id,
            Event.sequence == envelope.sequence,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing is not None:
        return EventIngestResult(
            accepted=True,
            duplicate=True,
            event_id=existing,
        )

    redacted_payload = redact_envelope_payload(envelope)

    event = Event(
        workspace_id=workspace_id,
        agent_id=agent_id,
        session_id=session_id,
        sequence=envelope.sequence,
        event_type=envelope.event_type,
        occurred_at=envelope.timestamp,
        payload=redacted_payload,
        source=envelope.metadata.get("source"),
    )
    db.add(event)
    await db.flush()

    return EventIngestResult(
        accepted=True,
        duplicate=False,
        event_id=event.id,
    )


@router.post("", response_model=EventIngestResult, status_code=status.HTTP_201_CREATED)
async def ingest_event(
    envelope: EventEnvelope,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("events:write"))] = None,
) -> EventIngestResult:
    """接入单条事件，带幂等校验。"""
    return await _process_single_event(envelope, db)


@router.post("/batch", response_model=BatchEventIngestResult, status_code=status.HTTP_201_CREATED)
async def ingest_batch(
    body: BatchEventIngest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("events:write"))] = None,
) -> BatchEventIngestResult:
    """批量接入事件（最多 50 条）。"""
    parsed: list[tuple[EventEnvelope, uuid.UUID, uuid.UUID, uuid.UUID]] = []
    for envelope in body.events:
        agent_id = _parse_uuid(envelope.agent)
        session_id = _parse_uuid(envelope.session)
        workspace_id = _parse_uuid(envelope.workspace)
        if not agent_id or not session_id or not workspace_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="agent, session, and workspace are required and must be valid UUIDs",
            )
        parsed.append((envelope, agent_id, session_id, workspace_id))

    session_ids = {p[2] for p in parsed}
    # 去重查询限定最近 24 小时，避免查询范围无限增长
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    stmt = select(Event.agent_id, Event.session_id, Event.sequence, Event.id).where(
        Event.session_id.in_(session_ids),
        Event.occurred_at >= cutoff,
    )
    result = await db.execute(stmt)
    existing_map: dict[tuple[str, str, int], uuid.UUID] = {}
    for agent_id, session_id, sequence, event_id in result.all():
        existing_map[(str(agent_id), str(session_id), sequence)] = event_id

    results: list[EventIngestResult] = []
    new_events: list[Event] = []
    # 记录新事件结果的下标，flush 后回填生成的 ID
    new_result_indices: list[int] = []
    for envelope, agent_id, session_id, workspace_id in parsed:
        key = (str(agent_id), str(session_id), envelope.sequence)
        if key in existing_map:
            results.append(
                EventIngestResult(
                    accepted=True,
                    duplicate=True,
                    event_id=existing_map[key],
                )
            )
        else:
            redacted_payload = redact_envelope_payload(envelope)
            event = Event(
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                sequence=envelope.sequence,
                event_type=envelope.event_type,
                occurred_at=envelope.timestamp,
                payload=redacted_payload,
                source=envelope.metadata.get("source"),
            )
            new_events.append(event)
            new_result_indices.append(len(results))
            results.append(
                EventIngestResult(
                    accepted=True,
                    duplicate=False,
                    event_id=None,  # flush 后回填
                )
            )

    if new_events:
        db.add_all(new_events)
        await db.flush()
        # 回填 flush 后生成的主键
        for idx, event in zip(new_result_indices, new_events):
            results[idx] = EventIngestResult(
                accepted=True,
                duplicate=False,
                event_id=event.id,
            )
        await db.commit()
        await _auto_trigger_episode(db, body.events)

    accepted_count = sum(1 for r in results if r.accepted)
    duplicate_count = sum(1 for r in results if r.duplicate)

    return BatchEventIngestResult(
        results=results,
        accepted_count=accepted_count,
        duplicate_count=duplicate_count,
    )


_EPISODE_TRIGGER_TYPES = {"session.ended", "context.compacted"}


async def _auto_trigger_episode(
    db: AsyncSession,
    envelopes: list[EventEnvelope],
) -> None:
    """会话收尾类事件接入时，入队 episode 收尾任务。"""
    trigger_sessions: dict[str, str] = {}
    for env in envelopes:
        if env.event_type in _EPISODE_TRIGGER_TYPES:
            key = f"{env.session}:{env.workspace}"
            if key not in trigger_sessions:
                trigger_sessions[key] = str(env.session)

    for key, session_id in trigger_sessions.items():
        workspace_id = key.split(":")[1]

        existing = await db.execute(
            select(Episode.id, Episode.status).where(Episode.session_id == uuid.UUID(session_id))
        )
        row = existing.one_or_none()
        if row is not None and row[1] in ("pending", "processing"):
            continue

        await queue.enqueue("finalize_episode", session_id, workspace_id)
        logger.info("Auto-triggered episode processing for session %s", session_id)


@router.get("/raw", response_model=list[dict[str, Any]])
async def get_raw_events_for_agent(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None,
        min_length=1,
        description="Workspace to query events from (optional, all workspaces if not specified)",
    ),
    session_id: uuid.UUID | None = Query(None, description="Filter by session"),
    event_type: str | None = Query(None, description="Filter by event type"),
    since_minutes: int = Query(60, ge=1, le=1440, description="Get events from last N minutes"),
    limit: int = Query(50, ge=1, le=200),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> list[dict[str, Any]]:
    """获取原始事件供 Agent 处理并提取有价值记忆。

    返回适合 LLM 处理的简化格式；Agent 可分析这些事件并把
    有价值的内容提交为候选记忆。
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None
    since_time = datetime.now(UTC) - timedelta(minutes=since_minutes)

    stmt = select(
        Event.id, Event.event_type, Event.occurred_at, Event.session_id, Event.payload
    ).where(Event.occurred_at >= since_time)

    if resolved_ws_id:
        stmt = stmt.where(Event.workspace_id == resolved_ws_id)

    if session_id:
        session_stmt = select(Session.id).where(Session.id == session_id)
        if resolved_ws_id:
            session_stmt = session_stmt.where(Session.workspace_id == resolved_ws_id)
        session_result = await db.execute(session_stmt)
        if session_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=404, detail="Event session not found in requested workspace"
            )
        stmt = stmt.where(Event.session_id == session_id)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)

    stmt = stmt.order_by(Event.occurred_at.desc()).limit(limit)

    result = await db.execute(stmt)
    rows = result.all()

    formatted_events = []
    for row in rows:
        event_id, event_type_val, occurred_at_val, session_id_val, payload = (
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
        )
        payload = payload or {}
        formatted_event = {
            "id": str(event_id),
            "event_type": event_type_val,
            "occurred_at": occurred_at_val.isoformat(),
            "session_id": str(session_id_val),
        }

        if event_type_val == "prompt.submitted":
            prompt = payload.get("prompt")
            formatted_event["content"] = prompt if isinstance(prompt, str) else ""
        elif event_type_val == "tool.failed":
            tool_name = payload.get("tool_name")
            error = payload.get("error")
            formatted_event["tool_name"] = tool_name if isinstance(tool_name, str) else ""
            formatted_event["error"] = error if isinstance(error, str) else ""
        elif event_type_val == "tool.completed":
            tool_name = payload.get("tool_name", "")
            tool_input = payload.get("tool_input", {})
            tool_output = payload.get("tool_response", {})

            formatted_event["tool_name"] = tool_name
            formatted_event["tool_input"] = _summarize_tool_input(tool_name, tool_input)
            formatted_event["tool_output_summary"] = _summarize_tool_output(tool_name, tool_output)
        else:
            formatted_event["payload_summary"] = _summarize_payload(payload)

        formatted_events.append(formatted_event)

    return formatted_events


def _summarize_tool_input(tool_name: str, tool_input: dict[str, Any]) -> str:
    """为 Agent 处理摘要工具输入。"""
    if tool_name == "Bash":
        return str(tool_input.get("command", ""))[:500]
    elif tool_name == "Write":
        path = str(tool_input.get("file_path", ""))
        content = str(tool_input.get("content", ""))
        return f"File: {path}\nContent preview: {content[:200]}..."
    elif tool_name == "Edit":
        path = str(tool_input.get("file_path", ""))
        old = str(tool_input.get("old_string", ""))[:100]
        new = str(tool_input.get("new_string", ""))[:100]
        return f"File: {path}\nOld: {old}...\nNew: {new}..."
    elif tool_name == "Read":
        return str(tool_input.get("file_path", ""))
    else:
        return str(tool_input)[:300]


def _summarize_tool_output(tool_name: str, tool_output: dict[str, Any] | list[Any]) -> str:
    """为 Agent 处理摘要工具输出。"""
    if isinstance(tool_output, list):
        if len(tool_output) > 0:
            first = tool_output[0]
            if isinstance(first, dict):
                kind = first.get("kind", "")
                content = first.get("content", "")
                if kind == "error":
                    return f"Error: {content[:300]}"
                return content[:300] if content else "No output"
        return "No output"

    kind = tool_output.get("kind", "")
    if tool_name == "Bash":
        stdout = tool_output.get("stdout", "")[:500]
        stderr = tool_output.get("stderr", "")[:200]
        exit_code = tool_output.get("exitCode", 0)
        summary = f"Exit code: {exit_code}"
        if stdout:
            summary += f"\nOutput: {stdout}"
        if stderr:
            summary += f"\nErrors: {stderr}"
        return summary
    elif tool_name in ("Write", "Edit"):
        return str(tool_output.get("message", "File operation completed"))
    elif kind == "error":
        return f"Error: {tool_output.get('content', '')[:300]}"
    else:
        content = tool_output.get("content", "")
        return content[:300] if content else "No output"


def _summarize_payload(payload: dict[str, Any]) -> str:
    """为 Agent 处理摘要通用 payload。"""
    parts = []
    for key, value in payload.items():
        if isinstance(value, str):
            parts.append(f"{key}: {value[:100]}")
        elif isinstance(value, (int, float, bool)):
            parts.append(f"{key}: {value}")
        elif isinstance(value, dict):
            parts.append(f"{key}: {{...}}")
        elif isinstance(value, list):
            parts.append(f"{key}: [{len(value)} items]")
    return "; ".join(parts)[:500]


@router.get("", response_model=PaginatedResponse[EventRead])
async def list_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    session_id: uuid.UUID | None = Query(None),
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    event_type: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[EventRead]:
    """列出事件，通常按 session_id 过滤。"""
    stmt = select(Event)
    count_stmt = select(func.count(Event.id))

    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None

    conditions = []
    if session_id:
        conditions.append(Event.session_id == session_id)
    if resolved_ws_id:
        conditions.append(Event.workspace_id == resolved_ws_id)
    if event_type:
        conditions.append(Event.event_type == event_type)
    stmt, count_stmt = apply_optional_filters(stmt, count_stmt, conditions)

    total, events = await execute_paginated(
        db, stmt, count_stmt, Event.sequence.asc(), offset, limit
    )

    return PaginatedResponse(
        items=[EventRead.model_validate(e) for e in events],
        total=total,
        offset=offset,
        limit=limit,
    )
