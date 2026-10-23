"""candidate_memory 增加写入策略命中记录。

Revision ID: 036_candidate_write_policy
Revises: 035_candidate_permanent
Create Date: 2026-10-23 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "036_candidate_write_policy"
down_revision: str | None = "035_candidate_permanent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_memory", sa.Column("policy_rule_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "candidate_memory", sa.Column("policy_action", sa.String(length=16), nullable=True)
    )
    op.add_column("candidate_memory", sa.Column("policy_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN，保留列不影响旧代码读取
    pass
