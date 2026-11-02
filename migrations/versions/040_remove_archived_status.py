"""移除 archived 状态：历史归档记忆恢复为 active。

Revision ID: 040_remove_archived_status
Revises: 039_review_leech_pause
Create Date: 2026-10-31 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "040_remove_archived_status"
down_revision: str | None = "039_review_leech_pause"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 状态枚举不再包含 archived；历史数据恢复为可检索的 active。
    op.execute(sa.text("UPDATE memory SET status = 'active' WHERE status = 'archived'"))


def downgrade() -> None:
    # 无法区分哪些记忆原本就是 active，降级不做推断。
    pass
