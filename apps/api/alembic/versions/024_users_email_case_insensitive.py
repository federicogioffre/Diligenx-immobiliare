"""One account per mailbox: email addresses are unique whatever their case.

Registration compared addresses exactly while the Microsoft/Google sign-in
looked them up case-insensitively, so ``Mario@studio.it`` could be
registered beside ``mario@studio.it`` and the first provider sign-in could be
linked to either. Addresses are stored in lower case from now on.

Existing addresses are lowered where that collides with no other account.
Accounts that differ only in case cannot be merged automatically (each may
own workspaces): the migration stops and names them, so an operator decides
which one to keep before deploying again.
"""
from alembic import op
from sqlalchemy import text

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    duplicates = conn.execute(text("""
        SELECT lower(email) AS address, count(*) AS accounts
        FROM users GROUP BY lower(email) HAVING count(*) > 1
    """)).fetchall()
    if duplicates:
        listed = ", ".join(f"{row.address} ({row.accounts})" for row in duplicates)
        raise RuntimeError(
            "Accounts whose email differs only in case must be resolved before "
            f"migration 024 can make addresses case-insensitive: {listed}"
        )
    conn.execute(text("UPDATE users SET email = lower(email) WHERE email <> lower(email)"))
    op.create_index("ix_users_email_lower", "users", [text("lower(email)")], unique=True)


def downgrade():
    op.drop_index("ix_users_email_lower", table_name="users")
