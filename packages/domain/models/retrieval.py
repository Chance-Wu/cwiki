"""检索追踪模型：RetrievalTrace 与 RetrievalTraceItem。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.domain.models.base import Base, JSONBType, UUIDType


class RetrievalTrace(Base):
    """一次检索请求的全链路追踪，用于调试与使用统计。"""

    __tablename__ = "retrieval_trace"
    __table_args__ = (
        Index("ix_retrieval_trace_workspace", "workspace_id"),
        Index("ix_retrieval_trace_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType(), nullable=True)
    # 数据库列名为 "query"（历史命名），Python 属性为 keyword
    keyword: Mapped[str] = mapped_column("query", Text, nullable=False)
    intent: Mapped[dict[str, Any] | None] = mapped_column(JSONBType(), nullable=True)
    candidate_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    returned_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONBType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())

    items: Mapped[list[RetrievalTraceItem]] = relationship(back_populates="trace", lazy="raise")


class RetrievalTraceItem(Base):
    """追踪明细：记录候选记忆在各检索阶段（召回/重排）的排名与得分。"""

    __tablename__ = "retrieval_trace_item"
    __table_args__ = (Index("ix_trace_item_trace_id", "trace_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("retrieval_trace.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    used: Mapped[bool] = mapped_column(default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())

    trace: Mapped[RetrievalTrace] = relationship(back_populates="items")
