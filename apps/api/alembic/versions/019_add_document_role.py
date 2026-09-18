"""Track letters of intent explicitly, retaining generic roles for existing files."""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents") as batch:
        batch.add_column(
            sa.Column("document_role", sa.String(20), nullable=False, server_default="data_room"),
        )
        batch.create_check_constraint(
            "ck_documents_document_role", "document_role IN ('data_room', 'loi')",
        )


def downgrade():
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("ck_documents_document_role", type_="check")
        batch.drop_column("document_role")
