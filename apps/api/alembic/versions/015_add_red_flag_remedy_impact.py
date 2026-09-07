"""add remedy_type, impact and structured payload to red_flags

Revision ID: 015
Revises: 014
Create Date: 2026-09-07

Real due-diligence reports tag their findings on two independent axes, and
the tag differs by profession. A Big-4 financial report marks each key
finding as affecting **Value**, the **SPA**, or **Other** — what the finding
hits. A law firm's consolidated risk memo instead tags each risk with the
**instrument** that answers it: a specific indemnity, a cross-reference to
a warranty paragraph, an earn-out, a condition precedent. Diligenx does
both jobs, so it carries both fields.

``structured_payload_json`` carries what the specialist agents already
extract and the aggregator should not lose: the amount the document stated,
the fiscal years, the mitigating factors, and the defensibility grade of
the tax findings behind the flag.

Both tag columns are nullable free-text rather than native enums: the
vocabularies are validated in Python (``packages.agents.red_flag_aggregator``)
and will grow, and a widened CHECK/enum in Postgres costs a migration each
time for no added safety here.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "red_flags", sa.Column("remedy_type", sa.String(length=40), nullable=True)
    )
    op.add_column(
        "red_flags", sa.Column("impact", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "red_flags",
        sa.Column("structured_payload_json", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_red_flags_remedy_type", "red_flags", ["remedy_type"], unique=False
    )
    op.create_index("ix_red_flags_impact", "red_flags", ["impact"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_red_flags_impact", table_name="red_flags")
    op.drop_index("ix_red_flags_remedy_type", table_name="red_flags")
    op.drop_column("red_flags", "structured_payload_json")
    op.drop_column("red_flags", "impact")
    op.drop_column("red_flags", "remedy_type")
