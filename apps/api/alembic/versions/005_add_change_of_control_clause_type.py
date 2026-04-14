"""Add change_of_control to ClauseType enum

Revision ID: 005
Revises: 004
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires ALTER TYPE to add enum values.
    # SQLite stores enums as VARCHAR so no DDL change is needed.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE clausetype ADD VALUE IF NOT EXISTS 'change_of_control'"
        )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without dropping and
    # recreating the type; downgrade is a no-op for safety.
    pass
