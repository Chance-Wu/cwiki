"""宿主无关的 Agent 捕获端点。

Agent 侧（hook / 脚本 / 自研集成）只需把结构化事件提交到这里，cwiki 负责：
- 按 host + workspace + 宿主 session_id 幂等创建 AgentSession；
- 把 compact summary / tool failure 存为完整 SessionNote（供收件箱整理）；
- 用确定性 UUID 去重，重复投递不产生重复笔记。

这里不做摘要化、不读 transcript、不调用 LLM；内容完整性由调用方和
``AgentCaptureRecord.content`` 的全文语义共同保证。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, require_scope, resolve_workspace
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import AgentSession, SessionNote
from packages.domain.schemas import (
    AgentCaptureRecord,
    AgentCaptureRejected,
    AgentCaptureRequest,
    AgentCaptureResponse,
    AgentCaptureStats,
)

router = APIRouter(prefix=f"{API_V1_PREFIX}/integrations/agent", tags=["agent-capture"])

_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# 拒绝 Windows 路径编码形态（C--Users-... / E--IdeaProjects-...）：这类名字
# 是“把路径直接当 workspace”留下的脏数据，不应再被自动创建。
_PATH_LIKE_RE = re.compile(r"^[A-Za-z]--")
_DEFAULT_SIGNAL = {
    "compact_summary": "session_snapshot",
    "tool_failure": "issue",
    "session_end": "other",
}


def _session_uuid(host: str, workspace: str, session_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"cwiki:{host}:{workspace}:{session_id}")


def _record_key(record: AgentCaptureRecord) -> str:
    if record.record_id:
        return record.record_id
    raw = "|".join(
        (
            record.kind,
            record.session_id,
            record.workspace,
            record.content,
            record.occurred_at.isoformat() if record.occurred_at else "",
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _note_uuid(host: str, key: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"cwiki:{host}:note:{key}")


@router.post("/capture", response_model=AgentCaptureResponse, status_code=201)
async def capture_agent_records(
    body: AgentCaptureRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("notes:write"))] = None,
) -> AgentCaptureResponse:
    accepted = 0
    duplicates = 0
    rejected: list[AgentCaptureRejected] = []
    note_ids: list[uuid.UUID] = []
    first_session_id: uuid.UUID | None = None

    for record in body.records:
        key = _record_key(record)
        if not _WORKSPACE_RE.fullmatch(record.workspace) or _PATH_LIKE_RE.match(record.workspace):
            rejected.append(
                AgentCaptureRejected(
                    record_id=key,
                    reason="workspace 名称非法：只允许字母、数字、点、下划线、连字符，"
                    "且不接受路径编码形态",
                )
            )
            continue

        resolved_ws_id = await resolve_workspace(record.workspace, db)
        session_id = _session_uuid(body.host, record.workspace, record.session_id)
        if first_session_id is None:
            first_session_id = session_id

        session = await db.get(AgentSession, session_id)
        if session is None:
            session = AgentSession(
                id=session_id,
                workspace_id=resolved_ws_id,
                agent=body.host,
                started_at=record.occurred_at or datetime.now(UTC),
                metadata_={
                    "host_session_id": record.session_id,
                    "cwd": record.cwd,
                    "source": "capture",
                },
            )
            db.add(session)
            await db.flush()
        elif record.cwd and not (session.metadata_ or {}).get("cwd"):
            session.metadata_ = {**(session.metadata_ or {}), "cwd": record.cwd}

        if record.kind == "session_end":
            session.ended_at = record.occurred_at or datetime.now(UTC)
            session.outcome = "unknown"
            if record.content:
                session.metadata_ = {
                    **(session.metadata_ or {}),
                    "end_reason": record.content[:200],
                }
            accepted += 1
            continue

        content = record.content.strip()
        if not content:
            rejected.append(AgentCaptureRejected(record_id=key, reason="content 为空"))
            continue

        note_id = _note_uuid(body.host, key)
        existing = await db.get(SessionNote, note_id)
        if existing is not None:
            duplicates += 1
            continue

        note = SessionNote(
            id=note_id,
            session_id=session_id,
            workspace_id=resolved_ws_id,
            content=content,
            signal_type=record.signal_type
            if record.signal_type != "other"
            else _DEFAULT_SIGNAL[record.kind],
            created_at=record.occurred_at or datetime.now(UTC),
        )
        db.add(note)
        note_ids.append(note_id)
        accepted += 1

    await db.flush()
    if accepted:
        from apps.api.routes.memory_status import invalidate_memory_status_caches

        invalidate_memory_status_caches()
    return AgentCaptureResponse(
        host=body.host,
        accepted=accepted,
        duplicates=duplicates,
        rejected=rejected,
        session_id=first_session_id,
        note_ids=note_ids,
    )


@router.get("/stats", response_model=AgentCaptureStats)
async def capture_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    host: str | None = Query(None, pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$"),
    workspace_id: str | None = Query(None, min_length=1),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> AgentCaptureStats:
    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None
    session_conditions = []
    if host:
        session_conditions.append(AgentSession.agent == host)
    if resolved_ws_id:
        session_conditions.append(AgentSession.workspace_id == resolved_ws_id)

    sessions = (
        await db.execute(select(func.count(AgentSession.id)).where(*session_conditions))
    ).scalar() or 0

    note_conditions = []
    if host:
        note_conditions.append(AgentSession.agent == host)
    if resolved_ws_id:
        note_conditions.append(SessionNote.workspace_id == resolved_ws_id)

    def note_count(*extra: ColumnElement[bool]) -> Select[int]:
        return (
            select(func.count(SessionNote.id))
            .select_from(SessionNote)
            .join(AgentSession, SessionNote.session_id == AgentSession.id)
            .where(*note_conditions, *extra)
        )

    notes_total = (await db.execute(note_count())).scalar() or 0

    cutoff = datetime.now(UTC) - timedelta(days=7)
    notes_last_7d = (await db.execute(note_count(SessionNote.created_at >= cutoff))).scalar() or 0
    pending_notes = (await db.execute(note_count(SessionNote.formalized.is_(False)))).scalar() or 0
    last_capture_at = (
        await db.execute(
            select(func.max(SessionNote.created_at))
            .select_from(SessionNote)
            .join(AgentSession, SessionNote.session_id == AgentSession.id)
            .where(*note_conditions)
        )
    ).scalar()

    kind_rows = (
        await db.execute(
            select(SessionNote.signal_type, func.count(SessionNote.id))
            .join(AgentSession, SessionNote.session_id == AgentSession.id)
            .where(*note_conditions)
            .group_by(SessionNote.signal_type)
        )
    ).all()

    return AgentCaptureStats(
        host=host,
        workspace_id=resolved_ws_id,
        sessions=sessions,
        notes_total=notes_total,
        notes_last_7d=notes_last_7d,
        pending_notes=pending_notes,
        last_capture_at=last_capture_at,
        by_kind={signal: count for signal, count in kind_rows},
    )
