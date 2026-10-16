"""强制 workspace 名称唯一，不改动既有 workspace 数据。

Revision ID: 024_workspace_name_unique
Revises: 023_add_performance_indexes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "024_workspace_name_unique"
down_revision: str | None = "023_add_performance_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    workspace = sa.table("workspace", sa.column("name", sa.String(128)))
    duplicates = (
        op.get_bind()
        .execute(
            sa.select(workspace.c.name, sa.func.count())
            .group_by(workspace.c.name)
            .having(sa.func.count() > 1)
            .order_by(workspace.c.name)
        )
        .all()
    )
    if duplicates:
        detail = ", ".join(f"{name!r} ({count})" for name, count in duplicates)
        raise RuntimeError(
            "Cannot enforce unique workspace names: duplicate names found: "
            f"{detail}. Resolve these duplicates manually before retrying the migration; "
            "no workspaces have been merged, renamed or deleted."
        )

    # 用唯一索引而非重建表，避免 SQLite 重建被外键引用的表；
    # 先建新索引再删旧的，唯一性检查失败时旧索引仍在。
    op.create_index("uq_workspace_name", "workspace", ["name"], unique=True)
    op.drop_index("ix_workspace_name", table_name="workspace")


def downgrade() -> None:
    op.create_index("ix_workspace_name", "workspace", ["name"])
    op.drop_index("uq_workspace_name", table_name="workspace")
