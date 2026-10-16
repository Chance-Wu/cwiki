"""v0.3.1 为 candidate_memory 新增 source 字段。

Revision ID: 004_candidate_source
Revises: 003_v0_3_intelligence
Create Date: 2026-09-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_candidate_source"
down_revision: str | None = "003_v0_3_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_memory",
        sa.Column("source", sa.String(32), nullable=False, server_default="mcp"),
    )


def downgrade() -> None:
    op.drop_column("candidate_memory", "source")
