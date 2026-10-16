"""v0.3.6 为发布工作流新增模板待定变更。

Revision ID: 010_template_pending
Revises: 009_remove_scope
Create Date: 2026-09-14 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010_template_pending"
down_revision: str | None = "009_remove_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_template",
        sa.Column("pending_changes", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("memory_template", "pending_changes")
