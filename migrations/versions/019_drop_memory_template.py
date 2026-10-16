"""drop memory_template table — templates are now static.

Revision ID: 019_drop_memory_template
Revises: 018_memory_segment
Create Date: 2026-09-16 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "019_drop_memory_template"
down_revision: str | None = "018_memory_segment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("memory_template")


def downgrade() -> None:
    import sqlalchemy as sa

    op.create_table(
        "memory_template",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("type", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sections", sa.Text(), nullable=False),
        sa.Column("alt_sections", sa.Text(), nullable=True),
        sa.Column("example", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("pending_changes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
