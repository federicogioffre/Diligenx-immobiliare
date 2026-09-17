"""Convert the legacy PostgreSQL TEXT embedding column to native pgvector.

Migration 004 used TEXT on every dialect even though the ORM declared VECTOR
on PostgreSQL. Conversion is transactional: invalid JSON/vector dimensions
abort the migration and preserve the old data for investigation/re-embedding.
The database server must have pgvector installed and migrations must run with
a role allowed to install the extension. SQLite remains TEXT.
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1536) "
        "USING embedding::vector(1536)"
    )


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE TEXT "
        "USING embedding::text"
    )
    # Keep the extension: another table or application may depend on it.
