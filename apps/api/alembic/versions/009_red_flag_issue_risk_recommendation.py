"""red flags: issue/risk/recommendation triple, DD area, 3-level severity

Revision ID: 009
Revises: 008
Create Date: 2026-06-10

Aligns the RedFlag model with the structure of professional red-flag DD
reports:

1. ``description`` → ``issue`` (rename): the factual finding.
2. New nullable ``risk`` and ``recommendation`` columns: impact and
   suggested action (condition precedent, R&W, special indemnity, ...).
3. New nullable ``area`` column (enum ``dd_area``): the standard report
   section the flag belongs to (corporate / indebtedness / real_estate /
   employees / suppliers_customers / insurance / litigation / ip_it /
   data_protection / other).
4. ``severity`` loses the ``critical`` value (practitioners use a 3-level
   scale; existing critical rows are downgraded to high). The enum type is
   recreated because PostgreSQL cannot drop enum values in place. The enum
   is shared with agent_findings.severity — both columns are converted.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DD_AREAS = (
    "corporate",
    "indebtedness",
    "real_estate",
    "employees",
    "suppliers_customers",
    "insurance",
    "litigation",
    "ip_it",
    "data_protection",
    "other",
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # ── 1. rename description → issue ────────────────────────────────────
    op.alter_column("red_flags", "description", new_column_name="issue")

    # ── 2. add risk / recommendation ──────────────────────────────────────
    op.add_column("red_flags", sa.Column("risk", sa.Text(), nullable=True))
    op.add_column("red_flags", sa.Column("recommendation", sa.Text(), nullable=True))

    # ── 3. add area enum column ───────────────────────────────────────────
    dd_area = sa.Enum(*_DD_AREAS, name="dd_area")
    dd_area.create(op.get_bind(), checkfirst=True)
    op.add_column("red_flags", sa.Column("area", dd_area, nullable=True))
    op.create_index("ix_red_flags_area", "red_flags", ["area"])

    # ── 4. severity: downgrade critical → high, drop the enum value ───────
    # Data first (works on both PG and SQLite):
    op.execute("UPDATE red_flags SET severity = 'high' WHERE severity = 'critical'")
    op.execute(
        "UPDATE agent_findings SET severity = 'high' WHERE severity = 'critical'"
    )

    if _is_postgres():
        # PG enums cannot drop values: recreate the type and swap columns.
        op.execute("ALTER TYPE severity RENAME TO severity_old")
        op.execute("CREATE TYPE severity AS ENUM ('low', 'medium', 'high')")
        op.execute(
            "ALTER TABLE red_flags ALTER COLUMN severity "
            "TYPE severity USING severity::text::severity"
        )
        op.execute(
            "ALTER TABLE agent_findings ALTER COLUMN severity "
            "TYPE severity USING severity::text::severity"
        )
        op.execute("DROP TYPE severity_old")
    # SQLite: enum is stored as VARCHAR; nothing to alter. Tests recreate
    # the schema from the models anyway.


def downgrade() -> None:
    if _is_postgres():
        op.execute("ALTER TYPE severity RENAME TO severity_old")
        op.execute(
            "CREATE TYPE severity AS ENUM ('low', 'medium', 'high', 'critical')"
        )
        op.execute(
            "ALTER TABLE red_flags ALTER COLUMN severity "
            "TYPE severity USING severity::text::severity"
        )
        op.execute(
            "ALTER TABLE agent_findings ALTER COLUMN severity "
            "TYPE severity USING severity::text::severity"
        )
        op.execute("DROP TYPE severity_old")

    op.drop_index("ix_red_flags_area", table_name="red_flags")
    op.drop_column("red_flags", "area")
    sa.Enum(name="dd_area").drop(op.get_bind(), checkfirst=True)
    op.drop_column("red_flags", "recommendation")
    op.drop_column("red_flags", "risk")
    op.alter_column("red_flags", "issue", new_column_name="description")
