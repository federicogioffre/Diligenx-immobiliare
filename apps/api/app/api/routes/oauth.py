"""Sign-in with Microsoft and Google.

* ``GET /auth/oauth/providers``          — which providers this deployment offers
* ``GET /auth/oauth/{provider}/start``   — sends the browser to the provider
* ``GET /auth/oauth/{provider}/callback`` — the provider sends it back here

Both browser legs are top-level navigations through the frontend's /api
proxy, so the cookies set here land on the frontend's origin exactly like
the password login's. The callback ends on ``/login/complete``, which picks
the workspace as the password login does; a failure ends on
``/login?oauth_error=<code>``.

An identity is matched by the provider's subject. A first sign-in links to
the account with the same email, or creates one, only when the provider
vouches for the address: otherwise anyone able to set an arbitrary email on
an account they control (a Microsoft tenant admin) could open someone
else's Diligenx account.
"""
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.auth import _set_session_cookies
from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import create_access_token, make_unusable_password
from app.db.session import get_db
from app.models.oauth_identity import OAuthIdentity
from app.models.user import User
from app.services import oauth
from app.services.oauth import OAuthError, OAuthProfile

logger = logging.getLogger(__name__)

router = APIRouter()

PENDING_COOKIE_NAME = "dm_oauth"
PENDING_TTL_SECONDS = 600
DEFAULT_NEXT = "/dashboard"


def _safe_next(value: str | None) -> str:
    """Only a path on this site: never `//host`, a scheme or a backslash."""
    if (not value or not value.startswith("/") or value.startswith("//")
            or "\\" in value or any(ord(ch) < 32 for ch in value)):
        return DEFAULT_NEXT
    return value


def _provider_or_404(name: str) -> oauth.Provider:
    provider = oauth.configured_providers().get(name)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not available")
    return provider


def _clear_pending(response: RedirectResponse) -> None:
    response.delete_cookie(PENDING_COOKIE_NAME, path="/", httponly=True,
                           secure=settings.AUTH_COOKIE_SECURE, samesite="lax")


def _fail(code: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?oauth_error={quote(code)}", status_code=303)
    _clear_pending(response)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/providers")
def list_providers():
    return {"providers": sorted(oauth.configured_providers())}


@router.get("/{provider}/start")
@limiter.limit("20/minute")
def start(request: Request, provider: str, next_path: str | None = Query(None, alias="next")):
    selected = _provider_or_404(provider)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = oauth.new_pkce_pair()
    try:
        target = oauth.authorization_url(selected, state=state, nonce=nonce, code_challenge=challenge)
    except OAuthError as exc:
        return _fail(exc.code)

    # The secrets this browser must bring back travel in a signed, short-lived
    # HttpOnly cookie: nothing to store server-side, and a callback opened in
    # another browser (a forwarded link, an attacker's code) has no match.
    pending = jwt.encode({
        "scope": "oauth", "provider": provider, "state": state, "nonce": nonce,
        "verifier": verifier, "next": _safe_next(next_path),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=PENDING_TTL_SECONDS),
    }, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    response = RedirectResponse(target, status_code=303)
    # SameSite=Lax still travels on the provider's top-level redirect back.
    response.set_cookie(PENDING_COOKIE_NAME, pending, max_age=PENDING_TTL_SECONDS, path="/",
                        httponly=True, secure=settings.AUTH_COOKIE_SECURE, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/{provider}/callback")
@limiter.limit("20/minute")
def callback(
    request: Request,
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    dm_oauth: str | None = Cookie(None, alias=PENDING_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    selected = oauth.configured_providers().get(provider)
    if selected is None:
        return _fail("unavailable")
    try:
        pending = jwt.decode(dm_oauth or "", settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return _fail("invalid_state")
    if (pending.get("scope") != "oauth" or pending.get("provider") != provider
            or not state or not hmac.compare_digest(str(pending.get("state", "")), state)):
        return _fail("invalid_state")
    if error:
        return _fail("cancelled" if error == "access_denied" else "provider_error")
    if not code:
        return _fail("provider_error")

    try:
        profile = oauth.complete_sign_in(selected, code=code, code_verifier=pending["verifier"],
                                         nonce=pending["nonce"])
        user, created = _resolve_user(db, profile)
    except OAuthError as exc:
        return _fail(exc.code)

    token = create_access_token(user.email, user_id=user.id, hashed_password=user.hashed_password)
    response = RedirectResponse(
        f"/login/complete?next={quote(_safe_next(pending.get('next')), safe='')}", status_code=303,
    )
    _clear_pending(response)
    _set_session_cookies(response, token)
    logger.info("oauth_sign_in provider=%s user=%d new_account=%s", provider, user.id, created)
    return response


def _resolve_user(db: Session, profile: OAuthProfile) -> tuple[User, bool]:
    identity = (
        db.query(OAuthIdentity)
        .filter(OAuthIdentity.provider == profile.provider, OAuthIdentity.subject == profile.subject)
        .first()
    )
    if identity is not None:
        if not identity.user.is_active:
            raise OAuthError("account_disabled")
        return identity.user, False

    if not profile.email:
        raise OAuthError("email_missing")
    if not profile.email_verified:
        raise OAuthError("email_not_verified")

    user = db.query(User).filter(func.lower(User.email) == profile.email).first()
    created = user is None
    if user is None:
        user = User(email=profile.email, full_name=profile.name, hashed_password=make_unusable_password())
        db.add(user)
    elif not user.is_active:
        raise OAuthError("account_disabled")
    db.add(OAuthIdentity(user=user, provider=profile.provider, subject=profile.subject, email=profile.email))
    try:
        if created:
            from app.services.credits import grant_signup
            grant_signup(db, user)
        db.commit()
    except IntegrityError:
        # Two first sign-ins of the same person raced; the other one won.
        db.rollback()
        raise OAuthError("retry") from None
    db.refresh(user)
    return user, created
