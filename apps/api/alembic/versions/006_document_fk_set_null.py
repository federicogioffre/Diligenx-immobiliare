"""Fix nullable document FKs to use ON DELETE SET NULL

Revision ID: 006
Revises: 005
Create Date: 2026-03-25

Without this migration, deleting a Document that is referenced by
red_flags.source_document_id or agent_runs.document_id raises a
FK constraint violation (500 Internal Server Error).
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite does not enforce FK constraints by default in tests;
        # no DDL change needed.
        return

    # ── red_flags.source_document_id ──────────────────────────────────────
    op.drop_constraint(
        "red_flags_source_document_id_fkey", "red_flags", type_="foreignkey"
    )
    op.create_foreign_key(
        "red_flags_source_document_id_fkey",
        "red_flags",
        "documents",
        ["source_document_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── agent_runs.document_id ─────────────────────────────────────────────
    op.drop_constraint(
        "agent_runs_document_id_fkey", "agent_runs", type_="foreignkey"
    )
    op.create_foreign_key(
        "agent_runs_document_id_fkey",
        "agent_runs",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Restore plain FK (no ON DELETE action)
    op.drop_constraint(
        "red_flags_source_document_id_fkey", "red_flags", type_="foreignkey"
    )
    op.create_foreign_key(
        "red_flags_source_document_id_fkey",
        "red_flags",
        "documents",
        ["source_document_id"],
        ["id"],
    )

    op.drop_constraint(
        "agent_runs_document_id_fkey", "agent_runs", type_="foreignkey"
    )
    op.create_foreign_key(
        "agent_runs_document_id_fkey",
        "agent_runs",
        "documents",
        ["document_id"],
        ["id"],
    )
