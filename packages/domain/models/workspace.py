"""组织维度模型：Workspace、Project、Agent、AgentProfile。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.domain.models.base import Base, JSONBType, UUIDType

if TYPE_CHECKING:
    from packages.domain.models.memory import Memory
    from packages.domain.models.session import Event, Session


class Workspace(Base):
    """工作区：唯一的顶层组织维度，名称全局唯一且兼作文件路径组件。"""

    __tablename__ = "workspace"
    __table_args__ = (Index("uq_workspace_name", "name", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(), onupdate=func.now()
    )

    projects: Mapped[list[Project]] = relationship(back_populates="workspace", lazy="raise")
    agents: Mapped[list[Agent]] = relationship(back_populates="workspace", lazy="raise")
    sessions: Mapped[list[Session]] = relationship(back_populates="workspace", lazy="raise")


class Project(Base):
    """项目：旧版组织维度，概念上已并入 workspace，保留以兼容旧数据。"""

    __tablename__ = "project"
    __table_args__ = (Index("ix_project_workspace_id", "workspace_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    repository: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONBType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="projects")
    sessions: Mapped[list[Session]] = relationship(back_populates="project", lazy="raise")
    memories: Mapped[list[Memory]] = relationship(back_populates="project", lazy="raise")


class Agent(Base):
    """Agent：接入本系统的 Agent 注册信息与能力声明。"""

    __tablename__ = "agent"
    __table_args__ = (Index("ix_agent_workspace_id", "workspace_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONBType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="agents")
    sessions: Mapped[list[Session]] = relationship(back_populates="agent", lazy="raise")
    events: Mapped[list[Event]] = relationship(back_populates="agent", lazy="raise")


class AgentProfile(Base):
    """Agent 画像：会话/笔记/反馈的聚合统计，驱动个性化策略。"""

    __tablename__ = "agent_profile"
    __table_args__ = (Index("ix_agent_profile_workspace", "workspace_id", "agent_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    total_sessions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_memories_submitted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_notes_created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    note_formalization_rate: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    preferred_signal_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_memory_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    nudge_response_rate: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")
    preferred_nudge_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
