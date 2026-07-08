"""Postgres Row-Level Security integration tests.

These tests verify that, when the API connects as a non-superuser role to a
real Postgres + RLS policies, queries are blocked at the DB engine level for
the wrong tenant — even when the application code "forgets" to filter.

Skipped on SQLite (the default test database). To run:

    export RLS_TEST_DATABASE_URL='postgresql://diligenx_app:pw@localhost/diligenx_test'
    python -m pytest tests/test_rls_isolation.py -v

The role used in ``RLS_TEST_DATABASE_URL`` MUST NOT be a superuser and MUST
NOT have the BYPASSRLS attribute, otherwise the policies are bypassed and
this test is meaningless. ``diligenx_app`` matches the production setup
documented in CLAUDE.md → "Enforcing RLS in production".
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

RLS_DSN = os.getenv("RLS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not RLS_DSN,
    reason="set RLS_TEST_DATABASE_URL to a non-superuser Postgres role to run",
)


@pytest.fixture(scope="module")
def pg_session():
    """Module-scoped session bound to the RLS test database.

    Wipes tenant-scoped tables on entry/exit so test data is isolated.
    """
    engine = create_engine(RLS_DSN, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = SessionLocal()

    # Reset before — and after — so a previous failed run doesn't poison us.
    _wipe(db)
    yield db
    _wipe(db)
    db.close()


def _wipe(db) -> None:
    """Truncate all tenant-scoped tables and users in dependency order.

    Runs in a context with BYPASSRLS via the migration role; if the test
    role can't TRUNCATE, the maintainer needs to grant it (see CLAUDE.md).
    """
    db.execute(text("SET app.current_user_id = '0'"))  # let policy see something
    for table in (
        "clause_findings",
        "document_chunks",
        "reports",
        "company_profiles",
        "open_questions",
        "missing_documents",
        "red_flags",
        "agent_findings",
        "agent_runs",
        "documents",
        "deals",
        "workspaces",
        "users",
    ):
        db.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
    db.commit()
    db.execute(text("RESET app.current_user_id"))
    db.commit()


def _create_tenant(db, email: str) -> tuple[int, int, int]:
    """Insert a User → Workspace → Deal triple owned by the new user.

    Uses raw SQL so it works regardless of which schema the test role can
    instantiate. Returns ``(user_id, workspace_id, deal_id)``.
    """
    # Insert user without RLS context — the users table has no policy.
    user_id = db.execute(
        text(
            "INSERT INTO users (email, hashed_password, is_active, created_at, updated_at) "
            "VALUES (:e, 'x', true, NOW(), NOW()) RETURNING id"
        ),
        {"e": email},
    ).scalar_one()
    db.commit()

    # For workspaces / deals we need the policy to let our INSERT through.
    db.execute(text("SET app.current_user_id = :uid"), {"uid": str(user_id)})
    workspace_id = db.execute(
        text(
            "INSERT INTO workspaces (name, owner_id, created_at, updated_at) "
            "VALUES ('w', :uid, NOW(), NOW()) RETURNING id"
        ),
        {"uid": user_id},
    ).scalar_one()
    deal_id = db.execute(
        text(
            "INSERT INTO deals (workspace_id, title, status, created_at, updated_at) "
            "VALUES (:wid, 't', 'draft', NOW(), NOW()) RETURNING id"
        ),
        {"wid": workspace_id},
    ).scalar_one()
    db.commit()
    db.execute(text("RESET app.current_user_id"))
    db.commit()
    return user_id, workspace_id, deal_id


def test_workspace_cross_tenant_select_returns_zero_rows(pg_session):
    """Tenant A cannot see tenant B's workspace even via raw SELECT *."""
    a_uid, a_wid, _ = _create_tenant(pg_session, "a@example.com")
    b_uid, b_wid, _ = _create_tenant(pg_session, "b@example.com")

    pg_session.execute(text("SET app.current_user_id = :uid"), {"uid": str(a_uid)})
    visible = pg_session.execute(text("SELECT id FROM workspaces")).scalars().all()
    pg_session.execute(text("RESET app.current_user_id"))

    assert a_wid in visible
    assert b_wid not in visible, "RLS leak: tenant A saw tenant B's workspace row"


def test_deal_cross_tenant_select_returns_zero_rows(pg_session):
    """A query without WHERE filter only returns the calling tenant's deals."""
    a_uid, _, a_did = _create_tenant(pg_session, "deal_a@example.com")
    b_uid, _, b_did = _create_tenant(pg_session, "deal_b@example.com")

    pg_session.execute(text("SET app.current_user_id = :uid"), {"uid": str(a_uid)})
    visible = pg_session.execute(text("SELECT id FROM deals")).scalars().all()
    pg_session.execute(text("RESET app.current_user_id"))

    assert a_did in visible
    assert b_did not in visible


def test_no_context_returns_zero_rows(pg_session):
    """With no ``app.current_user_id`` set, all tenant-scoped tables look empty.

    Safer default than ``true``: a forgotten ``set_tenant_context`` call
    surfaces as "no data" rather than "all data".
    """
    _create_tenant(pg_session, "ghost@example.com")

    # Explicitly do NOT set the GUC.
    pg_session.execute(text("RESET app.current_user_id"))
    visible = pg_session.execute(text("SELECT COUNT(*) FROM workspaces")).scalar_one()
    assert visible == 0


def test_update_other_tenants_row_affects_zero(pg_session):
    """An UPDATE without a WHERE filter only touches the calling tenant."""
    a_uid, a_wid, _ = _create_tenant(pg_session, "upd_a@example.com")
    b_uid, b_wid, _ = _create_tenant(pg_session, "upd_b@example.com")

    pg_session.execute(text("SET app.current_user_id = :uid"), {"uid": str(a_uid)})
    result = pg_session.execute(text("UPDATE workspaces SET name = 'HIJACKED'"))
    pg_session.commit()
    pg_session.execute(text("RESET app.current_user_id"))
    pg_session.commit()

    assert result.rowcount == 1, (
        f"RLS leak on UPDATE: expected 1 row, touched {result.rowcount}"
    )

    # Verify by switching to B's context and checking the name is intact.
    pg_session.execute(text("SET app.current_user_id = :uid"), {"uid": str(b_uid)})
    b_name = pg_session.execute(
        text("SELECT name FROM workspaces WHERE id = :wid"), {"wid": b_wid}
    ).scalar_one()
    pg_session.execute(text("RESET app.current_user_id"))
    pg_session.commit()

    assert b_name != "HIJACKED"
