import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, status
from jose import jwt, JWTError

from app.core.config import settings


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password exceeds bcrypt's 72-byte limit")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def validate_password(password: str) -> None:
    if len(password) < 8 or len(password.encode("utf-8")) > 72:
        raise ValueError("La password deve avere almeno 8 caratteri e non superare 72 byte UTF-8")


def verify_password(plain: str, hashed: str) -> bool:
    if len(plain.encode("utf-8")) > 72:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(subject: str, *, user_id: int, hashed_password: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "typ": "access", "uid": user_id,
               "fp": _password_fingerprint(hashed_password)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_claims(token: str) -> dict:
    """Decode the signed, account-bound claims of a session access token.

    Rejects scoped tokens (e.g. SSE stream tickets): a short-lived ticket
    leaked through a URL must never be usable as a full session credential.
    Unbound legacy sessions must sign in again. Accepting them would retain
    access after an account is recreated or its password is reset.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        sub: str = payload.get("sub")
        if sub is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        if (payload.get("scope") is not None or payload.get("typ") != "access"
                or type(payload.get("uid")) is not int
                or not isinstance(payload.get("fp"), str)):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def decode_token(token: str) -> str:
    return decode_access_claims(token)["sub"]


def session_matches_user(claims: dict, user) -> bool:
    return (claims["uid"] == user.id and claims["sub"] == user.email
            and hmac.compare_digest(claims["fp"], _password_fingerprint(user.hashed_password)))


# ── SSE stream tickets ──────────────────────────────────────────────────────
#
# The browser EventSource API cannot send headers, and the SSE endpoint is
# reached directly (not via the Next.js proxy), so the credential must travel
# in the URL. A dedicated short-lived, deal-scoped ticket keeps that exposure
# harmless: it expires in seconds and grants nothing beyond the one stream.

STREAM_TICKET_TTL_SECONDS = 60


def create_stream_ticket(subject: str, deal_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(seconds=STREAM_TICKET_TTL_SECONDS)
    payload = {"sub": subject, "exp": expire, "scope": "stream", "deal_id": deal_id}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_stream_ticket(ticket: str, deal_id: int) -> str:
    """Validate a stream ticket for *deal_id* and return its subject (email).

    Rejects plain access tokens (wrong/missing scope) and tickets minted for
    a different deal.
    """
    try:
        payload = jwt.decode(ticket, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ticket")

    sub = payload.get("sub")
    if (
        sub is None
        or payload.get("scope") != "stream"
        or payload.get("deal_id") != deal_id
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ticket")
    return sub


# ── Password reset tokens ───────────────────────────────────────────────────
#
# Stateless single-use: the token embeds a fingerprint of the CURRENT
# password hash. As soon as the password changes, every token issued before
# the change stops validating — no server-side token table needed. TTL keeps
# a leaked link short-lived.

PASSWORD_RESET_TTL_MINUTES = 30


def _password_fingerprint(hashed_password: str) -> str:
    return hashlib.sha256(hashed_password.encode()).hexdigest()[:16]


def create_password_reset_token(subject: str, hashed_password: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES)
    payload = {
        "sub": subject,
        "exp": expire,
        "scope": "pwreset",
        "fp": _password_fingerprint(hashed_password),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_password_reset_token(token: str, current_hashed_password: str) -> str:
    """Validate a password-reset token and return its subject (email).

    Rejects: plain access tokens / stream tickets (wrong scope), expired
    tokens (JWTError), and tokens minted before the last password change
    (fingerprint mismatch → already used or superseded).
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Link non valido o scaduto")

    sub = payload.get("sub")
    if (
        sub is None
        or payload.get("scope") != "pwreset"
        or payload.get("fp") != _password_fingerprint(current_hashed_password)
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Link non valido o scaduto")
    return sub
