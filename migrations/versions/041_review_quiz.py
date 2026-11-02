"""review_history 增加填空/选择判分字段。

Revision ID: 041_review_quiz
Revises: 040_remove_archived_status
Create Date: 2026-11-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "041_review_quiz"
down_revision: str | None = "040_remove_archived_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("review_history", sa.Column("quiz_type", sa.String(length=16), nullable=True))
    op.add_column("review_history", sa.Column("quiz_correct", sa.Boolean(), nullable=True))
    op.add_column("review_history", sa.Column("quiz_prompt", sa.Text(), nullable=True))
    op.add_column("review_history", sa.Column("quiz_expected", sa.Text(), nullable=True))
    op.add_column("review_history", sa.Column("quiz_response", sa.Text(), nullable=True))


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN；保留列不影响旧代码读取
    pass
