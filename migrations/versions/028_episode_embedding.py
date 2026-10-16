"""为 episode 表新增 embedding 列，支持情节检索。

Revision ID: 028_episode_embedding
Revises: 027_memory_relation_enhance
Create Date: 2026-10-10 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "028_episode_embedding"
down_revision: str | None = "027_memory_relation_enhance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE episode ADD COLUMN embedding TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE episode DROP COLUMN IF EXISTS embedding")
