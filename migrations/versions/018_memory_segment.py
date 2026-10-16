"""新增 memory_segment 表，支持增量 embedding。

Revision ID: 018_memory_segment
Revises: 017_review_schedule
Create Date: 2026-09-16 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "018_memory_segment"
down_revision: str | None = "017_review_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_segment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "memory_id",
            sa.Uuid(),
            sa.ForeignKey("memory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section_heading", sa.String(256), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("memory_id", "section_heading", name="uq_memory_segment"),
    )
    op.create_index("ix_memory_segment_memory_id", "memory_segment", ["memory_id"])


def downgrade() -> None:
    op.drop_table("memory_segment")
