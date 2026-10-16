"""create the property_profiles table under row-level security

Revision ID: r026
Revises: r025
Create Date: 2026-10-16

One row per property unit per source document, written by the
property-identity stage. The table is deal-scoped, so it gets the same
forced RLS policy as the other deal-scoped tables (012, with the NULLIF
form of 016), and the same grants as ``users`` for the application role
(022) — default privileges already cover it where 022 ran, the explicit
grant keeps databases that predate it consistent.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision: str = "r026"
down_revision: Union[str, None] = "r025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TENANT = "NULLIF(current_setting('app.current_user_id', true), '')::int"
_POLICY = (
    "EXISTS (SELECT 1 FROM deals d JOIN workspaces w ON w.id = d.workspace_id "
    f"WHERE d.id = property_profiles.deal_id AND w.owner_id = {_TENANT})"
)

_APP_ROLES = text("""
    SELECT DISTINCT acl.grantee::regrole::text
    FROM pg_class c
    CROSS JOIN LATERAL aclexplode(c.relacl) AS acl
    WHERE c.oid = 'public.users'::regclass
      AND acl.grantee <> 0
      AND acl.grantee <> c.relowner
      AND acl.privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
""")


def upgrade() -> None:
    op.create_table(
        "property_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("deals.id"), nullable=False, index=True),
        sa.Column("source_document_id", sa.Integer(),
                  sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("source_kind", sa.String(40), nullable=True),
        sa.Column("unit_label", sa.String(200), nullable=True),
        sa.Column("comune", sa.String(200), nullable=True),
        sa.Column("sezione", sa.String(40), nullable=True),
        sa.Column("foglio", sa.String(40), nullable=True),
        sa.Column("particella", sa.String(60), nullable=True),
        sa.Column("subalterno", sa.String(40), nullable=True),
        sa.Column("categoria", sa.String(40), nullable=True),
        sa.Column("classe", sa.String(40), nullable=True),
        sa.Column("consistenza", sa.String(100), nullable=True),
        sa.Column("superficie", sa.String(100), nullable=True),
        sa.Column("rendita", sa.String(100), nullable=True),
        sa.Column("indirizzo", sa.String(500), nullable=True),
        sa.Column("piano", sa.String(100), nullable=True),
        sa.Column("intestatari", sa.JSON(), nullable=True),
        sa.Column("titolo", sa.String(500), nullable=True),
        sa.Column("data_titolo", sa.String(40), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE property_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE property_profiles FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY property_profiles_tenant_isolation ON property_profiles "
        f"USING ({_POLICY}) WITH CHECK ({_POLICY})"
    )
    quote = bind.dialect.identifier_preparer.quote
    for role in bind.execute(_APP_ROLES).scalars():
        name = role if role.startswith('"') else quote(role)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON property_profiles TO {name}")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE property_profiles_id_seq TO {name}")


def downgrade() -> None:
    op.drop_table("property_profiles")
