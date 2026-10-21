"""记忆相关模型：Memory、MemoryVersion、CandidateMemory、Evidence 等。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
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
    from packages.domain.models.session import Episode, Event
    from packages.domain.models.workspace import Project


class Memory(Base):
    """正式记忆（知识条目）：经评审确认的稳定知识单元。"""

    __tablename__ = "memory"
    __table_args__ = (
        Index("ix_memory_project_id", "project_id"),
        Index("ix_memory_workspace_status", "workspace_id", "status"),
        Index("ix_memory_type", "type"),
        Index("ix_memory_updated_at", "updated_at"),
        Index("ix_memory_confidence", "confidence"),
        Index("ix_memory_importance", "importance"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("project.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(JSONBType(), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="mcp")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 时间有效性区间：支持"曾经正确、现已过时"的事实演化
    valid_from: Mapped[datetime | None] = mapped_column(nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # 永久记忆不参与衰减与自动淘汰
    is_permanent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    permanent_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(VectorType(settings.embedding_dimensions), nullable=True)
    content_contract: Mapped[dict[str, Any] | None] = mapped_column(JSONBType(), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONBType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project | None] = relationship(back_populates="memories")
    versions: Mapped[list[MemoryVersion]] = relationship(back_populates="memory", lazy="raise")
    evidences: Mapped[list[Evidence]] = relationship(back_populates="memory", lazy="raise")


class MemoryVersion(Base):
    """记忆历史版本快照；(memory_id, version) 唯一保证版本链可回溯。"""

    __tablename__ = "memory_version"
    __table_args__ = (
        Index("ix_memory_version_memory_id", "memory_id"),
        UniqueConstraint("memory_id", "version", name="uq_memory_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by_type: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())

    memory: Mapped[Memory] = relationship(back_populates="versions")


class CandidateMemory(Base):
    """候选记忆：待评审确认后才转为正式 Memory，携带质量与去重评分。"""

    __tablename__ = "candidate_memory"
    __table_args__ = (
        Index("ix_candidate_memory_workspace_status", "workspace_id", "status"),
        Index("ix_candidate_memory_workspace_value_desc", "workspace_id", "value_score"),
        Index("ix_candidate_memory_project_id", "project_id"),
        Index("ix_candidate_memory_review_priority", "review_priority"),
        Index("ix_candidate_memory_created_at", "created_at"),
        Index("ix_candidate_memory_episode_id", "episode_id"),
        UniqueConstraint("workspace_id", "client_write_id", name="uq_candidate_client_write_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("project.id", ondelete="SET NULL"), nullable=True
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("episode.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(JSONBType(), nullable=True)
    # (workspace_id, client_write_id) 唯一：客户端重试不会产生重复候选（幂等写入）
    client_write_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    importance: Mapped[float | None] = mapped_column(Float, nullable=True)
    novelty: Mapped[float | None] = mapped_column(Float, nullable=True)
    reusability: Mapped[float | None] = mapped_column(Float, nullable=True)
    stability: Mapped[float | None] = mapped_column(Float, nullable=True)
    future_utility: Mapped[float | None] = mapped_column(Float, nullable=True)
    actionability: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    scope_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_gate_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_gate_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_priority: Mapped[float | None] = mapped_column(Float, nullable=True)
    duplicate_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    similar_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), nullable=True, comment="ID of the most similar existing memory or candidate"
    )
    similar_memory_source: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="Source of similar item: 'memory' or 'candidate'"
    )
    dedup_relation_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Relation type from dedup: NEW, UPDATE, MERGE, CONFLICT, REJECT",
    )
    embedding = mapped_column(VectorType(settings.embedding_dimensions), nullable=True)
    # MQ-202: 结构化契约、质量报告、关系判定、提炼版本
    content_contract: Mapped[dict[str, Any] | None] = mapped_column(JSONBType(), nullable=True)
    quality_report: Mapped[dict[str, Any] | None] = mapped_column(JSONBType(), nullable=True)
    relation_decision: Mapped[dict[str, Any] | None] = mapped_column(JSONBType(), nullable=True)
    extraction_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 状态机：pending_review → approved（转正式）/ rejected
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="mcp")
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(), onupdate=func.now()
    )

    episode: Mapped[Episode | None] = relationship(back_populates="candidate_memories")
    evidences: Mapped[list[Evidence]] = relationship(back_populates="candidate", lazy="raise")
    reviews: Mapped[list[Review]] = relationship(back_populates="candidate", lazy="raise")


class Evidence(Base):
    """证据：把候选/正式记忆与来源事件关联，支撑可信度追溯。"""

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_memory_id", "memory_id"),
        Index("ix_evidence_candidate_id", "candidate_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=True
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(),
        ForeignKey("candidate_memory.id", ondelete="CASCADE"),
        nullable=True,
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("episode.id", ondelete="SET NULL"), nullable=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("event.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONBType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())

    memory: Mapped[Memory | None] = relationship(back_populates="evidences")
    candidate: Mapped[CandidateMemory | None] = relationship(back_populates="evidences")
    episode: Mapped[Episode | None] = relationship(back_populates="evidences")
    event: Mapped[Event | None] = relationship(back_populates="evidences")


class Review(Base):
    """评审记录：对候选记忆的批准/拒绝/合并等操作留痕。"""

    __tablename__ = "review"
    __table_args__ = (Index("ix_review_candidate_id", "candidate_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        ForeignKey("candidate_memory.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())

    candidate: Mapped[CandidateMemory] = relationship(back_populates="reviews")


class MemoryUsage(Base):
    """记忆使用流水：记录每次检索命中，驱动使用度信号与新鲜度衰减。"""

    __tablename__ = "memory_usage"
    __table_args__ = (
        Index("ix_memory_usage_memory_id", "memory_id"),
        Index("ix_memory_usage_session_id", "session_id"),
        Index("ix_memory_usage_workspace_id", "workspace_id"),
        Index("ix_memory_usage_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType(), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType(), nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="retrieved")
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())


class MemoryFeedback(Base):
    """记忆反馈：有用/无用等信号，用于调整重要度。"""

    __tablename__ = "memory_feedback"
    __table_args__ = (
        Index("ix_memory_feedback_memory_id", "memory_id"),
        Index("ix_memory_feedback_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())


class MemoryConflict(Base):
    """记忆冲突：候选与既有记忆冲突时挂起，等待裁决。"""

    __tablename__ = "memory_conflict"
    __table_args__ = (
        Index("ix_memory_conflict_memory", "memory_id"),
        Index("ix_memory_conflict_status", "status"),
        Index("ix_memory_conflict_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("candidate_memory.id", ondelete="SET NULL"), nullable=True
    )
    conflict_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONBType(), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class MemoryLifecycleEvent(Base):
    """记忆生命周期审计事件（created/updated/archived 等）。"""

    __tablename__ = "memory_lifecycle_event"
    __table_args__ = (
        Index("ix_lifecycle_memory_id", "memory_id"),
        Index("ix_lifecycle_event_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        ForeignKey("memory.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())


class MemoryRelation(Base):
    """记忆间有向关系（source → target）。"""

    __tablename__ = "memory_relation"
    __table_args__ = (
        Index("ix_memory_relation_source", "source_memory_id"),
        Index("ix_memory_relation_target", "target_memory_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    source_memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    target_memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    # Hebbian 强度：共检索强化、按半衰期衰减；与语义 confidence 分开存储
    strength: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    last_reinforced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())


class ProactivePushRecord(Base):
    """主动推送留痕，用于避免同一会话重复推送同一记忆。"""

    __tablename__ = "proactive_push_record"
    __table_args__ = (
        Index("ix_proactive_push_session_id", "session_id"),
        Index("ix_proactive_push_memory_id", "memory_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUIDType(), nullable=False)
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())


class ReviewSchedule(Base):
    """间隔重复复习计划（ease/interval/repetitions 为调度参数）。"""

    __tablename__ = "review_schedule"
    __table_args__ = (
        Index("ix_review_schedule_memory_id", "memory_id"),
        Index("ix_review_schedule_next_review", "next_review"),
        Index("ix_review_schedule_workspace", "workspace_id"),
        UniqueConstraint("memory_id", name="uq_review_schedule_memory"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    ease_factor: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_review: Mapped[datetime] = mapped_column(nullable=False)
    last_review: Mapped[datetime | None] = mapped_column(nullable=True)
    total_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(), onupdate=func.now()
    )


class ReviewHistory(Base):
    """单次复习事件的历史，用于审计与撤销支持。"""

    __tablename__ = "review_history"
    __table_args__ = (
        Index("ix_review_history_memory_id", "memory_id"),
        Index("ix_review_history_workspace_id", "workspace_id"),
        Index("ix_review_history_reviewed_at", "reviewed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    quality: Mapped[int] = mapped_column(Integer, nullable=False)

    # 复习前状态
    ease_factor_before: Mapped[float] = mapped_column(Float, nullable=False)
    interval_before: Mapped[int] = mapped_column(Integer, nullable=False)
    repetitions_before: Mapped[int] = mapped_column(Integer, nullable=False)
    next_review_before: Mapped[datetime] = mapped_column(nullable=False)
    mastery_level_before: Mapped[str] = mapped_column(String(32), nullable=False)

    # 复习后状态
    ease_factor_after: Mapped[float] = mapped_column(Float, nullable=False)
    interval_after: Mapped[int] = mapped_column(Integer, nullable=False)
    repetitions_after: Mapped[int] = mapped_column(Integer, nullable=False)
    next_review_after: Mapped[datetime] = mapped_column(nullable=False)
    mastery_level_after: Mapped[str] = mapped_column(String(32), nullable=False)

    # 审计元数据
    reviewed_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
