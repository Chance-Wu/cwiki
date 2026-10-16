"""v0.3.4 为 candidate_memory 新增判重（dedup）字段。

Revision ID: 007_candidate_dedup
Revises: 006_candidate_project
Create Date: 2026-09-12 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from packages.domain.models import UUIDType

revision: str = "007_candidate_dedup"
down_revision: str | None = "006_candidate_project"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_memory",
        sa.Column(
            "similar_memory_id",
            UUIDType(),
            nullable=True,
            comment="ID of the most similar existing memory or candidate",
        ),
    )
    op.add_column(
        "candidate_memory",
        sa.Column(
            "similar_memory_source",
            sa.String(32),
            nullable=True,
            comment="Source of similar item: 'memory' or 'candidate'",
        ),
    )


def downgrade() -> None:
    op.drop_column("candidate_memory", "similar_memory_source")
    op.drop_column("candidate_memory", "similar_memory_id")
