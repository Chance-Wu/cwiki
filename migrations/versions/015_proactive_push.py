"""v0.4 新增 proactive_push_record 表（P3-32）。

Revision ID: 015_proactive_push
Revises: 014_memory_permanent
Create Date: 2026-09-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015_proactive_push"
down_revision: str | None = "014_memory_permanent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proactive_push_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "memory_id",
            sa.Uuid(),
            sa.ForeignKey("memory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("keywords", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_proactive_push_session_id", "proactive_push_record", ["session_id"])
    op.create_index("ix_proactive_push_memory_id", "proactive_push_record", ["memory_id"])


def downgrade() -> None:
    op.drop_table("proactive_push_record")
