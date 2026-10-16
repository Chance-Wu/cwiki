"""为 candidate_memory 新增 client_write_id，实现幂等写入。

Revision ID: 021_candidate_client_write_id
Revises: 020_agent_session_event_link
Create Date: 2026-09-17 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "021_candidate_client_write_id"
down_revision: str | None = "020_agent_session_event_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("candidate_memory") as batch_op:
        batch_op.add_column(
            sa.Column("client_write_id", sa.String(64), nullable=True),
        )
        batch_op.create_unique_constraint(
            "uq_candidate_client_write_id",
            ["workspace_id", "client_write_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("candidate_memory") as batch_op:
        batch_op.drop_constraint("uq_candidate_client_write_id", type_="unique")
        batch_op.drop_column("client_write_id")
