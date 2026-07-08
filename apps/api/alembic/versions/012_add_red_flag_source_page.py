"""add source_page to red_flags

Revision ID: 012
Revises: 011
Create Date: 2026-07-08

Pinpoint citation: the page of source_document_id where the flagged item
appears. NULL when the aggregator could not attribute a specific page.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("red_flags", sa.Column("source_page", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("red_flags", "source_page")
