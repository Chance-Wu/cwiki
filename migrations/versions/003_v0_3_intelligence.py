"""v0.3 智能化——benchmark、usage_event、agent_session、quality gate。

Revision ID: 003_v0_3_intelligence
Revises: 002_v0_2_upgrade
Create Date: 2025-01-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from packages.domain.models import JSONBType, UUIDType

revision: str = "003_v0_3_intelligence"
down_revision: str | None = "002_v0_2_upgrade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- New columns on candidate_memory (quality gate)
    op.add_column("candidate_memory", sa.Column("quality_gate_score", sa.Float(), nullable=True))
    op.add_column("candidate_memory", sa.Column("quality_gate_reason", sa.Text(), nullable=True))
    op.add_column("candidate_memory", sa.Column("review_priority", sa.Float(), nullable=True))
    op.add_column("candidate_memory", sa.Column("duplicate_probability", sa.Float(), nullable=True))

    # -- benchmark_dataset
    op.create_table(
        "benchmark_dataset",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # -- benchmark_query
    op.create_table(
        "benchmark_query",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "dataset_id",
            UUIDType(),
            sa.ForeignKey("benchmark_dataset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(64), nullable=True),
        sa.Column("metadata", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_benchmark_query_dataset_id", "benchmark_query", ["dataset_id"])

    # -- benchmark_relevance
    op.create_table(
        "benchmark_relevance",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "query_id",
            UUIDType(),
            sa.ForeignKey("benchmark_query.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id", UUIDType(), sa.ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("relevance", sa.Integer(), nullable=False),
        sa.Column("annotator", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "query_id",
            "memory_id",
            "annotator",
            name="uq_benchmark_relevance_query_memory_annotator",
        ),
    )
    op.create_index("ix_benchmark_relevance_query_id", "benchmark_relevance", ["query_id"])

    # -- benchmark_run
    op.create_table(
        "benchmark_run",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "dataset_id",
            UUIDType(),
            sa.ForeignKey("benchmark_dataset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pipeline", sa.String(64), nullable=False),
        sa.Column("config", JSONBType(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # -- benchmark_result
    op.create_table(
        "benchmark_result",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "run_id",
            UUIDType(),
            sa.ForeignKey("benchmark_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "query_id",
            UUIDType(),
            sa.ForeignKey("benchmark_query.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("relevance", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_benchmark_result_run_id", "benchmark_result", ["run_id"])

    # -- memory_usage_event (distinct from 0.2 memory_usage)
    op.create_table(
        "memory_usage_event",
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
        sa.Column("agent", sa.String(128), nullable=True),
        sa.Column("usage_type", sa.String(32), nullable=False),
        sa.Column("evidence_type", sa.String(64), nullable=True),
        sa.Column("evidence", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_memory_usage_event_memory_id", "memory_usage_event", ["memory_id"])
    op.create_index("ix_memory_usage_event_session_id", "memory_usage_event", ["session_id"])
    op.create_index("ix_memory_usage_event_usage_type", "memory_usage_event", ["usage_type"])

    # -- agent_session
    op.create_table(
        "agent_session",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent", sa.String(128), nullable=False),
        sa.Column("agent_version", sa.String(64), nullable=True),
        sa.Column("repository", sa.String(1024), nullable=True),
        sa.Column("branch", sa.String(256), nullable=True),
        sa.Column("task", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=True),
        sa.Column("metadata", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_session_workspace_id", "agent_session", ["workspace_id"])
    op.create_index("ix_agent_session_agent", "agent_session", ["agent"])
    op.create_index("ix_agent_session_started_at", "agent_session", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_session_started_at", "agent_session")
    op.drop_index("ix_agent_session_agent", "agent_session")
    op.drop_index("ix_agent_session_workspace_id", "agent_session")
    op.drop_table("agent_session")

    op.drop_index("ix_memory_usage_event_usage_type", "memory_usage_event")
    op.drop_index("ix_memory_usage_event_session_id", "memory_usage_event")
    op.drop_index("ix_memory_usage_event_memory_id", "memory_usage_event")
    op.drop_table("memory_usage_event")

    op.drop_index("ix_benchmark_result_run_id", "benchmark_result")
    op.drop_table("benchmark_result")
    op.drop_table("benchmark_run")
    op.drop_index("ix_benchmark_relevance_query_id", "benchmark_relevance")
    op.drop_table("benchmark_relevance")
    op.drop_index("ix_benchmark_query_dataset_id", "benchmark_query")
    op.drop_table("benchmark_query")
    op.drop_table("benchmark_dataset")

    op.drop_column("candidate_memory", "duplicate_probability")
    op.drop_column("candidate_memory", "review_priority")
    op.drop_column("candidate_memory", "quality_gate_reason")
    op.drop_column("candidate_memory", "quality_gate_score")
