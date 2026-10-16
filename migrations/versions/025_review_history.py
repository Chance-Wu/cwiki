"""新增 review_history 表，用于追踪复习前后状态变化。

Revision ID: 025_review_history
Revises: 024_workspace_name_unique
Create Date: 2026-09-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "025_review_history"
down_revision: str | None = "024_workspace_name_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_history",
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
        sa.Column("quality", sa.Integer(), nullable=False),
        # 复习前状态
        sa.Column("ease_factor_before", sa.Float(), nullable=False),
        sa.Column("interval_before", sa.Integer(), nullable=False),
        sa.Column("repetitions_before", sa.Integer(), nullable=False),
        sa.Column("next_review_before", sa.DateTime(), nullable=False),
        sa.Column("mastery_level_before", sa.String(32), nullable=False),
        # 复习后状态
        sa.Column("ease_factor_after", sa.Float(), nullable=False),
        sa.Column("interval_after", sa.Integer(), nullable=False),
        sa.Column("repetitions_after", sa.Integer(), nullable=False),
        sa.Column("next_review_after", sa.DateTime(), nullable=False),
        sa.Column("mastery_level_after", sa.String(32), nullable=False),
        # 元数据
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_review_history_memory_id", "review_history", ["memory_id"])
    op.create_index("ix_review_history_workspace_id", "review_history", ["workspace_id"])
    op.create_index("ix_review_history_reviewed_at", "review_history", ["reviewed_at"])


def downgrade() -> None:
    op.drop_table("review_history")
