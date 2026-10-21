"""candidate_memory 增加 tags 列，支持提交时打标并在审批时继承。

Revision ID: 033_candidate_tags
Revises: 032_session_note_discarded
Create Date: 2026-10-20 14:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "033_candidate_tags"
down_revision: str | None = "032_session_note_discarded"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE candidate_memory ADD COLUMN tags JSON DEFAULT NULL")


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN，保留列不影响旧代码读取
    pass
