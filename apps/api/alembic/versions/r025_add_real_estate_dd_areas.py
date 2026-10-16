"""add the real-estate purchase values to the dd_area enum

Revision ID: r025
Revises: 024
Create Date: 2026-10-16

First migration of Diligenx-immobiliare. Revisions of this repository are
numbered ``r025``, ``r026``, … after Diligenx's ``024``; a migration later
ported from Diligenx is renumbered at the end of this chain, so the history
stays linear.

Same mechanics as 014: ``ALTER TYPE ... ADD VALUE`` runs in an autocommit
block on Postgres; SQLite stores the enum as VARCHAR and needs no DDL.
Downgrade is a no-op, since Postgres cannot drop enum values in place.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "r025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "title_chain",
    "encumbrances",
    "cadastral",
    "building_compliance",
    "condominium",
    "installations_energy",
    "occupancy",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        for value in _NEW_VALUES:
            op.execute(f"ALTER TYPE dd_area ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass
