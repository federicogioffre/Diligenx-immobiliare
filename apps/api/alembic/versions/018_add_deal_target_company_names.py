"""Add an explicit corporate introductory scope to each deal.

Existing deals deliberately remain unconfigured: titles and document mentions
are not reliable evidence that a legal entity belongs to the transaction.
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deals", sa.Column("target_company_names", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("deals", "target_company_names")
