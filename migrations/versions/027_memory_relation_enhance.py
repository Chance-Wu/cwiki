"""为 memory_relation 新增唯一索引，并为 candidate 新增 dedup_relation_type。

Revision ID: 027_memory_relation_enhance
Revises: 026_candidate_embedding
Create Date: 2026-10-10 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "027_memory_relation_enhance"
down_revision: str | None = "026_candidate_embedding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_relation "
        "ON memory_relation(source_memory_id, target_memory_id, relation_type)"
    )
    op.execute("ALTER TABLE candidate_memory ADD COLUMN dedup_relation_type VARCHAR(50)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_memory_relation")
