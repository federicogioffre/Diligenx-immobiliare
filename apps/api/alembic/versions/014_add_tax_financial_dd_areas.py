"""add tax and financial values to the dd_area enum

Revision ID: 014
Revises: 013
Create Date: 2026-09-03

Extends the ``dd_area`` enum with ``financial`` and ``tax`` so red flags
produced by the financial / tax documentary review can be filed under
their own report sections instead of ``other``.

Postgres only: ``ALTER TYPE ... ADD VALUE`` cannot run inside a
transaction block on PG < 12, so it is executed in an autocommit block.
On SQLite the enum is stored as VARCHAR and no DDL is needed.

Downgrade is a no-op: Postgres cannot drop enum values in place, and
leaving the extra values is harmless.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = ("financial", "tax")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        for value in _NEW_VALUES:
            op.execute(f"ALTER TYPE dd_area ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass
