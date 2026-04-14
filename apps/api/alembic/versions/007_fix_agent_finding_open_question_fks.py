"""Fix agent_findings/open_questions document FKs + backfill missing relevance columns.

Revision ID: 007
Revises: 006
Create Date: 2026-03-26

Two problems fixed here:
1. Migration 003 (relevance_score/relevance_reason on clause_findings) was on a
   detached branch and was never actually executed against the live database.
   We add the columns idempotently.
2. agent_findings.document_id and open_questions.document_id had plain FKs
   without ON DELETE SET NULL, causing 500 errors when deleting documents that
   had been analysed.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. Idempotently add relevance columns to clause_findings ──────────
    inspector = inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("clause_findings")}
    if "relevance_score" not in existing:
        op.add_column(
            "clause_findings",
            sa.Column("relevance_score", sa.String(20), nullable=True),
        )
    if "relevance_reason" not in existing:
        op.add_column(
            "clause_findings",
            sa.Column("relevance_reason", sa.Text(), nullable=True),
        )

    # ── 2. Fix nullable document FKs (PostgreSQL only) ────────────────────
    if bind.dialect.name != "postgresql":
        return

    # agent_findings.document_id
    op.drop_constraint(
        "agent_findings_document_id_fkey", "agent_findings", type_="foreignkey"
    )
    op.create_foreign_key(
        "agent_findings_document_id_fkey",
        "agent_findings",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # open_questions.document_id
    op.drop_constraint(
        "open_questions_document_id_fkey", "open_questions", type_="foreignkey"
    )
    op.create_foreign_key(
        "open_questions_document_id_fkey",
        "open_questions",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "agent_findings_document_id_fkey", "agent_findings", type_="foreignkey"
        )
        op.create_foreign_key(
            "agent_findings_document_id_fkey",
            "agent_findings",
            "documents",
            ["document_id"],
            ["id"],
        )

        op.drop_constraint(
            "open_questions_document_id_fkey", "open_questions", type_="foreignkey"
        )
        op.create_foreign_key(
            "open_questions_document_id_fkey",
            "open_questions",
            "documents",
            ["document_id"],
            ["id"],
        )

    inspector = inspect(op.get_bind())
    existing = {c["name"] for c in inspector.get_columns("clause_findings")}
    if "relevance_reason" in existing:
        op.drop_column("clause_findings", "relevance_reason")
    if "relevance_score" in existing:
        op.drop_column("clause_findings", "relevance_score")
