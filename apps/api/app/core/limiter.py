"""
Rate limiter — slowapi backed by in-memory storage (single instance).

Usage in a route module:
    from fastapi import Request
    from app.core.limiter import limiter

    @router.post("/login")
    @limiter.limit("10/minute")
    def login(request: Request, ...):
        ...

The limiter instance and the exception handler are both registered in main.py.

Who is "the client"
-------------------
Browsers reach the API through the frontend's /api rewrite, so the TCP peer
uvicorn sees is the platform's proxy in front of the API, the same address
for every user: keyed on it, "10 logins a minute" was ten for everybody and
anyone could lock the whole login out. The frontend middleware therefore
forwards the address the browser connected from in ``CLIENT_IP_HEADER``,
together with ``PROXY_SHARED_SECRET``. The header is trusted only when the
secret matches, so a client calling the API directly cannot pose as someone
else's address; without a secret configured, the peer address is used as
before.

Per-account budgets
-------------------
An IP budget does not protect one account from guesses spread over many
addresses, nor a mailbox from reset emails requested from many addresses.
``account_budget_exceeded`` / ``spend_account_budget`` keep a separate
counter per (scope, email) in the same storage.
"""

import hmac
import ipaddress

from fastapi import Request
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

CLIENT_IP_HEADER = "x-diligenx-client-ip"
PROXY_SECRET_HEADER = "x-diligenx-proxy-secret"


def client_ip(request: Request) -> str:
    """The browser's address when the frontend vouches for it, else the TCP peer."""
    secret = settings.PROXY_SHARED_SECRET
    if secret:
        presented = request.headers.get(PROXY_SECRET_HEADER, "")
        forwarded = request.headers.get(CLIENT_IP_HEADER, "").strip()
        if forwarded and hmac.compare_digest(presented.encode(), secret.encode()):
            try:
                return str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip, default_limits=["200/minute"])


def account_budget_exceeded(scope: str, email: str, limit: str) -> bool:
    """True when the per-account budget *limit* (e.g. "10/15minutes") is spent."""
    if not limiter.enabled:
        return False
    return not limiter.limiter.test(parse(limit), scope, email.strip().lower())


def spend_account_budget(scope: str, email: str, limit: str) -> None:
    if limiter.enabled:
        limiter.limiter.hit(parse(limit), scope, email.strip().lower())
