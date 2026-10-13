"""Prepaid credits: a balance on every user and the ledger behind it.

Existing accounts start at zero; top them up with ``python -m app.credits_cli``.
Like ``users`` and ``oauth_identities``, the ledger is not under row-level
security, and the application role gets the access it has on ``users``
(see 022: the API runs as a non-owner role in production).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "023"
down_revision = "022"
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
    op.add_column("users", sa.Column("credit_balance", sa.Integer(), server_default="0", nullable=False))
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_credit_transactions_id", "credit_transactions", ["id"])
    op.create_index("ix_credit_transactions_user_id", "credit_transactions", ["user_id"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    quote = bind.dialect.identifier_preparer.quote
    for role in bind.execute(_APP_ROLES).scalars():
        name = role if role.startswith('"') else quote(role)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON credit_transactions TO {name}")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE credit_transactions_id_seq TO {name}")


def downgrade():
    op.drop_index("ix_credit_transactions_user_id", table_name="credit_transactions")
    op.drop_index("ix_credit_transactions_id", table_name="credit_transactions")
    op.drop_table("credit_transactions")
    op.drop_column("users", "credit_balance")
