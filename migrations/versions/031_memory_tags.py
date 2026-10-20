"""memory 增加 tags 列，支持标签分类与过滤检索。

Revision ID: 031_memory_tags
Revises: 030_session_note_candidate
Create Date: 2026-10-19 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "031_memory_tags"
down_revision: str | None = "030_session_note_candidate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE memory ADD COLUMN tags JSON DEFAULT NULL")


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN，保留列不影响旧代码读取
    pass
