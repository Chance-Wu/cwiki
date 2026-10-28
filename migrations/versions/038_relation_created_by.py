"""memory_relation 增加来源标记：created_by / source。

Revision ID: 038_relation_created_by
Revises: 037_candidate_write_decisions
Create Date: 2026-10-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "038_relation_created_by"
down_revision: str | None = "037_candidate_write_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 存量边全部由 auto_relation（相似度自动）产生，server_default 一并完成回填
    op.add_column(
        "memory_relation",
        sa.Column("created_by", sa.String(length=16), nullable=False, server_default="auto"),
    )
    op.add_column("memory_relation", sa.Column("source", sa.String(length=64), nullable=True))


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN，保留列不影响旧代码读取
    pass
