"""Give the application role the same access to oauth_identities as to users.

Production runs the API as a role without DDL rights; migrations run as the
table owner. A table created by a migration is therefore invisible to the
API until someone grants it, and 021 did not: the first Microsoft/Google
sign-in failed with "permission denied for table oauth_identities".

The role's name differs per environment, so it is not hard-coded: every role
the owner has granted DML on ``users`` receives the same on
``oauth_identities`` and its sequence. Default privileges then cover the
tables later migrations create. Nothing to do on SQLite, or where the API
connects as the owner itself.
"""
from alembic import op
from sqlalchemy import text

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

_APP_ROLES = text("""
    SELECT DISTINCT acl.grantee::regrole::text
    FROM pg_class c
    CROSS JOIN LATERAL aclexplode(c.relacl) AS acl
    WHERE c.oid = 'public.users'::regclass
      AND acl.grantee <> 0
      AND acl.grantee <> c.relowner
      AND acl.privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
""")


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    quote = bind.dialect.identifier_preparer.quote
    for role in bind.execute(_APP_ROLES).scalars():
        # regrole::text is already quoted when the name needs it.
        name = role if role.startswith('"') else quote(role)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON oauth_identities TO {name}")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE oauth_identities_id_seq TO {name}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                   f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {name}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                   f"GRANT USAGE, SELECT ON SEQUENCES TO {name}")


def downgrade():
    # Revoking would break sign-in on a database that keeps the table.
    pass
