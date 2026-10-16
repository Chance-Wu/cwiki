"""初始迁移——创建全部表。

Revision ID: 001_initial
Revises: None
Create Date: 2025-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from packages.domain.models import JSONBType, UUIDType, VectorType

revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- workspace
    op.create_table(
        "workspace",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # -- project
    op.create_table(
        "project",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("repository", sa.String(1024), nullable=True),
        sa.Column("metadata", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_project_workspace_id", "project", ["workspace_id"])

    # -- agent
    op.create_table(
        "agent",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("adapter", sa.String(64), nullable=False),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("capabilities", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # -- session
    op.create_table(
        "session",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id", UUIDType(), sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "project_id",
            UUIDType(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_session_id", sa.String(256), nullable=False),
        sa.Column("cwd", sa.String(2048), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("metadata", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "external_session_id", name="uq_session_agent_external"),
    )
    op.create_index("ix_session_project_id", "session", ["project_id"])
    op.create_index("ix_session_started_at_desc", "session", ["started_at"])

    # -- event
    op.create_table(
        "event",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id", UUIDType(), sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "session_id",
            UUIDType(),
            sa.ForeignKey("session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("payload", JSONBType(), nullable=True),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "agent_id", "session_id", "sequence", name="uq_event_agent_session_seq"
        ),
    )
    op.create_index("ix_event_session_id_sequence", "event", ["session_id", "sequence"])
    op.create_index("ix_event_event_type", "event", ["event_type"])
    op.create_index("ix_event_occurred_at_desc", "event", ["occurred_at"])

    # -- episode
    op.create_table(
        "episode",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            UUIDType(),
            sa.ForeignKey("session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("importance", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_episode_session_id", "episode", ["session_id"])
    op.create_index("ix_episode_status", "episode", ["status"])

    # -- candidate_memory
    op.create_table(
        "candidate_memory",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "episode_id",
            UUIDType(),
            sa.ForeignKey("episode.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("importance", sa.Float(), nullable=True),
        sa.Column("reusability", sa.Float(), nullable=True),
        sa.Column("stability", sa.Float(), nullable=True),
        sa.Column("evidence_strength", sa.Float(), nullable=True),
        sa.Column("value_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_review"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_candidate_memory_workspace_status", "candidate_memory", ["workspace_id", "status"]
    )
    op.create_index(
        "ix_candidate_memory_workspace_value_desc",
        "candidate_memory",
        ["workspace_id", "value_score"],
    )

    # -- memory
    op.create_table(
        "memory",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            UUIDType(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("usage_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("embedding", VectorType(1536), nullable=True),
        sa.Column("metadata", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_memory_project_id", "memory", ["project_id"])
    op.create_index("ix_memory_workspace_status", "memory", ["workspace_id", "status"])
    op.create_index("ix_memory_type", "memory", ["type"])

    # -- memory_version
    op.create_table(
        "memory_version",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "memory_id", UUIDType(), sa.ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("change_type", sa.String(32), nullable=False),
        sa.Column("changed_by_type", sa.String(32), nullable=False),
        sa.Column("changed_by_id", sa.String(128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("memory_id", "version", name="uq_memory_version"),
    )

    # -- evidence
    op.create_table(
        "evidence",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "memory_id", UUIDType(), sa.ForeignKey("memory.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "candidate_id",
            UUIDType(),
            sa.ForeignKey("candidate_memory.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "episode_id",
            UUIDType(),
            sa.ForeignKey("episode.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "event_id", UUIDType(), sa.ForeignKey("event.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_ref", sa.String(2048), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("metadata", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_evidence_memory_id", "evidence", ["memory_id"])
    op.create_index("ix_evidence_candidate_id", "evidence", ["candidate_id"])

    # -- entity
    op.create_table(
        "entity",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_entity_workspace_name", "entity", ["workspace_id", "name"])

    # -- relation
    op.create_table(
        "relation",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "source_entity_id",
            UUIDType(),
            sa.ForeignKey("entity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_entity_id",
            UUIDType(),
            sa.ForeignKey("entity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(128), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            name="uq_relation_source_target_type",
        ),
    )

    # -- knowledge
    op.create_table(
        "knowledge",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # -- review
    op.create_table(
        "review",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "candidate_id",
            UUIDType(),
            sa.ForeignKey("candidate_memory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewer_type", sa.String(32), nullable=False),
        sa.Column("reviewer_id", sa.String(128), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("before_content", sa.Text(), nullable=True),
        sa.Column("after_content", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # -- audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("payload", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("review")
    op.drop_table("knowledge")
    op.drop_table("relation")
    op.drop_table("entity")
    op.drop_index("ix_evidence_candidate_id", "evidence")
    op.drop_index("ix_evidence_memory_id", "evidence")
    op.drop_table("evidence")
    op.drop_table("memory_version")
    op.drop_index("ix_memory_type", "memory")
    op.drop_index("ix_memory_workspace_status", "memory")
    op.drop_index("ix_memory_project_id", "memory")
    op.drop_table("memory")
    op.drop_index("ix_candidate_memory_workspace_value_desc", "candidate_memory")
    op.drop_index("ix_candidate_memory_workspace_status", "candidate_memory")
    op.drop_table("candidate_memory")
    op.drop_index("ix_episode_status", "episode")
    op.drop_index("ix_episode_session_id", "episode")
    op.drop_table("episode")
    op.drop_index("ix_event_occurred_at_desc", "event")
    op.drop_index("ix_event_event_type", "event")
    op.drop_index("ix_event_session_id_sequence", "event")
    op.drop_table("event")
    op.drop_index("ix_session_started_at_desc", "session")
    op.drop_index("ix_session_project_id", "session")
    op.drop_table("session")
    op.drop_table("agent")
    op.drop_index("ix_project_workspace_id", "project")
    op.drop_table("project")
    op.drop_table("workspace")
