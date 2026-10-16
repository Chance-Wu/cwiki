"""删除代码与模型已不再引用的遗留表。

早期功能迭代产生的十二张孤立表被删除：audit_log、entity、relation（知识图谱）、
benchmark_*（DB 版基准测试，已被 benchmarks/datasets/ 下的文件数据集取代）、
memory_usage_event、memory_stats_cache、memory_segment、nudge_response。
这些表均未被 SQLAlchemy 模型或应用代码引用，且在既有数据库中全部为空表。

Revision ID: 029_drop_legacy_tables
Revises: 028_episode_embedding
Create Date: 2026-10-14 10:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from packages.domain.models import JSONBType, UUIDType

revision: str = "029_drop_legacy_tables"
down_revision: str | None = "028_episode_embedding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 先删被 FK 引用的子表，再删父表，避免外键约束报错。
    op.drop_table("relation")
    op.drop_table("benchmark_result")
    op.drop_table("benchmark_relevance")
    op.drop_table("benchmark_run")
    op.drop_table("benchmark_query")
    op.drop_table("benchmark_dataset")
    op.drop_table("memory_usage_event")
    op.drop_table("memory_stats_cache")
    op.drop_table("memory_segment")
    op.drop_table("nudge_response")
    op.drop_table("audit_log")
    op.drop_table("entity")


def downgrade() -> None:
    # 按原定义（001/003/013/018）以依赖逆序重建各表。
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
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], unique=False)
    op.create_index("ix_audit_log_workspace_id", "audit_log", ["workspace_id"], unique=False)

    op.create_table(
        "benchmark_dataset",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "benchmark_query",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "dataset_id",
            UUIDType(),
            sa.ForeignKey("benchmark_dataset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(64), nullable=True),
        sa.Column("metadata", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_benchmark_query_dataset_id", "benchmark_query", ["dataset_id"])

    op.create_table(
        "benchmark_relevance",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "query_id",
            UUIDType(),
            sa.ForeignKey("benchmark_query.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id", UUIDType(), sa.ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("relevance", sa.Integer(), nullable=False),
        sa.Column("annotator", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "query_id",
            "memory_id",
            "annotator",
            name="uq_benchmark_relevance_query_memory_annotator",
        ),
    )
    op.create_index("ix_benchmark_relevance_query_id", "benchmark_relevance", ["query_id"])

    op.create_table(
        "benchmark_run",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "dataset_id",
            UUIDType(),
            sa.ForeignKey("benchmark_dataset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pipeline", sa.String(64), nullable=False),
        sa.Column("config", JSONBType(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "benchmark_result",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "run_id",
            UUIDType(),
            sa.ForeignKey("benchmark_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "query_id",
            UUIDType(),
            sa.ForeignKey("benchmark_query.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("relevance", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_benchmark_result_run_id", "benchmark_result", ["run_id"])

    op.create_table(
        "memory_usage_event",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column(
            "workspace_id",
            UUIDType(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id", UUIDType(), sa.ForeignKey("memory.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("trace_id", UUIDType(), nullable=True),
        sa.Column("session_id", UUIDType(), nullable=True),
        sa.Column("agent", sa.String(128), nullable=True),
        sa.Column("usage_type", sa.String(32), nullable=False),
        sa.Column("evidence_type", sa.String(64), nullable=True),
        sa.Column("evidence", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_memory_usage_event_memory_id", "memory_usage_event", ["memory_id"])
    op.create_index("ix_memory_usage_event_session_id", "memory_usage_event", ["session_id"])
    op.create_index("ix_memory_usage_event_usage_type", "memory_usage_event", ["usage_type"])

    op.create_table(
        "memory_stats_cache",
        sa.Column(
            "memory_id",
            sa.Uuid(),
            sa.ForeignKey("memory.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("usage_count_90d", sa.Integer(), server_default=sa.text("0")),
        sa.Column("approval_rate", sa.Float(), server_default=sa.text("0.5")),
        sa.Column("quality_score", sa.Float(), server_default=sa.text("0.5")),
        sa.Column("relation_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("last_computed", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "nudge_response",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("agent_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nudge_type", sa.String(50), nullable=False),
        sa.Column("nudge_content", sa.Text(), nullable=False),
        sa.Column("responded", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("response_action", sa.String(50), nullable=True),
        sa.Column("response_delay_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "memory_segment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "memory_id",
            sa.Uuid(),
            sa.ForeignKey("memory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section_heading", sa.String(256), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("memory_id", "section_heading", name="uq_memory_segment"),
    )
    op.create_index("ix_memory_segment_memory_id", "memory_segment", ["memory_id"])
