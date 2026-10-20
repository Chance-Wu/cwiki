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
    # 内容完整性优先：全文入库，不在捕获阶段截断。列表接口只返回预览，
    # 详情接口返回全文；上限用于防止异常超大 payload，而不是摘要化。
    content: str = Field(..., min_length=1, max_length=50000)
    signal_type: str = Field(default="other", max_length=50)
    candidate_id: UUID | None = None


class SessionNoteFormalize(BaseModel):
    """把笔记整理为候选记忆或正式记忆。

    - candidate_id：整理动作生成了候选，note 仍可在候选详情中追溯；
    - memory_id：候选已批准/直接整理为正式记忆，建立最终反向链接。
    """

    candidate_id: UUID | None = None
    memory_id: UUID | None = None


class SessionNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    workspace_id: UUID
    # preview 视图为 None；详情/创建/整理响应返回全文
    content: str | None = None
    content_preview: str
    content_length: int
    signal_type: str
    formalized: bool
    formalized_memory_id: UUID | None
    candidate_id: UUID | None = None
    discarded_at: datetime | None = None
    # 来源宿主与工作区名称（由 join 填充，便于收件箱展示）
    host: str | None = None
    workspace_name: str | None = None
    created_at: datetime
