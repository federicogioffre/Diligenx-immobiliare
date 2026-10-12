"""Bind Microsoft and Google sign-ins to local accounts.

``users`` is not under row-level security, and neither is this table: it is
read before any tenant is known, to find whose account a sign-in opens.
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "oauth_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "subject", name="uq_oauth_identity_provider_subject"),
    )
    op.create_index("ix_oauth_identities_id", "oauth_identities", ["id"])
    op.create_index("ix_oauth_identities_user_id", "oauth_identities", ["user_id"])


def downgrade():
    op.drop_index("ix_oauth_identities_user_id", table_name="oauth_identities")
    op.drop_index("ix_oauth_identities_id", table_name="oauth_identities")
    op.drop_table("oauth_identities")
