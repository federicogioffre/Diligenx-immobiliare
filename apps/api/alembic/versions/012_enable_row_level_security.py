"""enable row level security on tenant-scoped tables

Revision ID: 012
Revises: 011
Create Date: 2026-05-16

Adds defense-in-depth: even if a future application bug forgets to filter
by owner, Postgres itself refuses to return rows belonging to other tenants.

How it works:
  - Every request that touches a tenant-scoped table must first execute
    ``SET app.current_user_id = <id>`` (session-level, so it survives the
    multiple commits a pipeline stage performs). The auth dependency does this
    automatically via ``app.db.tenant_context.set_tenant_context``.
  - Each tenant-scoped table has a policy that resolves ownership back to
    ``users.id`` (sometimes via the workspaces/deals/documents chain).
  - When the GUC is unset (NULL), the policy returns NULL → no rows visible.
    Safer default than ``false``: an authenticated bug looks like an empty
    result set, easy to spot.

IMPORTANT — Postgres roles:
  Superusers and roles with BYPASSRLS ignore RLS unconditionally. For these
  policies to ACTUALLY enforce, the API must connect as a non-superuser role
  without BYPASSRLS. On Railway the default ``postgres`` user is a superuser,
  so this migration is a no-op there until DATABASE_URL is rewired to a
  dedicated app role. See CLAUDE.md → "Enforcing RLS in production".

SQLite (test) databases do not support RLS; this migration short-circuits.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TENANT_SCOPED_BY_OWNER = "workspaces"  # owner_id column directly

_TENANT_SCOPED_BY_WORKSPACE = ("deals",)  # workspace_id column

_TENANT_SCOPED_BY_DEAL = (
    "documents",
    "red_flags",
    "reports",
    "agent_runs",
    "agent_findings",
    "open_questions",
    "missing_documents",
    "company_profiles",
)

_TENANT_SCOPED_BY_DOCUMENT = (
    "document_chunks",
    "clause_findings",
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    # --- workspaces: owner_id is the direct tenant key -----------------------
    op.execute(
        """
        ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
        ALTER TABLE workspaces FORCE ROW LEVEL SECURITY;
        CREATE POLICY workspaces_tenant_isolation ON workspaces
            USING (owner_id = current_setting('app.current_user_id', true)::int)
            WITH CHECK (owner_id = current_setting('app.current_user_id', true)::int);
        """
    )

    # --- deals: tenant key is workspaces.owner_id --------------------------
    for table in _TENANT_SCOPED_BY_WORKSPACE:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (
                    EXISTS (
                        SELECT 1 FROM workspaces w
                        WHERE w.id = {table}.workspace_id
                          AND w.owner_id = current_setting('app.current_user_id', true)::int
                    )
                )
                WITH CHECK (
                    EXISTS (
                        SELECT 1 FROM workspaces w
                        WHERE w.id = {table}.workspace_id
                          AND w.owner_id = current_setting('app.current_user_id', true)::int
                    )
                );
            """
        )

    # --- documents/red_flags/etc.: tenant key resolves via deals → workspaces ---
    for table in _TENANT_SCOPED_BY_DEAL:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (
                    EXISTS (
                        SELECT 1 FROM deals d
                        JOIN workspaces w ON w.id = d.workspace_id
                        WHERE d.id = {table}.deal_id
                          AND w.owner_id = current_setting('app.current_user_id', true)::int
                    )
                )
                WITH CHECK (
                    EXISTS (
                        SELECT 1 FROM deals d
                        JOIN workspaces w ON w.id = d.workspace_id
                        WHERE d.id = {table}.deal_id
                          AND w.owner_id = current_setting('app.current_user_id', true)::int
                    )
                );
            """
        )

    # --- document_chunks / clause_findings: via documents → deals → workspaces --
    for table in _TENANT_SCOPED_BY_DOCUMENT:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (
                    EXISTS (
                        SELECT 1 FROM documents doc
                        JOIN deals d ON d.id = doc.deal_id
                        JOIN workspaces w ON w.id = d.workspace_id
                        WHERE doc.id = {table}.document_id
                          AND w.owner_id = current_setting('app.current_user_id', true)::int
                    )
                )
                WITH CHECK (
                    EXISTS (
                        SELECT 1 FROM documents doc
                        JOIN deals d ON d.id = doc.deal_id
                        JOIN workspaces w ON w.id = d.workspace_id
                        WHERE doc.id = {table}.document_id
                          AND w.owner_id = current_setting('app.current_user_id', true)::int
                    )
                );
            """
        )


def downgrade() -> None:
    if not _is_postgres():
        return

    all_tables = (
        (_TENANT_SCOPED_BY_OWNER,)
        + _TENANT_SCOPED_BY_WORKSPACE
        + _TENANT_SCOPED_BY_DEAL
        + _TENANT_SCOPED_BY_DOCUMENT
    )
    for table in all_tables:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
