"""Regression test for the production incident where every authenticated
request after the first 500'd on Postgres.

Root cause: the `checkin` pool event (app/db/session.py) ran
`RESET app.current_user_id` but left psycopg2's implicit transaction open.
The connection went back into the pool idle-in-transaction; the next
checkout's `pool_pre_ping` (which sets autocommit=True) then raised
"set_session cannot be used inside a transaction" — turning every REUSED
connection into a 500. Login worked (fresh connection); the very next
request failed. That's exactly what shipped to production.

Invisible on the default (SQLite) suite for two independent reasons:
  1. Both the checkin handler and set_tenant_context are no-ops on SQLite.
  2. tests/conftest.py's `client` fixture overrides get_db() to reuse one
     already-open Session for the whole test, so it never exercises the
     real pool's checkout/checkin cycle regardless of DB backend.

This suite uses the app UNMODIFIED — no dependency overrides — against a
real Postgres, so the pool lifecycle runs exactly as it does in production.

Run via:

    export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/diligenx_ci
    export SECRET_KEY=<32+ chars, non-default>   # required once DATABASE_URL isn't sqlite
    export AUTH_COOKIE_SECURE=false              # only matters for cookie-based flows
    cd apps/api && alembic upgrade head
    python -m pytest ../../tests_integration -q
"""
from __future__ import annotations

import os
import uuid

import pytest

_DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not _DATABASE_URL.startswith("postgresql"),
    reason="set DATABASE_URL to a real Postgres DSN to run (see module docstring)",
)


@pytest.fixture(scope="module")
def client():
    """A TestClient with NO dependency overrides: real get_db(), real engine,
    real connection pool. That's the entire point of this suite."""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client) -> dict:
    """Register a fresh user (unique email) and return Bearer auth headers.

    Bearer (not the cookie) is used deliberately so this suite's assertions
    are about the DB connection pool, not about cookie-jar behaviour over
    plain http in TestClient.
    """
    email = f"pgintegration-{uuid.uuid4().hex[:12]}@example.com"
    password = "integration-test-pw-123"
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "PG Integration"},
    )
    assert resp.status_code == 201, resp.text
    resp = client.post("/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_repeated_authenticated_requests_reuse_connection_successfully(
    client, auth_headers
):
    """The exact production symptom: login succeeds (fresh connection), then
    every SUBSEQUENT authenticated request must also succeed, not just the
    first one that reuses a pooled connection. Sequential single-threaded
    requests hand back the same connection each time (QueuePool is LIFO), so
    this reliably exercises checkin -> pool_pre_ping on every iteration.
    """
    for i in range(8):
        resp = client.get("/workspaces/", headers=auth_headers)
        assert resp.status_code == 200, f"request #{i} failed: {resp.status_code} {resp.text}"


def test_tenant_context_guc_is_cleared_after_checkin(client, auth_headers):
    """Defense-in-depth: once a request has bound app.current_user_id and
    the connection is returned to the pool, no stale tenant context must
    leak to whoever checks that connection out next. Checked directly
    against Postgres, not just inferred from a 200."""
    from sqlalchemy import text
    from app.db.session import engine

    resp = client.get("/workspaces/", headers=auth_headers)
    assert resp.status_code == 200

    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT current_setting('app.current_user_id', true)")
        ).scalar()
    assert value in (None, ""), (
        f"app.current_user_id leaked across connection reuse: {value!r}"
    )
