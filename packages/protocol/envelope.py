"""Agent Event Protocol v1 事件信封定义。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventEnvelope(BaseModel):
    """Agent Event Protocol v1 事件信封：跨 Agent 传输的事件统一封装。"""

    model_config = ConfigDict(strict=False)

    protocol_version: str = Field(default="1", description="Protocol version")
    event_id: UUID = Field(default_factory=uuid4, description="Unique event identifier")
    event_type: str = Field(description="Type of event")
    agent: str = Field(description="Agent identifier")
    session: str = Field(description="Session identifier")
    workspace: str = Field(description="Workspace identifier")
    project: str | None = Field(default=None, description="Project identifier")
    sequence: int = Field(ge=0, description="Monotonically increasing sequence number")
    timestamp: datetime = Field(description="When the event occurred (UTC ISO-8601)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event-specific data")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol_version(cls, v: str) -> str:
        if v != "1":
            raise ValueError(f"Unsupported protocol version: {v}, only '1' is supported")
        return v

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Sequence number must be non-negative")
        return v


def redact_envelope_payload(envelope: EventEnvelope) -> dict[str, Any]:
    """脱敏事件信封 payload 中的密钥，返回净化后的字典。"""
    from packages.domain.secrets import redact_secrets

    return _redact_dict(envelope.payload, redact_secrets)


def _redact_dict(d: dict[str, Any], redact_fn: Callable[[str], str]) -> dict[str, Any]:
    """递归脱敏字典中的密钥。"""
    # 键名命中敏感清单 → 整个值遮蔽；字符串值 → 正则脱敏；容器 → 递归处理
    sensitive_keys = {
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "api-key",
        "access_token",
        "auth_token",
        "token",
        "private_key",
        "client_secret",
        "authorization",
    }
    out: dict[str, Any] = {}
    for key, val in d.items():
        if isinstance(key, str) and key.lower() in sensitive_keys:
            out[key] = "***REDACTED***"
        elif isinstance(val, str):
            out[key] = redact_fn(val)
        elif isinstance(val, dict):
            out[key] = _redact_dict(val, redact_fn)
        elif isinstance(val, list):
            out[key] = [
                redact_fn(v)
                if isinstance(v, str)
                else _redact_dict(v, redact_fn)
                if isinstance(v, dict)
                else v
                for v in val
            ]
        else:
            out[key] = val
    return out
