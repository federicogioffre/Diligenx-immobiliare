"""Bind published reports to their analyzed input revision."""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reports", sa.Column("input_hash", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("reports", "input_hash")
