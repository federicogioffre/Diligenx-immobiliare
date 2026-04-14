"""Add language column to documents

Revision ID: 3b226dc2df3d
Revises: 002
Create Date: 2026-03-07 21:24:18.537393

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b226dc2df3d'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('language', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'language')
