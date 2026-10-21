"""会话相关模型：Session、Event、Episode、AgentSession、SessionNote。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.domain.config import settings
from packages.domain.models.base import Base, JSONBType, UUIDType, VectorType

if TYPE_CHECKING:
    from packages.domain.models.memory import CandidateMemory, Evidence
    from packages.domain.models.workspace import Agent, Project, Workspace


class Session(Base):
    """Agent 会话；(agent_id, external_session_id) 唯一，支持幂等创建。"""

    __tablename__ = "session"
    __table_args__ = (
        UniqueConstraint("agent_id", "external_session_id", name="uq_session_agent_external"),
        Index("ix_session_project_id", "project_id"),
        Index("ix_session_started_at_desc", "started_at"),
        Index("ix_session_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("agent.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("project.id", ondelete="SET NULL"), nullable=True
    )
    external_session_id: Mapped[str] = mapped_column(String(256), nullable=False)
    cwd: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONBType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())

    workspace: Mapped[Workspace] = relationship(back_populates="sessions")
    agent: Mapped[Agent] = relationship(back_populates="sessions")
    project: Mapped[Project | None] = relationship(back_populates="sessions")
    events: Mapped[list[Event]] = relationship(back_populates="session", lazy="raise")
    episodes: Mapped[list[Episode]] = relationship(back_populates="session", lazy="raise")


class Event(Base):
    """会话事件流水；sequence 在同一会话内单调递增，用于排序与去重。"""

    __tablename__ = "event"
    __table_args__ = (
        UniqueConstraint("agent_id", "session_id", "sequence", name="uq_event_agent_session_seq"),
        Index("ix_event_session_id_sequence", "session_id", "sequence"),
        Index("ix_event_event_type", "event_type"),
        Index("ix_event_occurred_at_desc", "occurred_at"),
        Index("ix_event_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("agent.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONBType(), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())

    agent: Mapped[Agent] = relationship(back_populates="events")
    session: Mapped[Session] = relationship(back_populates="events")
    evidences: Mapped[list[Evidence]] = relationship(back_populates="event", lazy="raise")


class Episode(Base):
    """情节：会话中一段有目标的工作片段，是候选记忆的来源上下文。"""

    __tablename__ = "episode"
    __table_args__ = (
        Index("ix_episode_session_id", "session_id"),
        Index("ix_episode_status", "status"),
        Index("ix_episode_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    importance: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONBType(), nullable=True)
    embedding = mapped_column(VectorType(settings.embedding_dimensions), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped[Session] = relationship(back_populates="episodes")
    candidate_memories: Mapped[list[CandidateMemory]] = relationship(
        back_populates="episode", lazy="raise"
    )
    evidences: Mapped[list[Evidence]] = relationship(back_populates="episode", lazy="raise")


class AgentSession(Base):
    """Agent 执行档案：一次任务运行的元信息（环境、任务、结果）。"""

    __tablename__ = "agent_session"
    __table_args__ = (
        Index("ix_agent_session_workspace_id", "workspace_id"),
        Index("ix_agent_session_agent", "agent"),
        Index("ix_agent_session_started_at", "started_at"),
        Index("ix_agent_session_event_session_id", "event_session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    agent: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    repository: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(256), nullable=True)
    task: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_session_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType(), nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONBType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())


class SessionNote(Base):
    """会话笔记：捕获的原始信号，经形式化后转为正式记忆。"""

    __tablename__ = "session_note"
    __table_args__ = (
        Index("ix_session_note_session_id", "session_id"),
        Index("ix_session_note_signal_type", "signal_type"),
        Index("ix_session_note_workspace_id", "workspace_id"),
        Index("ix_session_note_formalized", "formalized"),
        Index("ix_session_note_candidate_id", "candidate_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        ForeignKey("agent_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUIDType(), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    formalized: Mapped[bool] = mapped_column(default=False, server_default="0")
    formalized_memory_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType(), nullable=True)
    # 整理后生成的候选记忆；note -> candidate -> memory 的追溯链中间节点
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType(), nullable=True)
    discarded_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
