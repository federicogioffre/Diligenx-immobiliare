"""Add relevance_score and relevance_reason to clause_findings.

Revision ID: 003
Revises: 002
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "3b226dc2df3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clause_findings",
        sa.Column("relevance_score", sa.String(20), nullable=True),
    )
    op.add_column(
        "clause_findings",
        sa.Column("relevance_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clause_findings", "relevance_reason")
    op.drop_column("clause_findings", "relevance_score")
