"""Sign-in with Microsoft and Google: the OpenID Connect flow end to end,
with the providers' discovery, token and key endpoints replaced by a local
signer — no network."""
import base64
import time
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from app.core.config import settings
from app.core.security import create_access_token, has_usable_password
from app.models.oauth_identity import OAuthIdentity
from app.models.user import User
from app.services import oauth

MS_TENANT = "11111111-2222-3333-4444-555555555555"
MS_ISSUER_TEMPLATE = "https://login.microsoftonline.com/{tenantid}/v2.0"
GOOGLE_ISSUER = "https://accounts.google.com"


def _b64(n: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()


class FakeIdP:
    """Discovery, JWKS and token endpoints of both providers."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = self.key.public_key().public_numbers()
        self.jwk = {"kty": "RSA", "kid": "k1", "use": "sig", "alg": "RS256",
                    "n": _b64(numbers.n), "e": _b64(numbers.e)}
        self.id_token_claims: dict = {}
        self.token_status = 200
        self.token_requests: list[dict] = []

    def get_json(self, url: str) -> dict:
        if "login.microsoftonline.com" in url and url.endswith("openid-configuration"):
            return {"issuer": MS_ISSUER_TEMPLATE,
                    "authorization_endpoint": "https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize",
                    "token_endpoint": "https://login.microsoftonline.com/organizations/oauth2/v2.0/token",
                    "jwks_uri": "https://login.microsoftonline.com/organizations/discovery/v2.0/keys"}
        if "accounts.google.com" in url:
            return {"issuer": GOOGLE_ISSUER,
                    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs"}
        if url.endswith("/keys") or url.endswith("/certs"):
            return {"keys": [self.jwk]}
        raise AssertionError(f"unexpected GET {url}")

    def post_form(self, url: str, data: dict) -> tuple[int, dict]:
        self.token_requests.append({"url": url, **data})
        if self.token_status != 200:
            return self.token_status, {"error": "invalid_grant"}
        return 200, {"id_token": self.sign(self.id_token_claims), "token_type": "Bearer"}

    def sign(self, claims: dict, kid: str = "k1") -> str:
        from cryptography.hazmat.primitives import serialization
        pem = self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())
        return jwt.encode(claims, pem.decode(), algorithm="RS256", headers={"kid": kid})


@pytest.fixture(autouse=True)
def idp(monkeypatch):
    fake = FakeIdP()
    monkeypatch.setattr(oauth, "_http_get_json", fake.get_json)
    monkeypatch.setattr(oauth, "_http_post_form", fake.post_form)
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", "ms-client")
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_SECRET", "ms-secret")
    monkeypatch.setattr(settings, "MICROSOFT_TENANT", "organizations")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "g-client")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "g-secret")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example")
    monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", False)
    oauth.clear_caches()
    yield fake
    oauth.clear_caches()


def _claims(provider: str, nonce: str, **overrides) -> dict:
    now = int(time.time())
    if provider == "microsoft":
        base = {"iss": f"https://login.microsoftonline.com/{MS_TENANT}/v2.0", "aud": "ms-client",
                "tid": MS_TENANT, "sub": "ms-subject-1", "email": "Avvocato@Studio.it",
                "xms_edov": True, "name": "Avv. Rossi"}
    else:
        base = {"iss": GOOGLE_ISSUER, "aud": "g-client", "sub": "g-subject-1",
                "email": "avvocato@studio.it", "email_verified": True, "name": "Avv. Rossi"}
    base.update({"iat": now, "exp": now + 600, "nonce": nonce})
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def _start(client, provider="microsoft", next_path=None):
    params = {"next": next_path} if next_path else {}
    resp = client.get(f"/auth/oauth/{provider}/start", params=params, follow_redirects=False)
    assert resp.status_code == 303, resp.text
    query = parse_qs(urlparse(resp.headers["location"]).query)
    pending = resp.cookies.get("dm_oauth")
    assert pending
    nonce = jwt.get_unverified_claims(pending)["nonce"]
    return query, nonce


def _sign_in(client, idp, provider="microsoft", next_path=None, **claim_overrides):
    query, nonce = _start(client, provider, next_path)
    idp.id_token_claims = _claims(provider, nonce, **claim_overrides)
    return client.get(f"/auth/oauth/{provider}/callback",
                      params={"code": "auth-code", "state": query["state"][0]}, follow_redirects=False)


def _error_of(resp) -> str | None:
    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    return parse_qs(location.query).get("oauth_error", [None])[0]


# ── Configuration ───────────────────────────────────────────────────────────

def test_providers_lists_only_configured(client, monkeypatch):
    assert client.get("/auth/oauth/providers").json() == {"providers": ["google", "microsoft"]}
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")
    assert client.get("/auth/oauth/providers").json() == {"providers": ["microsoft"]}


def test_unconfigured_provider_cannot_start(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    assert client.get("/auth/oauth/google/start", follow_redirects=False).status_code == 404
    assert client.get("/auth/oauth/github/start", follow_redirects=False).status_code == 404


# ── Start ───────────────────────────────────────────────────────────────────

def test_start_redirects_with_pkce_state_and_nonce(client):
    resp = client.get("/auth/oauth/microsoft/start", follow_redirects=False)
    location = urlparse(resp.headers["location"])
    assert location.netloc == "login.microsoftonline.com"
    query = parse_qs(location.query)
    assert query["client_id"] == ["ms-client"]
    assert query["redirect_uri"] == ["https://app.example/api/auth/oauth/microsoft/callback"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["openid email profile"]
    pending = jwt.get_unverified_claims(resp.cookies["dm_oauth"])
    assert query["state"] == [pending["state"]] and query["nonce"] == [pending["nonce"]]
    # The challenge is derived from the verifier kept in the cookie, never sent.
    import hashlib
    expected = base64.urlsafe_b64encode(hashlib.sha256(pending["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected]
    assert "verifier" not in resp.headers["location"]
    cookie = next(c for c in resp.headers.get_list("set-cookie") if c.startswith("dm_oauth="))
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower()


# ── Callback: success paths ─────────────────────────────────────────────────

def test_first_microsoft_sign_in_creates_account_without_password(client, db, idp):
    resp = _sign_in(client, idp, "microsoft")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login/complete?next=%2Fdashboard"
    assert resp.cookies.get("dm_token")
    cleared = next(c for c in resp.headers.get_list("set-cookie") if c.startswith("dm_oauth="))
    assert "Max-Age=0" in cleared or 'dm_oauth=""' in cleared

    user = db.query(User).filter(User.email == "avvocato@studio.it").one()
    assert user.full_name == "Avv. Rossi"
    assert not has_usable_password(user.hashed_password)
    assert [(i.provider, i.subject) for i in user.oauth_identities] == [("microsoft", "ms-subject-1")]

    # The token exchange carried the PKCE verifier and the exact redirect URI.
    request = idp.token_requests[-1]
    assert request["code"] == "auth-code" and request["code_verifier"]
    assert request["redirect_uri"] == "https://app.example/api/auth/oauth/microsoft/callback"

    me = client.get("/users/me", cookies={"dm_token": resp.cookies["dm_token"]})
    assert me.status_code == 200
    assert me.json()["has_password"] is False
    assert me.json()["auth_providers"] == ["microsoft"]


def test_returning_identity_opens_the_same_account(client, db, idp):
    _sign_in(client, idp, "microsoft")
    # The address changed at the provider: the subject still identifies the person.
    resp = _sign_in(client, idp, "microsoft", email="renamed@studio.it", xms_edov=False)
    assert resp.headers["location"].startswith("/login/complete")
    assert db.query(User).count() == 1


def test_verified_email_links_existing_password_account(client, db, test_user, idp):
    resp = _sign_in(client, idp, "google", email="TEST@example.com")
    assert resp.headers["location"].startswith("/login/complete")
    db.refresh(test_user)
    assert test_user.auth_providers == ["google"]
    # The password was set by someone the provider never vouched for.
    assert not test_user.has_password
    assert db.query(User).count() == 1


def test_pre_registered_password_stops_working_once_the_owner_signs_in(client, db, idp):
    # Someone registers the address before its owner ever uses Diligenx...
    assert client.post("/auth/register", json={
        "email": "avvocato@studio.it", "password": "attacker-pass"}).status_code == 201
    login = client.post("/auth/login", data={"username": "avvocato@studio.it", "password": "attacker-pass"})
    squatter_session = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/users/me", headers=squatter_session).status_code == 200

    # ...then the owner signs in with Google, which vouches for the mailbox.
    resp = _sign_in(client, idp, "google")
    assert resp.headers["location"].startswith("/login/complete")
    assert db.query(User).count() == 1

    # Neither the password nor the session opened with it opens the account.
    client.cookies.clear()
    assert client.post("/auth/login", data={
        "username": "avvocato@studio.it", "password": "attacker-pass"}).status_code == 401
    assert client.get("/users/me", headers=squatter_session).status_code == 401


def test_pre_registered_admin_address_does_not_become_admin(client, db, idp, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", ["avvocato@studio.it"])
    client.post("/auth/register", json={"email": "Avvocato@Studio.it", "password": "attacker-pass"})
    _sign_in(client, idp, "microsoft")  # the owner, vouched by xms_edov
    client.cookies.clear()
    stored = db.query(User).one().email  # however registration spelled it
    login = client.post("/auth/login", data={"username": stored, "password": "attacker-pass"})
    if login.status_code == 200:
        squatter_session = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/users/me", headers=squatter_session).json()["is_admin"] is False
    assert login.status_code == 401
    assert db.query(User).count() == 1


def test_an_address_registers_once_whatever_its_case(client, db):
    assert client.post("/auth/register", json={
        "email": "Avvocato@Studio.it", "password": "first-pass1"}).status_code == 201
    assert db.query(User).one().email == "avvocato@studio.it"
    second = client.post("/auth/register", json={"email": "AVVOCATO@studio.it", "password": "second-pass"})
    assert second.status_code == 400
    login = client.post("/auth/login", data={"username": "AVVOCATO@Studio.IT", "password": "first-pass1"})
    assert login.status_code == 200


def test_next_is_kept_only_when_it_is_a_local_path(client, idp):
    resp = _sign_in(client, idp, "google", next_path="/deals/7?tab=report")
    assert resp.headers["location"] == "/login/complete?next=%2Fdeals%2F7%3Ftab%3Dreport"
    for hostile in ("//evil.example", "https://evil.example", "/\\evil.example"):
        resp = _sign_in(client, idp, "google", next_path=hostile)
        assert resp.headers["location"] == "/login/complete?next=%2Fdashboard"


# ── Callback: refusals ──────────────────────────────────────────────────────

def test_unverified_microsoft_email_cannot_claim_an_account(client, db, test_user, idp):
    # Any tenant admin can put any address on a work account.
    resp = _sign_in(client, idp, "microsoft", email="test@example.com", xms_edov=None)
    assert _error_of(resp) == "email_not_verified"
    assert test_user.oauth_identities == []
    assert db.query(OAuthIdentity).count() == 0


def test_unverified_google_email_is_refused(client, idp):
    assert _error_of(_sign_in(client, idp, "google", email_verified=False)) == "email_not_verified"


def test_personal_microsoft_account_email_counts_as_verified(client, idp):
    resp = _sign_in(client, idp, "microsoft", tid=oauth.MICROSOFT_CONSUMER_TENANT, xms_edov=None,
                    iss=f"https://login.microsoftonline.com/{oauth.MICROSOFT_CONSUMER_TENANT}/v2.0")
    assert resp.headers["location"].startswith("/login/complete")


def test_missing_email_is_refused(client, idp):
    assert _error_of(_sign_in(client, idp, "google", email=None)) == "email_missing"


def test_disabled_account_is_refused(client, db, test_user, idp):
    test_user.is_active = False
    db.commit()
    assert _error_of(_sign_in(client, idp, "google", email="test@example.com")) == "account_disabled"


def test_state_mismatch_is_refused(client, idp):
    _, nonce = _start(client, "google")
    idp.id_token_claims = _claims("google", nonce)
    resp = client.get("/auth/oauth/google/callback", params={"code": "c", "state": "forged"},
                      follow_redirects=False)
    assert _error_of(resp) == "invalid_state"
    assert not idp.token_requests


def test_callback_without_the_browser_cookie_is_refused(client, idp):
    query, _ = _start(client, "google")
    client.cookies.clear()
    resp = client.get("/auth/oauth/google/callback", params={"code": "c", "state": query["state"][0]},
                      follow_redirects=False)
    assert _error_of(resp) == "invalid_state"


def test_cookie_from_another_provider_is_refused(client, idp):
    query, _ = _start(client, "google")
    resp = client.get("/auth/oauth/microsoft/callback", params={"code": "c", "state": query["state"][0]},
                      follow_redirects=False)
    assert _error_of(resp) == "invalid_state"


def test_user_cancelling_at_the_provider(client):
    query, _ = _start(client, "microsoft")
    resp = client.get("/auth/oauth/microsoft/callback",
                      params={"error": "access_denied", "state": query["state"][0]}, follow_redirects=False)
    assert _error_of(resp) == "cancelled"
    assert "dm_token" not in resp.cookies


def test_failed_code_exchange(client, idp):
    idp.token_status = 400
    assert _error_of(_sign_in(client, idp, "google")) == "exchange_failed"


@pytest.mark.parametrize("override", [
    {"aud": "someone-else"},
    {"iss": "https://login.microsoftonline.com/99999999-0000-0000-0000-000000000000/v2.0"},
    {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
])
def test_id_token_claims_are_checked(client, idp, override):
    assert _error_of(_sign_in(client, idp, "microsoft", **override)) == "invalid_token"


def test_replayed_nonce_is_refused(client, idp):
    query, _ = _start(client, "google")
    idp.id_token_claims = _claims("google", "a-nonce-from-another-sign-in")
    resp = client.get("/auth/oauth/google/callback", params={"code": "c", "state": query["state"][0]},
                      follow_redirects=False)
    assert _error_of(resp) == "invalid_token"


def test_token_signed_by_another_key_is_refused(client, idp, monkeypatch):
    query, nonce = _start(client, "google")
    impostor = FakeIdP()
    claims = _claims("google", nonce)
    monkeypatch.setattr(oauth, "_http_post_form", lambda url, data: (200, {"id_token": impostor.sign(claims)}))
    resp = client.get("/auth/oauth/google/callback", params={"code": "c", "state": query["state"][0]},
                      follow_redirects=False)
    assert _error_of(resp) == "invalid_token"


def test_unknown_key_id_refetches_the_key_set_once(client, idp, monkeypatch):
    calls = []
    monkeypatch.setattr(oauth, "_http_get_json", lambda url: (calls.append(url), idp.get_json(url))[1])
    query, nonce = _start(client, "google")
    claims = _claims("google", nonce)
    monkeypatch.setattr(oauth, "_http_post_form",
                        lambda url, data: (200, {"id_token": idp.sign(claims, kid="rotated")}))
    resp = client.get("/auth/oauth/google/callback", params={"code": "c", "state": query["state"][0]},
                      follow_redirects=False)
    assert _error_of(resp) == "invalid_token"
    assert sum(url.endswith("/certs") for url in calls) == 2


# ── Accounts without a password ─────────────────────────────────────────────

def _oauth_only_user(db) -> User:
    from app.core.security import make_unusable_password
    user = User(email="oauth@studio.it", hashed_password=make_unusable_password())
    db.add(user)
    db.commit()
    return user


def test_no_password_opens_an_account_without_one(client, db):
    user = _oauth_only_user(db)
    resp = client.post("/auth/login", data={"username": user.email, "password": user.hashed_password})
    assert resp.status_code == 401


def test_password_reset_gives_an_oauth_account_a_password(client, db):
    from app.core.security import create_password_reset_token
    user = _oauth_only_user(db)
    token = create_password_reset_token(user.email, user.hashed_password)
    assert client.post("/auth/reset-password", json={"token": token, "new_password": "nuovapass123"}).status_code == 204
    resp = client.post("/auth/login", data={"username": user.email, "password": "nuovapass123"})
    assert resp.status_code == 200


def _token_issued(user: User, seconds_ago: int) -> str:
    claims = jwt.get_unverified_claims(
        create_access_token(user.email, user_id=user.id, hashed_password=user.hashed_password))
    claims["iat"] = int(time.time()) - seconds_ago
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def test_oauth_account_deletion_needs_a_recent_sign_in(client, db):
    user = _oauth_only_user(db)
    stale = {"Authorization": f"Bearer {_token_issued(user, 3600)}"}
    resp = client.request("DELETE", "/users/me", json={}, headers=stale)
    assert resp.status_code == 403 and resp.json()["detail"] == "reauth_required"

    fresh = {"Authorization": f"Bearer {_token_issued(user, 30)}"}
    assert client.request("DELETE", "/users/me", json={}, headers=fresh).status_code == 204
    db.expire_all()
    assert db.query(User).count() == 0


def test_deletion_removes_the_linked_identities(client, db, idp):
    resp = _sign_in(client, idp, "google")
    token = resp.cookies["dm_token"]
    assert client.request("DELETE", "/users/me", json={}, cookies={"dm_token": token}).status_code == 204
    db.expire_all()
    assert db.query(OAuthIdentity).count() == 0


def test_password_account_still_needs_its_password_to_delete(client, test_user, auth_headers):
    assert client.request("DELETE", "/users/me", json={}, headers=auth_headers).status_code == 403
    assert client.request("DELETE", "/users/me", json={"password": "testpass123"},
                          headers=auth_headers).status_code == 204
