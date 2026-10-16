"""v0.4 新增 P2-P4 增强表（nudge、lifecycle、relation、profile、stats）。

Revision ID: 013_enhancement_tables
Revises: 012_session_note
Create Date: 2026-09-15 10:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013_enhancement_tables"
down_revision: str | None = "012_session_note"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nudge_response",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("agent_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nudge_type", sa.String(50), nullable=False),
        sa.Column("nudge_content", sa.Text(), nullable=False),
        sa.Column("responded", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("response_action", sa.String(50), nullable=True),
        sa.Column("response_delay_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "memory_lifecycle_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "memory_id",
            sa.Uuid(),
            sa.ForeignKey("memory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_lifecycle_memory_id", "memory_lifecycle_event", ["memory_id"])

    op.create_table(
        "memory_relation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_memory_id",
            sa.Uuid(),
            sa.ForeignKey("memory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_memory_id",
            sa.Uuid(),
            sa.ForeignKey("memory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("1.0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "agent_profile",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("agent_id", sa.String(255), nullable=False),
        sa.Column("total_sessions", sa.Integer(), server_default=sa.text("0")),
        sa.Column("total_memories_submitted", sa.Integer(), server_default=sa.text("0")),
        sa.Column("total_notes_created", sa.Integer(), server_default=sa.text("0")),
        sa.Column("note_formalization_rate", sa.Float(), server_default=sa.text("0.0")),
        sa.Column("preferred_signal_types", sa.Text(), nullable=True),
        sa.Column("preferred_memory_types", sa.Text(), nullable=True),
        sa.Column("nudge_response_rate", sa.Float(), server_default=sa.text("0.5")),
        sa.Column("preferred_nudge_types", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_agent_profile_workspace",
        "agent_profile",
        ["workspace_id", "agent_id"],
    )

    op.create_table(
        "memory_stats_cache",
        sa.Column(
            "memory_id",
            sa.Uuid(),
            sa.ForeignKey("memory.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("usage_count_90d", sa.Integer(), server_default=sa.text("0")),
        sa.Column("approval_rate", sa.Float(), server_default=sa.text("0.5")),
        sa.Column("quality_score", sa.Float(), server_default=sa.text("0.5")),
        sa.Column("relation_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("last_computed", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("memory_stats_cache")
    op.drop_table("agent_profile")
    op.drop_table("memory_relation")
    op.drop_table("memory_lifecycle_event")
    op.drop_table("nudge_response")
