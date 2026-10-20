"""Hook 事件的归一化结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class HookEvent:
    host: str
    event: str
    session_id: str
    cwd: str | None = None
    workspace: str = "default"
    prompt: str | None = None
    summary: str | None = None
    tool_name: str | None = None
    error: str | None = None
    error_type: str | None = None
    is_interrupt: bool = False
    reason: str | None = None
    transcript_path: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
