"""review_schedule 增加顽固记忆与暂停字段：lapse_streak / suspended_at。

Revision ID: 039_review_leech_pause
Revises: 038_relation_created_by
Create Date: 2026-10-31 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "039_review_leech_pause"
down_revision: str | None = "038_relation_created_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 存量排期默认无连续遗忘、未暂停
    op.add_column(
        "review_schedule",
        sa.Column("lapse_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("review_schedule", sa.Column("suspended_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN，保留列不影响旧代码读取
    pass
