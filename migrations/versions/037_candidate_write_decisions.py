"""candidate_memory 增加写入决策命中记录。

Revision ID: 037_candidate_write_decisions
Revises: 036_candidate_write_policy
Create Date: 2026-10-23 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "037_candidate_write_decisions"
down_revision: str | None = "036_candidate_write_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_memory", sa.Column("decision_rule_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "candidate_memory", sa.Column("decision_action", sa.String(length=16), nullable=True)
    )
    op.add_column("candidate_memory", sa.Column("decision_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN，保留列不影响旧代码读取
    pass
