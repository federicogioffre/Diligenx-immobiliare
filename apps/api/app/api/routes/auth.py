from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.core.security import hash_password, verify_password, create_access_token
from app.schemas.user import UserCreate, UserRead, Token

router = APIRouter()

# Session cookie (HttpOnly — invisible to JS) and its non-HttpOnly companion
# flag, which client code reads purely as a "probably logged in" UX signal.
AUTH_COOKIE_NAME = "dm_token"
AUTHED_FLAG_COOKIE_NAME = "dm_authed"

_COOKIE_KWARGS = dict(samesite="lax", path="/")


def _set_session_cookies(response: Response, token: str) -> None:
    max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        **_COOKIE_KWARGS,
    )
    response.set_cookie(
        AUTHED_FLAG_COOKIE_NAME,
        "1",
        max_age=max_age,
        httponly=False,
        secure=settings.AUTH_COOKIE_SECURE,
        **_COOKIE_KWARGS,
    )
    response.headers["Cache-Control"] = "no-store"


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(
        AUTH_COOKIE_NAME,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        **_COOKIE_KWARGS,
    )
    response.delete_cookie(
        AUTHED_FLAG_COOKIE_NAME,
        httponly=False,
        secure=settings.AUTH_COOKIE_SECURE,
        **_COOKIE_KWARGS,
    )
    response.headers["Cache-Control"] = "no-store"


@router.post("/register", response_model=UserRead, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Authenticate and start a session.

    The JWT is set as an HttpOnly cookie (the browser client relies on it and
    never touches the token from JS) and is also returned in the body for
    non-browser API clients using ``Authorization: Bearer``.
    """
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.email)
    _set_session_cookies(response, token)
    return {"access_token": token}


@router.post("/logout", status_code=204)
def logout(response: Response):
    """End the cookie session.

    Deliberately unauthenticated: a browser with an invalid/rejected session
    (deactivated user, rotated SECRET_KEY) must still be able to clear its
    HttpOnly cookie — JS cannot delete it.
    """
    _clear_session_cookies(response)
