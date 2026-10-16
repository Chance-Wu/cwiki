"""v0.2 升级——新增 retrieval_trace、memory_usage、feedback、conflict 表，
以及 candidate_memory 与 memory 的新列。

Revision ID: 002_v0_2_upgrade
Revises: 001_initial
Create Date: 2025-01-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from packages.domain.models import JSONBType, UUIDType

revision: str = "002_v0_2_upgrade"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- New columns on candidate_memory
    op.add_column("candidate_memory", sa.Column("novelty", sa.Float(), nullable=True))
    op.add_column("candidate_memory", sa.Column("future_utility", sa.Float(), nullable=True))
    op.add_column("candidate_memory", sa.Column("actionability", sa.Float(), nullable=True))
    op.add_column("candidate_memory", sa.Column("scope_confidence", sa.Float(), nullable=True))
    op.add_column("candidate_memory", sa.Column("quality_score", sa.Float(), nullable=True))

    # -- New column on memory
    op.add_column("memory", sa.Column("content_contract", JSONBType(), nullable=True))

    # -- retrieval_trace
    op.create_table(
        "retrieval_trace",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", UUIDType(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("intent", JSONBType(), nullable=True),
        sa.Column("scope", JSONBType(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=True),
        sa.Column("returned_count", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("metadata", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_retrieval_trace_workspace", "retrieval_trace", ["workspace_id"])
    op.create_index("ix_retrieval_trace_created", "retrieval_trace", ["created_at"])

    # -- retrieval_trace_item
    op.create_table(
        "retrieval_trace_item",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "trace_id",
            UUIDType(),
            sa.ForeignKey("retrieval_trace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id", UUIDType(), sa.ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("used", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_trace_item_trace_id", "retrieval_trace_item", ["trace_id"])

    # -- memory_usage
    op.create_table(
        "memory_usage",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id", UUIDType(), sa.ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("trace_id", UUIDType(), nullable=True),
        sa.Column("session_id", UUIDType(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(32), nullable=False, server_default="retrieved"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_memory_usage_memory_id", "memory_usage", ["memory_id"])
    op.create_index("ix_memory_usage_session_id", "memory_usage", ["session_id"])

    # -- memory_feedback
    op.create_table(
        "memory_feedback",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id", UUIDType(), sa.ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("feedback_type", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_memory_feedback_memory_id", "memory_feedback", ["memory_id"])

    # -- memory_conflict
    op.create_table(
        "memory_conflict",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id", UUIDType(), sa.ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "candidate_id",
            UUIDType(),
            sa.ForeignKey("candidate_memory.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("conflict_type", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("evidence", JSONBType(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_memory_conflict_memory", "memory_conflict", ["memory_id"])
    op.create_index("ix_memory_conflict_status", "memory_conflict", ["status"])


def downgrade() -> None:
    op.drop_index("ix_memory_conflict_status", "memory_conflict")
    op.drop_index("ix_memory_conflict_memory", "memory_conflict")
    op.drop_table("memory_conflict")
    op.drop_index("ix_memory_feedback_memory_id", "memory_feedback")
    op.drop_table("memory_feedback")
    op.drop_index("ix_memory_usage_session_id", "memory_usage")
    op.drop_index("ix_memory_usage_memory_id", "memory_usage")
    op.drop_table("memory_usage")
    op.drop_index("ix_trace_item_trace_id", "retrieval_trace_item")
    op.drop_table("retrieval_trace_item")
    op.drop_index("ix_retrieval_trace_created", "retrieval_trace")
    op.drop_index("ix_retrieval_trace_workspace", "retrieval_trace")
    op.drop_table("retrieval_trace")
    op.drop_column("memory", "content_contract")
    op.drop_column("candidate_memory", "quality_score")
    op.drop_column("candidate_memory", "scope_confidence")
    op.drop_column("candidate_memory", "actionability")
    op.drop_column("candidate_memory", "future_utility")
    op.drop_column("candidate_memory", "novelty")
