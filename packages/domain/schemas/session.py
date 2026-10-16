"""会话相关 schema：Session、Event、AgentSession、SessionNote。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    workspace_id: str
    agent_id: UUID
    project_id: UUID | None = None
    external_session_id: str = Field(..., max_length=256)
    cwd: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, Any] | None = None


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    agent_id: UUID
    project_id: UUID | None
    external_session_id: str
    cwd: str | None
    status: str
    started_at: datetime
    ended_at: datetime | None
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")
    created_at: datetime


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    agent_id: UUID
    session_id: UUID
    sequence: int
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any] | None
    source: str | None
    created_at: datetime


class EventIngestResult(BaseModel):
    """单条事件接入结果。"""

    accepted: bool
    # sequence 重复即视为重复事件，幂等忽略（见 Event 表唯一约束）
    duplicate: bool = False
    event_id: UUID | None = None


class BatchEventIngestResult(BaseModel):
    """批量事件接入结果。"""

    results: list[EventIngestResult]
    accepted_count: int
    duplicate_count: int


class AgentSessionCreate(BaseModel):
    workspace_id: str
    agent: str = Field(..., max_length=128)
    agent_version: str | None = Field(default=None, max_length=64)
    repository: str | None = Field(default=None, max_length=1024)
    branch: str | None = Field(default=None, max_length=256)
    task: str | None = None
    metadata: dict[str, Any] | None = None


class AgentSessionComplete(BaseModel):
    outcome: str = Field(..., pattern="^(success|partial_success|failure|unknown)$")
    metadata: dict[str, Any] | None = None


class AgentSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    agent: str
    agent_version: str | None
    repository: str | None
    branch: str | None
    task: str | None
    event_session_id: UUID | None
    started_at: datetime
    ended_at: datetime | None
    outcome: str | None
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")
    created_at: datetime


class SessionNoteCreate(BaseModel):
    content: str = Field(..., max_length=2000)
    signal_type: str = Field(default="other", max_length=50)


class SessionNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    workspace_id: UUID
    content: str
    signal_type: str
    formalized: bool
    formalized_memory_id: UUID | None
    created_at: datetime
