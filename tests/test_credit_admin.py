import pytest

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models import OAuthIdentity, User
from app.models.credit_transaction import CreditTransaction


def _headers(user):
    token = create_access_token(user.email, user_id=user.id, hashed_password=user.hashed_password)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(db, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", ["Boss@Example.com"])
    user = User(email="boss@example.com", hashed_password=hash_password("Str0ng-password!"))
    db.add(user)
    db.flush()
    db.add(OAuthIdentity(user_id=user.id, provider="google", subject="g-1", email="boss@example.com"))
    db.commit()
    db.refresh(user)
    return user


def test_admin_grants_and_removes_credits(client, db, admin, test_user):
    headers = _headers(admin)
    assert client.get("/users/me", headers=headers).json()["is_admin"] is True
    response = client.post("/admin/credits", headers=headers,
                           json={"email": "TEST@example.com", "amount": 500, "note": "beta"})
    assert response.status_code == 200, response.text
    assert response.json()["credit_balance"] == 500
    assert client.post("/admin/credits", headers=headers,
                       json={"email": "test@example.com", "amount": -200}).json()["credit_balance"] == 300
    assert client.post("/admin/credits", headers=headers,
                       json={"email": "test@example.com", "amount": -301}).status_code == 400
    assert client.post("/admin/credits", headers=headers,
                       json={"email": "test@example.com", "amount": 0}).status_code == 422
    assert client.post("/admin/credits", headers=headers,
                       json={"email": "nobody@example.com", "amount": 5}).status_code == 404
    notes = [t.note for t in db.query(CreditTransaction).order_by(CreditTransaction.id)]
    assert notes == ["beta · boss@example.com", "boss@example.com"]
    accounts = client.get("/admin/users?q=test", headers=headers).json()
    assert [(a["email"], a["credit_balance"]) for a in accounts] == [("test@example.com", 300)]


def test_non_admin_is_refused(client, test_user, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", [])
    assert client.get("/admin/users", headers=auth_headers).status_code == 403
    assert client.post("/admin/credits", headers=auth_headers,
                       json={"email": "test@example.com", "amount": 5}).status_code == 403
    assert client.get("/users/me", headers=auth_headers).json()["is_admin"] is False


def test_admin_address_needs_a_provider_vouched_sign_in(client, test_user, auth_headers, monkeypatch):
    # Registration does not verify email: a password account under an
    # administrator's address must not inherit the role.
    monkeypatch.setattr(settings, "ADMIN_EMAILS", ["test@example.com"])
    assert client.get("/admin/users", headers=auth_headers).status_code == 403


def test_me_reports_credit_state(client, test_user, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "CREDITS_ENABLED", True)
    monkeypatch.setattr(settings, "CREDITS_UNLIMITED_EMAILS", ["test@example.com"])
    body = client.get("/users/me", headers=auth_headers).json()
    assert (body["credits_enabled"], body["credits_unlimited"], body["credit_balance"]) == (True, True, 0)
