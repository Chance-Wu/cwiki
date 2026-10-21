"""cwiki memory_relation 增加 Hebbian 强度字段。

Revision ID: 034_relation_strength
Revises: 033_candidate_tags
Create Date: 2026-10-20 14:45:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "034_relation_strength"
down_revision: str | None = "033_candidate_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE memory_relation ADD COLUMN strength FLOAT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE memory_relation ADD COLUMN last_reinforced_at DATETIME")


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN，保留列不影响旧代码读取
    pass
