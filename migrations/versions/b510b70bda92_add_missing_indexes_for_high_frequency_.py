"""为高频查询列补充缺失索引

Revision ID: b510b70bda92
Revises: 025_review_history
Create Date: 2026-09-30 06:59:02.517028
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b510b70bda92"
down_revision: str | None = "025_review_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_agent_workspace_id", "agent", ["workspace_id"], unique=False)
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], unique=False)
    op.create_index("ix_audit_log_workspace_id", "audit_log", ["workspace_id"], unique=False)
    op.create_index(
        "ix_candidate_memory_created_at", "candidate_memory", ["created_at"], unique=False
    )
    op.create_index(
        "ix_candidate_memory_episode_id", "candidate_memory", ["episode_id"], unique=False
    )
    op.create_index(
        "ix_candidate_memory_review_priority", "candidate_memory", ["review_priority"], unique=False
    )
    op.create_index("ix_episode_workspace_id", "episode", ["workspace_id"], unique=False)
    op.create_index("ix_event_workspace_id", "event", ["workspace_id"], unique=False)
    op.create_index("ix_memory_confidence", "memory", ["confidence"], unique=False)
    op.create_index("ix_memory_importance", "memory", ["importance"], unique=False)
    op.create_index(
        "ix_memory_conflict_created_at", "memory_conflict", ["created_at"], unique=False
    )
    op.create_index(
        "ix_memory_feedback_workspace_id", "memory_feedback", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_lifecycle_event_created_at", "memory_lifecycle_event", ["created_at"], unique=False
    )
    op.create_index("ix_memory_usage_created_at", "memory_usage", ["created_at"], unique=False)
    op.create_index("ix_memory_usage_workspace_id", "memory_usage", ["workspace_id"], unique=False)
    op.create_index("ix_session_workspace_id", "session", ["workspace_id"], unique=False)
    op.create_index("ix_session_note_formalized", "session_note", ["formalized"], unique=False)
    op.create_index("ix_session_note_workspace_id", "session_note", ["workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_session_note_workspace_id", table_name="session_note")
    op.drop_index("ix_session_note_formalized", table_name="session_note")
    op.drop_index("ix_session_workspace_id", table_name="session")
    op.drop_index("ix_memory_usage_workspace_id", table_name="memory_usage")
    op.drop_index("ix_memory_usage_created_at", table_name="memory_usage")
    op.drop_index("ix_lifecycle_event_created_at", table_name="memory_lifecycle_event")
    op.drop_index("ix_memory_feedback_workspace_id", table_name="memory_feedback")
    op.drop_index("ix_memory_conflict_created_at", table_name="memory_conflict")
    op.drop_index("ix_memory_importance", table_name="memory")
    op.drop_index("ix_memory_confidence", table_name="memory")
    op.drop_index("ix_event_workspace_id", table_name="event")
    op.drop_index("ix_episode_workspace_id", table_name="episode")
    op.drop_index("ix_candidate_memory_review_priority", table_name="candidate_memory")
    op.drop_index("ix_candidate_memory_episode_id", table_name="candidate_memory")
    op.drop_index("ix_candidate_memory_created_at", table_name="candidate_memory")
    op.drop_index("ix_audit_log_workspace_id", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_agent_workspace_id", table_name="agent")
