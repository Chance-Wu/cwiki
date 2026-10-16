"""补充查询性能缺失的索引。

Revision ID: 023_add_performance_indexes
Revises: 022_drop_knowledge
Create Date: 2026-09-21 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "023_add_performance_indexes"
down_revision: str | None = "022_drop_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 用 IF NOT EXISTS 保证幂等（SQLite 支持该语法）
    op.execute("CREATE INDEX IF NOT EXISTS ix_workspace_name ON workspace (name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_workspace_id ON project (workspace_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_profile_workspace ON agent_profile (workspace_id, agent_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_memory_updated_at ON memory (updated_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memory_version_memory_id ON memory_version (memory_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_candidate_id ON review (candidate_id)")


def downgrade() -> None:
    op.drop_index("ix_review_candidate_id", table_name="review")
    op.drop_index("ix_memory_version_memory_id", table_name="memory_version")
    op.drop_index("ix_memory_updated_at", table_name="memory")
    op.drop_index("ix_agent_profile_workspace", table_name="agent_profile")
    op.drop_index("ix_project_workspace_id", table_name="project")
    op.drop_index("ix_workspace_name", table_name="workspace")
