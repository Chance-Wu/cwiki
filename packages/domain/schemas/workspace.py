"""组织维度相关 schema：Workspace、Agent、AgentProfile。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.domain.paths import validate_path_component


class WorkspaceCreate(BaseModel):
    name: str = Field(..., max_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        # workspace 名会直接用作 Markdown 记忆文件的路径组件，须满足跨平台文件名规则
        return validate_path_component(value)


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    # 仅列表端点填充；单条读写的默认值 0 表示未统计
    memory_count: int = 0


class AgentCreate(BaseModel):
    workspace_id: str
    name: str = Field(..., max_length=128)
    type: str = Field(..., max_length=64)
    adapter: str = Field(..., max_length=64)
    version: str | None = Field(default=None, max_length=64)
    capabilities: dict[str, Any] | None = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    name: str
    type: str
    adapter: str
    version: str | None
    status: str
    capabilities: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class AgentProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: str
    agent_id: str
    total_sessions: int
    total_memories_submitted: int
    total_notes_created: int
    note_formalization_rate: float
    preferred_signal_types: list[str] | None = None
    preferred_memory_types: list[str] | None = None
    nudge_response_rate: float
    preferred_nudge_types: list[str] | None = None
    updated_at: datetime

    @classmethod
    def from_orm_with_json(cls, obj: Any) -> AgentProfileRead:
        import json

        data = {
            "id": obj.id,
            "workspace_id": obj.workspace_id,
            "agent_id": obj.agent_id,
            "total_sessions": obj.total_sessions,
            "total_memories_submitted": obj.total_memories_submitted,
            "total_notes_created": obj.total_notes_created,
            "note_formalization_rate": obj.note_formalization_rate,
            "nudge_response_rate": obj.nudge_response_rate,
            "updated_at": obj.updated_at,
        }
        # preferred_* 在 ORM 中为 JSON 文本列，此处反序列化为列表
        for field in ["preferred_signal_types", "preferred_memory_types", "preferred_nudge_types"]:
            val = getattr(obj, field, None)
            data[field] = json.loads(val) if val else None
        return cls(**data)


class AgentProfileUpdate(BaseModel):
    total_sessions: int | None = None
    total_memories_submitted: int | None = None
    total_notes_created: int | None = None
    note_formalization_rate: float | None = None
    preferred_signal_types: list[str] | None = None
    preferred_memory_types: list[str] | None = None
    nudge_response_rate: float | None = None
    preferred_nudge_types: list[str] | None = None
