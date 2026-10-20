"""session_note 增加 discarded_at，支持软删除丢弃操作。

Revision ID: 032_session_note_discarded
Revises: 031_memory_tags
Create Date: 2026-10-19 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "032_session_note_discarded"
down_revision: str | None = "031_memory_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE session_note ADD COLUMN discarded_at DATETIME")


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN，保留列不影响旧代码读取
    pass
