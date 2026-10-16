"""删除 knowledge 表——该概念已移除，统一为纯 memory 模型。

Revision ID: 022_drop_knowledge
Revises: 021_candidate_client_write_id
Create Date: 2026-09-21 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from packages.domain.models import UUIDType

revision: str = "022_drop_knowledge"
down_revision: str | None = "021_candidate_client_write_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("knowledge")


def downgrade() -> None:
    op.create_table(
        "knowledge",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
