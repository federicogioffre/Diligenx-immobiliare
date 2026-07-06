from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, status
from jose import jwt, JWTError

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "typ": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> str:
    """Decode a session access token and return its subject (email).

    Rejects scoped tokens (e.g. SSE stream tickets): a short-lived ticket
    leaked through a URL must never be usable as a full session credential.
    Tokens without a ``typ`` claim are accepted for backward compatibility
    with sessions issued before token typing was introduced.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        sub: str = payload.get("sub")
        if sub is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        if payload.get("scope") is not None or payload.get("typ", "access") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return sub
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


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
