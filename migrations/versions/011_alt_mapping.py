"""v0.3.7 将 alt_sections 归一化为 substitute->required 映射。

Revision ID: 011_alt_mapping
Revises: 010_template_pending
Create Date: 2026-09-14 18:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011_alt_mapping"
down_revision: str | None = "010_template_pending"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_TO_MAPPING: dict[str, dict[str, str]] = {
    "decision": {"背景": "场景", "决策": "知识"},
    "convention": {"约定": "知识"},
    "pattern": {"模式": "知识"},
    "feedback": {"规则": "知识"},
}


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, type, alt_sections FROM memory_template")).fetchall()
    for row_id, tpl_type, alt in rows:
        if alt is None or isinstance(alt, dict):
            continue
        mapping = _LEGACY_TO_MAPPING.get(tpl_type, {})
        conn.execute(
            sa.text("UPDATE memory_template SET alt_sections = :alt WHERE id = :id"),
            {"alt": json.dumps(mapping, ensure_ascii=False), "id": str(row_id)},
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, alt_sections FROM memory_template")).fetchall()
    for row_id, alt in rows:
        if not isinstance(alt, dict):
            continue
        conn.execute(
            sa.text("UPDATE memory_template SET alt_sections = :alt WHERE id = :id"),
            {"alt": json.dumps(list(alt.keys()), ensure_ascii=False), "id": str(row_id)},
        )
