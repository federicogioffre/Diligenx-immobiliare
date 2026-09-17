"""Treat an unset/reset transaction-local tenant as no access, not a cast error."""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def _policies(tenant):
    yield "workspaces", f"owner_id = {tenant}"
    yield "deals", f"EXISTS (SELECT 1 FROM workspaces w WHERE w.id = deals.workspace_id AND w.owner_id = {tenant})"
    for table in ("documents", "red_flags", "reports", "agent_runs", "agent_findings", "open_questions", "missing_documents", "company_profiles"):
        yield table, f"EXISTS (SELECT 1 FROM deals d JOIN workspaces w ON w.id = d.workspace_id WHERE d.id = {table}.deal_id AND w.owner_id = {tenant})"
    for table in ("document_chunks", "clause_findings"):
        yield table, f"EXISTS (SELECT 1 FROM documents doc JOIN deals d ON d.id = doc.deal_id JOIN workspaces w ON w.id = d.workspace_id WHERE doc.id = {table}.document_id AND w.owner_id = {tenant})"


def _apply(tenant):
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, expression in _policies(tenant):
        op.execute(f"ALTER POLICY {table}_tenant_isolation ON {table} USING ({expression}) WITH CHECK ({expression})")


def upgrade():
    _apply("NULLIF(current_setting('app.current_user_id', true), '')::int")


def downgrade():
    _apply("current_setting('app.current_user_id', true)::int")
