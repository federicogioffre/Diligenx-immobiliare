"""Tests for HttpOnly cookie auth, logout, and SSE stream tickets.

The session JWT is set as an HttpOnly cookie at login (browser client) while
the Bearer header keeps working (API clients, rest of the suite). The SSE
stream is authenticated by a short-lived, deal-scoped ticket instead of the
full session JWT — and, critically, tickets must never be usable as session
tokens (and vice versa).
"""
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.core.config import settings
from app.core.security import create_access_token, create_stream_ticket
from app.models.deal import Deal
from app.models.user import User
from app.models.workspace import Workspace
from app.core.security import hash_password


@pytest.fixture(autouse=True)
def _insecure_cookies_for_http_testclient(monkeypatch):
    """TestClient's base URL is http://testserver and its cookie jar refuses
    to send Secure cookies over http — disable the Secure attribute here."""
    monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", False)


def _login(client, email="test@example.com", password="testpass123"):
    return client.post(
        "/auth/login",
        data={"username": email, "password": password},
    )


# ── Login sets the session cookies ─────────────────────────────────────────

def test_login_sets_httponly_session_cookie(client, test_user):
    resp = _login(client)
    assert resp.status_code == 200

    set_cookies = resp.headers.get_list("set-cookie")
    token_cookie = next((c for c in set_cookies if c.startswith("dm_token=")), None)
    assert token_cookie is not None
    assert "HttpOnly" in token_cookie
    assert "SameSite=lax" in token_cookie
    assert "Path=/" in token_cookie
    assert f"Max-Age={settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60}" in token_cookie
    # Host-only: no Domain attribute.
    assert "Domain=" not in token_cookie


def test_login_sets_non_httponly_authed_flag(client, test_user):
    resp = _login(client)
    set_cookies = resp.headers.get_list("set-cookie")
    flag_cookie = next((c for c in set_cookies if c.startswith("dm_authed=")), None)
    assert flag_cookie is not None
    assert "HttpOnly" not in flag_cookie


def test_login_response_is_not_cacheable(client, test_user):
    resp = _login(client)
    assert resp.headers.get("Cache-Control") == "no-store"


def test_login_still_returns_token_in_body(client, test_user):
    resp = _login(client)
    assert resp.json()["access_token"]


# ── Cookie authenticates API calls ─────────────────────────────────────────

def test_cookie_authenticates_protected_endpoint(client, test_user):
    _login(client)  # TestClient persists the cookie jar
    resp = client.get("/workspaces/")
    assert resp.status_code == 200


def test_bearer_still_works_and_wins(client, test_user, auth_headers):
    resp = client.get("/workspaces/", headers=auth_headers)
    assert resp.status_code == 200


def test_no_credentials_is_401(client, test_user):
    resp = client.get("/workspaces/")
    assert resp.status_code in (401, 403)


# ── Logout ──────────────────────────────────────────────────────────────────

def test_logout_clears_session(client, test_user):
    _login(client)
    assert client.get("/workspaces/").status_code == 200

    resp = client.post("/auth/logout")
    assert resp.status_code == 204

    assert client.get("/workspaces/").status_code in (401, 403)


def test_logout_works_without_a_session(client):
    """A broken/expired session must still be able to clear its cookies."""
    resp = client.post("/auth/logout")
    assert resp.status_code == 204


# ── Token typing: tickets are not session tokens ───────────────────────────

def test_stream_ticket_rejected_as_bearer(client, test_user, test_deal):
    ticket = create_stream_ticket(test_user.email, test_deal.id)
    resp = client.get(
        "/workspaces/", headers={"Authorization": f"Bearer {ticket}"}
    )
    assert resp.status_code == 401


def test_stream_ticket_rejected_as_session_cookie(client, test_user, test_deal):
    ticket = create_stream_ticket(test_user.email, test_deal.id)
    client.cookies.set("dm_token", ticket)
    resp = client.get("/workspaces/")
    assert resp.status_code == 401


# ── Stream tickets ──────────────────────────────────────────────────────────

def test_stream_ticket_issued_for_own_deal(client, test_user, test_deal, auth_headers):
    resp = client.post(f"/deals/{test_deal.id}/stream-ticket", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["ticket"]


def test_stream_ticket_404_for_foreign_deal(client, db, test_deal, auth_headers):
    other = User(
        email="other@example.com",
        hashed_password=hash_password("otherpass123"),
        full_name="Other",
    )
    db.add(other)
    db.commit()
    ws = Workspace(name="Other WS", owner_id=other.id)
    db.add(ws)
    db.commit()
    deal = Deal(workspace_id=ws.id, title="Foreign Deal")
    db.add(deal)
    db.commit()

    resp = client.post(f"/deals/{deal.id}/stream-ticket", headers=auth_headers)
    assert resp.status_code == 404


def test_stream_with_valid_ticket(client, test_user, test_deal, auth_headers):
    ticket = client.post(
        f"/deals/{test_deal.id}/stream-ticket", headers=auth_headers
    ).json()["ticket"]

    # test_deal is in `draft` status, so the generator emits one snapshot
    # and closes immediately — no infinite stream to consume.
    resp = client.get(f"/deals/{test_deal.id}/analysis-stream?ticket={ticket}")
    assert resp.status_code == 200
    assert resp.text.startswith("data: ")


def test_stream_rejects_ticket_for_other_deal(client, test_user, test_deal, auth_headers):
    ticket = create_stream_ticket(test_user.email, test_deal.id + 999)
    resp = client.get(f"/deals/{test_deal.id}/analysis-stream?ticket={ticket}")
    assert resp.status_code == 401


def test_stream_rejects_full_session_token(client, test_user, test_deal):
    """The old ?token=<session JWT> pattern must no longer work."""
    session_token = create_access_token(test_user.email, user_id=test_user.id, hashed_password=test_user.hashed_password)
    resp = client.get(
        f"/deals/{test_deal.id}/analysis-stream?ticket={session_token}"
    )
    assert resp.status_code == 401


def test_stream_rejects_expired_ticket(client, test_user, test_deal):
    expired = jwt.encode(
        {
            "sub": test_user.email,
            "scope": "stream",
            "deal_id": test_deal.id,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=5),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp = client.get(f"/deals/{test_deal.id}/analysis-stream?ticket={expired}")
    assert resp.status_code == 401


def test_stream_rejects_garbage_ticket(client, test_deal):
    resp = client.get(f"/deals/{test_deal.id}/analysis-stream?ticket=not-a-jwt")
    assert resp.status_code == 401
