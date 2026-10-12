"""Sign-in with Microsoft and Google over OpenID Connect.

Authorization-code flow with PKCE, a ``state`` bound to the browser and a
``nonce`` bound to the ID token. The ID token is the only identity evidence
used: its signature is checked against the provider's published keys, and
its issuer, audience, expiry and nonce against what this request expects.

Provider metadata and signing keys are fetched from the provider's
discovery document and cached in process.
"""
import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from jose import jwt

from app.core.config import settings

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10
DISCOVERY_TTL_SECONDS = 24 * 3600
JWKS_TTL_SECONDS = 3600
CLOCK_SKEW_SECONDS = 120

# Personal Microsoft accounts all sign in through this one tenant; their
# address is verified by Microsoft when the account is created.
MICROSOFT_CONSUMER_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"


class OAuthError(Exception):
    """A sign-in that cannot complete. ``code`` is shown to the login page."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class Provider:
    name: str
    discovery_url: str
    client_id: str
    client_secret: str
    scopes: str = "openid email profile"


@dataclass(frozen=True)
class OAuthProfile:
    provider: str
    subject: str
    email: str | None
    email_verified: bool
    name: str | None


def configured_providers() -> dict[str, Provider]:
    providers = {}
    if settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET:
        providers["microsoft"] = Provider(
            name="microsoft",
            discovery_url=(
                f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT}"
                "/v2.0/.well-known/openid-configuration"
            ),
            client_id=settings.MICROSOFT_CLIENT_ID,
            client_secret=settings.MICROSOFT_CLIENT_SECRET,
        )
    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        providers["google"] = Provider(
            name="google",
            discovery_url="https://accounts.google.com/.well-known/openid-configuration",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
        )
    return providers


def redirect_uri(provider: str) -> str:
    # The browser reaches the API through the frontend's /api proxy, so the
    # session cookie set by the callback lands on the frontend's origin.
    return f"{settings.FRONTEND_URL}/api/auth/oauth/{provider}/callback"


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


# ── HTTP (patched in tests) ─────────────────────────────────────────────────

def _http_get_json(url: str) -> dict:
    try:
        response = httpx.get(url, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("oauth_metadata_unavailable url=%s error=%s", url, exc)
        raise OAuthError("unavailable") from None


def _http_post_form(url: str, data: dict) -> tuple[int, dict]:
    try:
        response = httpx.post(url, data=data, timeout=HTTP_TIMEOUT_SECONDS,
                              headers={"Accept": "application/json"})
        return response.status_code, response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("oauth_token_endpoint_unavailable url=%s error=%s", url, exc)
        raise OAuthError("unavailable") from None


# ── Provider metadata ───────────────────────────────────────────────────────

_discovery_cache: dict[str, tuple[float, dict]] = {}
_jwks_cache: dict[str, tuple[float, list[dict]]] = {}


def _discovery(provider: Provider) -> dict:
    cached = _discovery_cache.get(provider.discovery_url)
    if cached and time.monotonic() - cached[0] < DISCOVERY_TTL_SECONDS:
        return cached[1]
    document = _http_get_json(provider.discovery_url)
    for key in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not isinstance(document.get(key), str):
            raise OAuthError("unavailable", f"discovery document lacks {key}")
    _discovery_cache[provider.discovery_url] = (time.monotonic(), document)
    return document


def _signing_key(jwks_uri: str, kid: str | None) -> dict:
    cached = _jwks_cache.get(jwks_uri)
    fresh = cached is not None and time.monotonic() - cached[0] < JWKS_TTL_SECONDS
    keys = cached[1] if fresh else None
    for _ in range(2):
        if keys is None:
            keys = _http_get_json(jwks_uri).get("keys") or []
            _jwks_cache[jwks_uri] = (time.monotonic(), keys)
        match = next((key for key in keys if key.get("kid") == kid), None)
        if match is not None:
            return match
        # Providers rotate keys: an unknown kid earns one refetch.
        keys = None
    raise OAuthError("invalid_token", f"no signing key {kid!r}")


def clear_caches() -> None:
    _discovery_cache.clear()
    _jwks_cache.clear()


# ── Flow ────────────────────────────────────────────────────────────────────

def authorization_url(provider: Provider, *, state: str, nonce: str, code_challenge: str) -> str:
    params = {
        "client_id": provider.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(provider.name),
        "scope": provider.scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # A shared office computer is often signed in to someone else's
        # account: always let the person choose.
        "prompt": "select_account",
    }
    return f"{_discovery(provider)['authorization_endpoint']}?{urlencode(params)}"


def complete_sign_in(provider: Provider, *, code: str, code_verifier: str, nonce: str) -> OAuthProfile:
    document = _discovery(provider)
    status, tokens = _http_post_form(document["token_endpoint"], {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(provider.name),
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
        "code_verifier": code_verifier,
    })
    if status != 200 or not isinstance(tokens.get("id_token"), str):
        logger.warning("oauth_code_exchange_failed provider=%s status=%s error=%s",
                       provider.name, status, tokens.get("error"))
        raise OAuthError("exchange_failed")
    return verify_id_token(provider, tokens["id_token"], nonce=nonce, access_token=tokens.get("access_token"))


def verify_id_token(provider: Provider, id_token: str, *, nonce: str, access_token: str | None = None) -> OAuthProfile:
    document = _discovery(provider)
    try:
        header = jwt.get_unverified_header(id_token)
        unverified = jwt.get_unverified_claims(id_token)
    except Exception:
        raise OAuthError("invalid_token", "malformed ID token") from None
    if header.get("alg") != "RS256":
        raise OAuthError("invalid_token", f"unexpected algorithm {header.get('alg')!r}")

    issuers = [document["issuer"]]
    if "{tenantid}" in document["issuer"]:
        # Microsoft's multi-tenant endpoints publish an issuer template; the
        # token's own tenant fills it in.
        tenant = unverified.get("tid")
        if not isinstance(tenant, str) or not tenant:
            raise OAuthError("invalid_token", "missing tenant")
        issuers = [document["issuer"].replace("{tenantid}", tenant)]
    if provider.name == "google":
        issuers.append("accounts.google.com")

    key = _signing_key(document["jwks_uri"], header.get("kid"))
    try:
        claims = jwt.decode(
            id_token, key, algorithms=["RS256"], audience=provider.client_id,
            issuer=issuers, access_token=access_token,
            options={"leeway": CLOCK_SKEW_SECONDS},
        )
    except Exception as exc:
        logger.warning("oauth_id_token_rejected provider=%s error=%s", provider.name, exc)
        raise OAuthError("invalid_token") from None

    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OAuthError("invalid_token", "nonce mismatch")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise OAuthError("invalid_token", "missing subject")

    email = claims.get("email")
    email = email.strip().lower() if isinstance(email, str) and email.strip() else None
    return OAuthProfile(
        provider=provider.name,
        subject=subject,
        email=email,
        email_verified=_email_verified(provider.name, claims),
        name=claims.get("name") if isinstance(claims.get("name"), str) else None,
    )


def _truthy(value) -> bool:
    return value is True or value == 1 or (isinstance(value, str) and value.lower() in ("true", "1"))


def _email_verified(provider: str, claims: dict) -> bool:
    if provider == "google":
        return _truthy(claims.get("email_verified"))
    # Microsoft does not verify the `email` of a work account: any tenant
    # admin can set any address. `xms_edov` (an optional claim to enable in
    # the app registration) says the address's domain is verified by the
    # tenant that issued the token.
    return _truthy(claims.get("xms_edov")) or claims.get("tid") == MICROSOFT_CONSUMER_TENANT
