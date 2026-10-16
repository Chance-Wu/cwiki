"""新增 review_schedule 表，支撑间隔重复（SM-2）。

Revision ID: 016_review_schedule
Revises: 015_proactive_push
Create Date: 2026-09-15 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "017_review_schedule"
down_revision: str | None = "015_proactive_push"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_schedule",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id",
            sa.Uuid(),
            sa.ForeignKey("memory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ease_factor", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("repetitions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_review", sa.DateTime(), nullable=False),
        sa.Column("last_review", sa.DateTime(), nullable=True),
        sa.Column("total_reviews", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("memory_id", name="uq_review_schedule_memory"),
    )
    op.create_index("ix_review_schedule_memory_id", "review_schedule", ["memory_id"])
    op.create_index("ix_review_schedule_next_review", "review_schedule", ["next_review"])
    op.create_index("ix_review_schedule_workspace", "review_schedule", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("review_schedule")
