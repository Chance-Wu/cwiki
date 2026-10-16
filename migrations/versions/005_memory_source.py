"""v0.3.2 为 memory 新增 source 字段。

Revision ID: 005_memory_source
Revises: 004_candidate_source
Create Date: 2026-09-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_memory_source"
down_revision: str | None = "004_candidate_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory",
        sa.Column("source", sa.String(32), nullable=False, server_default="mcp"),
    )


def downgrade() -> None:
    op.drop_column("memory", "source")
