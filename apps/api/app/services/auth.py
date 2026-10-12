from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.security import decode_access_claims, session_matches_user
from app.db.session import get_db
from app.db.tenant_context import set_tenant_context
from app.models.user import User

# auto_error=False: a missing Authorization header falls through to the
# session cookie instead of short-circuiting with a 403.
bearer = HTTPBearer(auto_error=False)


def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    dm_token: str | None = Cookie(None, alias="dm_token"),
    db: Session = Depends(get_db),
) -> tuple[User, dict]:
    """Resolve the authenticated user and the claims of the session token.

    The Bearer header wins when both are present (API clients, tests); the
    browser client relies on the HttpOnly ``dm_token`` cookie set at login.
    """
    token = credentials.credentials if credentials else dm_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    claims = decode_access_claims(token)
    user = db.query(User).filter(User.id == claims["uid"], User.is_active == True).first()
    if not user or not session_matches_user(claims, user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # Bind the RLS tenant context on this request's connection: from here
    # on, Postgres row-level policies restrict every query to this user's
    # rows — even if a handler forgets an ownership filter. No-op on SQLite.
    set_tenant_context(db, user.id)
    return user, claims


def get_current_user(session: tuple[User, dict] = Depends(get_current_session)) -> User:
    return session[0]
