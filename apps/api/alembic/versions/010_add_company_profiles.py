"""create company_profiles table

Revision ID: 010
Revises: 009
Create Date: 2026-06-10

Stores the "Corporate Introductory Information" record produced by the
corporate_intro_agent for each target company identified in a deal —
mirrors the columns of the corresponding section in professional red-flag
DD reports.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("deals.id"), nullable=False, index=True),
        sa.Column("company_name", sa.String(500), nullable=False),
        sa.Column("legal_form", sa.String(200), nullable=True),
        sa.Column("incorporation_date", sa.String(100), nullable=True),
        sa.Column("registered_office", sa.String(500), nullable=True),
        sa.Column("corporate_capital", sa.Text(), nullable=True),
        sa.Column("shareholders", sa.Text(), nullable=True),
        sa.Column("pledge", sa.Text(), nullable=True),
        sa.Column("managing_body", sa.Text(), nullable=True),
        sa.Column("auditors", sa.Text(), nullable=True),
        sa.Column("auditing_company", sa.Text(), nullable=True),
        sa.Column("business", sa.Text(), nullable=True),
        sa.Column("fiscal_year", sa.String(200), nullable=True),
        sa.Column("duration", sa.String(200), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "source_document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("company_profiles")
