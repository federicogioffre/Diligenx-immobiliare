"""Tests for the password-reset flow.

Covers: no user enumeration on forgot-password, token round-trip, reset
actually changes the password, single-use enforcement (fingerprint),
expiry/garbage rejection, minimum password length, and the mailer's
log-only fallback when SMTP is not configured.
"""
import pytest

from app.core.security import (
    create_password_reset_token,
    verify_password,
)
from app.models.user import User


class TestForgotPassword:

    def test_returns_202_for_existing_user(self, client, test_user):
        resp = client.post("/auth/forgot-password", json={"email": test_user.email})
        assert resp.status_code == 202

    def test_returns_202_for_unknown_email_no_enumeration(self, client):
        resp = client.post(
            "/auth/forgot-password", json={"email": "ghost@example.com"}
        )
        assert resp.status_code == 202

    def test_same_body_for_known_and_unknown(self, client, test_user):
        known = client.post(
            "/auth/forgot-password", json={"email": test_user.email}
        ).json()
        unknown = client.post(
            "/auth/forgot-password", json={"email": "ghost@example.com"}
        ).json()
        assert known == unknown

    def test_email_contains_reset_link(self, client, test_user, monkeypatch):
        sent: list[dict] = []
        import app.services.mailer as mailer
        monkeypatch.setattr(
            mailer, "send_email",
            lambda to, subject, body: sent.append(
                {"to": to, "subject": subject, "body": body}
            ) or True,
        )
        client.post("/auth/forgot-password", json={"email": test_user.email})
        assert len(sent) == 1
        assert sent[0]["to"] == test_user.email
        assert "/reset-password?token=" in sent[0]["body"]

    def test_no_email_for_unknown_address(self, client, monkeypatch):
        sent: list = []
        import app.services.mailer as mailer
        monkeypatch.setattr(
            mailer, "send_email", lambda **kw: sent.append(kw) or True
        )
        client.post("/auth/forgot-password", json={"email": "ghost@example.com"})
        assert sent == []


class TestResetPassword:

    def _token_for(self, user: User) -> str:
        return create_password_reset_token(user.email, user.hashed_password)

    def test_resets_password(self, client, db, test_user):
        token = self._token_for(test_user)
        resp = client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "brand-new-pass-1"},
        )
        assert resp.status_code == 204
        db.refresh(test_user)
        assert verify_password("brand-new-pass-1", test_user.hashed_password)

    def test_can_login_with_new_password(self, client, db, test_user):
        token = self._token_for(test_user)
        client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "brand-new-pass-2"},
        )
        resp = client.post(
            "/auth/login",
            data={"username": test_user.email, "password": "brand-new-pass-2"},
        )
        assert resp.status_code == 200

    def test_token_is_single_use(self, client, db, test_user):
        token = self._token_for(test_user)
        first = client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "first-new-pass-1"},
        )
        assert first.status_code == 204
        # Same token again: the fingerprint no longer matches the new hash.
        second = client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "second-new-pass-1"},
        )
        assert second.status_code == 400

    def test_garbage_token_rejected(self, client):
        resp = client.post(
            "/auth/reset-password",
            json={"token": "not-a-jwt", "new_password": "whatever-123"},
        )
        assert resp.status_code == 400

    def test_access_token_not_usable_as_reset_token(self, client, test_user):
        """A leaked session JWT must not allow a password reset (wrong scope)."""
        from app.core.security import create_access_token
        resp = client.post(
            "/auth/reset-password",
            json={
                "token": create_access_token(test_user.email),
                "new_password": "whatever-123",
            },
        )
        assert resp.status_code == 400

    def test_short_password_rejected(self, client, test_user):
        token = self._token_for(test_user)
        resp = client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "short"},
        )
        assert resp.status_code == 422


class TestMailerFallback:

    def test_send_email_logs_when_smtp_unconfigured(self, caplog):
        import logging
        from app.services.mailer import send_email, smtp_configured

        assert not smtp_configured()  # test env has no SMTP_HOST
        with caplog.at_level(logging.INFO, logger="app.services.mailer"):
            ok = send_email("x@example.com", "Subject", "Body with link")
        assert ok is False
        assert "NOT sent" in caplog.text
        assert "Body with link" in caplog.text
