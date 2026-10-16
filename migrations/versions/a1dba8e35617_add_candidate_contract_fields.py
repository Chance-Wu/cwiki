"""add_candidate_contract_fields (MQ-202)

Revision ID: a1dba8e35617
Revises: 029_drop_legacy_tables
Create Date: 2026-10-16 09:25:33.467217
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from packages.domain.models.base import JSONBType


revision: str = 'a1dba8e35617'
down_revision: Union[str, None] = '029_drop_legacy_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('candidate_memory', sa.Column('content_contract', JSONBType(), nullable=True))
    op.add_column('candidate_memory', sa.Column('quality_report', JSONBType(), nullable=True))
    op.add_column('candidate_memory', sa.Column('relation_decision', JSONBType(), nullable=True))
    op.add_column('candidate_memory', sa.Column('extraction_version', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('candidate_memory', 'extraction_version')
    op.drop_column('candidate_memory', 'relation_decision')
    op.drop_column('candidate_memory', 'quality_report')
    op.drop_column('candidate_memory', 'content_contract')
