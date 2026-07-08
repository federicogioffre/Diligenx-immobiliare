"""Tests for the account self-service endpoints (GDPR arts. 15/17/20).

Covers /users/me, /users/me/export and DELETE /users/me: shape of the
export, password confirmation on delete, full cascade erasure (DB rows
and stored files), cookie clearing, and auth requirements.
"""
import pytest

from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from app.models.red_flag import RedFlag, Severity
from app.models.user import User
from app.models.workspace import Workspace
from app.core.security import hash_password, create_access_token


@pytest.fixture
def second_user(db) -> User:
    user = User(
        email="other@example.com",
        hashed_password=hash_password("otherpass123"),
        full_name="Other User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def populated_account(db, test_user, test_workspace, test_deal):
    """A deal with one document and one red flag under the test user."""
    doc = Document(
        deal_id=test_deal.id,
        filename="contract.pdf",
        file_path=f"deals/{test_deal.id}/abc_contract.pdf",
        mime_type="application/pdf",
        file_size=1234,
        status=DocumentStatus.processed,
        raw_text="Some contract text.",
        language="it",
        page_count=3,
    )
    flag = RedFlag(
        deal_id=test_deal.id,
        title="Pledge over shares",
        issue="A pledge exists.",
        risk="Shares encumbered at closing.",
        recommendation="Obtain release as CP.",
        severity=Severity.high,
        category="pledge",
        confidence=0.9,
    )
    db.add_all([doc, flag])
    db.commit()
    return test_deal


# ── GET /users/me ──────────────────────────────────────────────────────────

class TestGetMe:

    def test_requires_auth(self, client):
        assert client.get("/users/me").status_code in (401, 403)

    def test_returns_current_user(self, client, auth_headers, test_user):
        resp = client.get("/users/me", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == test_user.email
        assert body["id"] == test_user.id
        assert "hashed_password" not in body


# ── GET /users/me/export ───────────────────────────────────────────────────

class TestExport:

    def test_requires_auth(self, client):
        assert client.get("/users/me/export").status_code in (401, 403)

    def test_is_downloadable_json(self, client, auth_headers, populated_account):
        resp = client.get("/users/me/export", headers=auth_headers)
        assert resp.status_code == 200
        assert "attachment" in resp.headers["content-disposition"]
        assert resp.headers["cache-control"] == "no-store"

    def test_contains_full_structure(self, client, auth_headers, populated_account):
        body = client.get("/users/me/export", headers=auth_headers).json()
        assert body["export_format_version"] == 1
        assert body["user"]["email"] == "test@example.com"
        assert len(body["workspaces"]) == 1
        deal = body["workspaces"][0]["deals"][0]
        assert deal["title"] == "Test Deal"
        assert deal["documents"][0]["filename"] == "contract.pdf"
        assert deal["red_flags"][0]["severity"] == "high"
        assert deal["red_flags"][0]["issue"] == "A pledge exists."

    def test_excludes_other_users_data(
        self, client, auth_headers, populated_account, db, second_user
    ):
        other_ws = Workspace(name="Other WS", owner_id=second_user.id)
        db.add(other_ws)
        db.commit()
        body = client.get("/users/me/export", headers=auth_headers).json()
        names = [w["name"] for w in body["workspaces"]]
        assert "Other WS" not in names


# ── DELETE /users/me ───────────────────────────────────────────────────────

class TestDeleteAccount:

    def test_requires_auth(self, client):
        resp = client.request(
            "DELETE", "/users/me", json={"password": "x"}
        )
        assert resp.status_code in (401, 403)

    def test_wrong_password_rejected(self, client, auth_headers, test_user):
        resp = client.request(
            "DELETE", "/users/me",
            headers=auth_headers,
            json={"password": "not-the-password"},
        )
        assert resp.status_code == 403

    def test_deletes_user_and_cascade(
        self, client, auth_headers, populated_account, db, test_user
    ):
        user_id = test_user.id
        deal_id = populated_account.id
        resp = client.request(
            "DELETE", "/users/me",
            headers=auth_headers,
            json={"password": "testpass123"},
        )
        assert resp.status_code == 204
        assert db.query(User).filter(User.id == user_id).first() is None
        assert db.query(Workspace).filter(Workspace.owner_id == user_id).count() == 0
        assert db.query(Deal).filter(Deal.id == deal_id).first() is None
        assert db.query(Document).filter(Document.deal_id == deal_id).count() == 0
        assert db.query(RedFlag).filter(RedFlag.deal_id == deal_id).count() == 0

    def test_deletes_stored_files(
        self, client, auth_headers, populated_account, monkeypatch
    ):
        deleted_keys: list[str] = []
        import app.api.routes.users as users_module
        monkeypatch.setattr(
            users_module, "delete_file", lambda key: deleted_keys.append(key)
        )
        resp = client.request(
            "DELETE", "/users/me",
            headers=auth_headers,
            json={"password": "testpass123"},
        )
        assert resp.status_code == 204
        assert deleted_keys == [f"deals/{populated_account.id}/abc_contract.pdf"]

    def test_other_users_survive(
        self, client, auth_headers, test_user, db, second_user
    ):
        other_ws = Workspace(name="Other WS", owner_id=second_user.id)
        db.add(other_ws)
        db.commit()
        client.request(
            "DELETE", "/users/me",
            headers=auth_headers,
            json={"password": "testpass123"},
        )
        assert db.query(User).filter(User.id == second_user.id).first() is not None
        assert db.query(Workspace).filter(Workspace.owner_id == second_user.id).count() == 1

    def test_session_cookies_cleared(self, client, auth_headers, test_user):
        resp = client.request(
            "DELETE", "/users/me",
            headers=auth_headers,
            json={"password": "testpass123"},
        )
        assert resp.status_code == 204
        set_cookie = ",".join(
            v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"
        )
        # Both session cookies are expired by the response.
        assert "dm_token=" in set_cookie
        assert "dm_authed=" in set_cookie
