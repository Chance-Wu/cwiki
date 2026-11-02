"""Transactional memory mirror repair log.

Revision ID: 042_file_sync_jobs
Revises: 041_review_quiz
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "042_file_sync_jobs"
down_revision: str | None = "041_review_quiz"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_sync_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("memory_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_file_sync_job_memory_id", "file_sync_job", ["memory_id"])


def downgrade() -> None:
    op.drop_index("ix_file_sync_job_memory_id", table_name="file_sync_job")
    op.drop_table("file_sync_job")
