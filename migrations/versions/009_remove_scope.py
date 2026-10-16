"""v0.3.6 从所有表中移除 scope 字段。

Revision ID: 009_remove_scope
Revises: 008_memory_template
Create Date: 2026-09-14 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "009_remove_scope"
down_revision: str | None = "008_memory_template"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("candidate_memory") as batch_op:
        batch_op.drop_column("scope")

    with op.batch_alter_table("memory") as batch_op:
        batch_op.drop_column("scope")

    with op.batch_alter_table("retrieval_trace") as batch_op:
        batch_op.drop_column("scope")

    with op.batch_alter_table("benchmark_query") as batch_op:
        batch_op.drop_column("scope")


def downgrade() -> None:
    import sqlalchemy as sa

    from packages.domain.models import JSONBType

    with op.batch_alter_table("benchmark_query") as batch_op:
        batch_op.add_column(sa.Column("scope", sa.String(64), nullable=True))

    with op.batch_alter_table("retrieval_trace") as batch_op:
        batch_op.add_column(sa.Column("scope", JSONBType(), nullable=True))

    with op.batch_alter_table("memory") as batch_op:
        batch_op.add_column(
            sa.Column("scope", sa.String(64), nullable=False, server_default="workspace")
        )

    with op.batch_alter_table("candidate_memory") as batch_op:
        batch_op.add_column(
            sa.Column("scope", sa.String(64), nullable=False, server_default="workspace")
        )
