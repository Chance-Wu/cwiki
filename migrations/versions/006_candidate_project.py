"""v0.3.3 为 candidate_memory 新增 project_id。

Revision ID: 006_candidate_project
Revises: 005_memory_source
Create Date: 2026-09-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from packages.domain.models import UUIDType

revision: str = "006_candidate_project"
down_revision: str | None = "005_memory_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_memory",
        sa.Column("project_id", UUIDType(), nullable=True),
    )
    op.create_index("ix_candidate_memory_project_id", "candidate_memory", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_memory_project_id", table_name="candidate_memory")
    op.drop_column("candidate_memory", "project_id")
