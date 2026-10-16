"""为 agent_session 新增 event_session_id。

Revision ID: 020_agent_session_event_link
Revises: 019_drop_memory_template
Create Date: 2026-09-17 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "020_agent_session_event_link"
down_revision: str | None = "019_drop_memory_template"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_session",
        sa.Column("event_session_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_agent_session_event_session_id",
        "agent_session",
        ["event_session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_session_event_session_id", table_name="agent_session")
    op.drop_column("agent_session", "event_session_id")
