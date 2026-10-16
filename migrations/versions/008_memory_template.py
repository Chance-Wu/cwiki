"""v0.3.5 新增 memory_template 表。

Revision ID: 008_memory_template
Revises: 007_candidate_dedup
Create Date: 2026-09-13 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from packages.domain.models import UUIDType

revision: str = "008_memory_template"
down_revision: str | None = "007_candidate_dedup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_template",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column("type", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("alt_sections", sa.JSON(), nullable=True),
        sa.Column("example", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("memory_template")
