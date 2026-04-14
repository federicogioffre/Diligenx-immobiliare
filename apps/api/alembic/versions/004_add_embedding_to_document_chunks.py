"""Add embedding column to document_chunks

Revision ID: 004
Revises: 3b226dc2df3d
Create Date: 2026-03-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # VectorType stores as TEXT (JSON array) on SQLite, VECTOR on PostgreSQL.
    # Using TEXT here covers the SQLite dev setup; PostgreSQL uses pgvector natively.
    op.add_column(
        'document_chunks',
        sa.Column('embedding', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('document_chunks', 'embedding')
