"""Rate limits key on the real client, and per account where an IP budget
cannot protect one: behind the frontend proxy every request used to share the
proxy's address, so ten failed logins anywhere locked the login for everybody."""
import pytest
from starlette.requests import Request

from app.core.config import settings
from app.core.limiter import CLIENT_IP_HEADER, PROXY_SECRET_HEADER, client_ip, limiter

SECRET = "s" * 40


@pytest.fixture
def live_limiter(monkeypatch):
    monkeypatch.setattr(settings, "PROXY_SHARED_SECRET", SECRET)
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


def _from(ip: str, secret: str = SECRET) -> dict:
    return {CLIENT_IP_HEADER: ip, PROXY_SECRET_HEADER: secret}


def _request(headers: dict) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/", "client": ("10.0.0.1", 1234),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    })


# ── Who the client is ───────────────────────────────────────────────────────

def test_forwarded_address_is_used_with_the_shared_secret(monkeypatch):
    monkeypatch.setattr(settings, "PROXY_SHARED_SECRET", SECRET)
    assert client_ip(_request(_from("203.0.113.7"))) == "203.0.113.7"
    assert client_ip(_request(_from("2001:db8::1"))) == "2001:db8::1"


@pytest.mark.parametrize("headers", [
    _from("203.0.113.7", secret="wrong"),           # a client posing as someone else
    {CLIENT_IP_HEADER: "203.0.113.7"},              # no secret at all
    _from("not-an-ip"),                             # garbage under the right secret
    {PROXY_SECRET_HEADER: SECRET},                  # secret without an address
])
def test_otherwise_the_peer_address_is_used(monkeypatch, headers):
    monkeypatch.setattr(settings, "PROXY_SHARED_SECRET", SECRET)
    assert client_ip(_request(headers)) == "10.0.0.1"


def test_without_a_configured_secret_the_header_is_ignored(monkeypatch):
    monkeypatch.setattr(settings, "PROXY_SHARED_SECRET", "")
    assert client_ip(_request(_from("203.0.113.7", secret=""))) == "10.0.0.1"


# ── One client exhausting its budget leaves the others alone ────────────────

def test_one_address_exhausting_the_login_budget_does_not_lock_out_another(client, live_limiter):
    for n in range(10):
        client.post("/auth/login", data={"username": f"u{n}@x.it", "password": "nope-nope"},
                    headers=_from("198.51.100.1"))
    blocked = client.post("/auth/login", data={"username": "u10@x.it", "password": "nope-nope"},
                          headers=_from("198.51.100.1"))
    assert blocked.status_code == 429
    other = client.post("/auth/login", data={"username": "u11@x.it", "password": "nope-nope"},
                        headers=_from("198.51.100.2"))
    assert other.status_code == 401


# ── Per-account budgets ─────────────────────────────────────────────────────

def test_failed_logins_from_many_addresses_pause_that_account(client, test_user, live_limiter, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_FAILURES_PER_ACCOUNT", "3/15minutes")
    for n in range(3):
        resp = client.post("/auth/login", data={"username": test_user.email, "password": "wrong-guess"},
                           headers=_from(f"198.51.100.{n + 1}"))
        assert resp.status_code == 401
    # The right password, from yet another address and in another case, waits too.
    paused = client.post("/auth/login", data={"username": "TEST@example.com", "password": "testpass123"},
                         headers=_from("198.51.100.9"))
    assert paused.status_code == 429
    assert paused.headers["Retry-After"]


def test_successful_logins_do_not_spend_the_account_budget(client, test_user, live_limiter, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_FAILURES_PER_ACCOUNT", "2/15minutes")
    for n in range(4):
        resp = client.post("/auth/login", data={"username": test_user.email, "password": "testpass123"},
                           headers=_from(f"198.51.100.{n + 1}"))
        assert resp.status_code == 200


def test_another_account_is_not_paused(client, test_user, live_limiter, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_FAILURES_PER_ACCOUNT", "1/15minutes")
    client.post("/auth/login", data={"username": "victim@x.it", "password": "wrong-guess"},
                headers=_from("198.51.100.1"))
    ok = client.post("/auth/login", data={"username": test_user.email, "password": "testpass123"},
                     headers=_from("198.51.100.1"))
    assert ok.status_code == 200


def test_reset_emails_to_one_mailbox_are_capped_without_revealing_it(client, test_user, live_limiter,
                                                                      monkeypatch):
    import app.services.mailer as mailer
    sent: list = []
    monkeypatch.setattr(mailer, "send_email", lambda **kw: sent.append(kw) or True)
    monkeypatch.setattr(settings, "PASSWORD_RESETS_PER_ACCOUNT", "2/hour")
    answers = [
        client.post("/auth/forgot-password", json={"email": test_user.email},
                    headers=_from(f"198.51.100.{n + 1}"))
        for n in range(3)
    ]
    assert [a.status_code for a in answers] == [202, 202, 202]
    assert answers[2].json() == answers[0].json()
    assert len(sent) == 2
