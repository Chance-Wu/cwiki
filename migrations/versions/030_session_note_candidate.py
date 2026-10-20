"""session_note 增加 candidate_id，建立 note -> candidate 追溯链。

Revision ID: 030_session_note_candidate
Revises: a1dba8e35617
Create Date: 2026-10-19 00:50:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "030_session_note_candidate"
down_revision: str | None = "a1dba8e35617"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE session_note ADD COLUMN candidate_id VARCHAR(36)")
    op.create_index("ix_session_note_candidate_id", "session_note", ["candidate_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_session_note_candidate_id", table_name="session_note")
    # 旧版 SQLite 不支持 DROP COLUMN，保留列不影响旧代码读取
