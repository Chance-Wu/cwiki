"""candidate_memory 增加永久声明，审批时继承到正式记忆。

Revision ID: 035_candidate_permanent
Revises: 034_relation_strength
Create Date: 2026-10-23 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "035_candidate_permanent"
down_revision: str | None = "034_relation_strength"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_memory",
        sa.Column("is_permanent", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("candidate_memory", sa.Column("permanent_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN，保留列不影响旧代码读取
    pass
