"""v0.4 新增 session_note 表（P1 memory_note 功能）。

Revision ID: 012_session_note
Revises: 011_alt_mapping
Create Date: 2026-09-15 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012_session_note"
down_revision: str | None = "011_alt_mapping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_note",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("agent_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("signal_type", sa.String(50), nullable=False),
        sa.Column("formalized", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("formalized_memory_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_session_note_session_id", "session_note", ["session_id"])
    op.create_index("ix_session_note_signal_type", "session_note", ["signal_type"])


def downgrade() -> None:
    op.drop_table("session_note")
