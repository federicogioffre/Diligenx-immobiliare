"""add report_language to deals

Revision ID: 011
Revises: 010
Create Date: 2026-06-10

"it" | "en" | NULL. NULL means: auto-detect from the majority language of
the deal's processed documents (fallback "en").
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("report_language", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("deals", "report_language")
