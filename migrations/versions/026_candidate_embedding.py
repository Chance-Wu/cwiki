"""为 candidate_memory 表新增 embedding 列。

Revision ID: 026_candidate_embedding
Revises: b510b70bda92
Create Date: 2026-10-07 09:45:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "026_candidate_embedding"
down_revision: str | None = "b510b70bda92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 为 candidate_memory 表新增 embedding 列
    op.execute("ALTER TABLE candidate_memory ADD COLUMN embedding TEXT")


def downgrade() -> None:
    # 旧版 SQLite 不支持 DROP COLUMN，降级时跳过删除
    pass
