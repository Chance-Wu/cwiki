"""v0.4 为 memory 表新增永久记忆字段（P3）。

Revision ID: 014_memory_permanent
Revises: 013_enhancement_tables
Create Date: 2026-09-15 10:02:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014_memory_permanent"
down_revision: str | None = "013_enhancement_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory",
        sa.Column("is_permanent", sa.Boolean(), server_default=sa.text("0")),
    )
    op.add_column("memory", sa.Column("permanent_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("memory", "permanent_reason")
    op.drop_column("memory", "is_permanent")
