"""宿主无关的 Agent 捕获协议。

任何 Agent（Qoder / Claude Code / Cursor / Codex / 自研）只要能把会话中的
结构化事件 POST 到 capture 端点，就能进入 cwiki 的“待整理”收件箱。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

CaptureKind = Literal["compact_summary", "tool_failure", "session_end"]


class AgentCaptureRecord(BaseModel):
    """一条待整理的捕获记录。

    - compact_summary：宿主压缩上下文后提供的摘要（已由宿主总结，非 cwiki 截断）
    - tool_failure：工具失败的结构化信息（已脱敏）
    - session_end：只更新会话生命周期，不产生 note
    """

    record_id: str | None = Field(
        default=None,
        max_length=128,
        description="幂等键；缺省时服务端按 host+session+kind+content 生成",
    )
    kind: CaptureKind
    session_id: str = Field(..., min_length=1, max_length=256)
    workspace: str = Field(..., min_length=1, max_length=64)
    cwd: str | None = Field(default=None, max_length=2048)
    content: str = Field(default="", max_length=50000)
    signal_type: str = Field(default="other", max_length=50)
    occurred_at: datetime | None = None


class AgentCaptureRequest(BaseModel):
    host: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    records: list[AgentCaptureRecord] = Field(..., min_length=1, max_length=50)


class AgentCaptureRejected(BaseModel):
    record_id: str | None
    reason: str


class AgentCaptureResponse(BaseModel):
    host: str
    accepted: int
    duplicates: int
    rejected: list[AgentCaptureRejected]
    session_id: UUID | None = None
    note_ids: list[UUID] = Field(default_factory=list)


class AgentCaptureStats(BaseModel):
    host: str | None = None
    workspace_id: UUID | None = None
    sessions: int
    notes_total: int
    notes_last_7d: int
    pending_notes: int
    last_capture_at: datetime | None
    by_kind: dict[str, int] = Field(default_factory=dict)
