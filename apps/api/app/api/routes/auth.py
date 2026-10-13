from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    decode_password_reset_token,
    hash_password,
    verify_password,
)
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
    if db.query(User).filter(func.lower(User.email) == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    from app.services.credits import grant_signup
    grant_signup(db, user)
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
    user = db.query(User).filter(func.lower(User.email) == form.username.strip().lower()).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.email, user_id=user.id, hashed_password=user.hashed_password)
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


# ── Password reset ──────────────────────────────────────────────────────────

from pydantic import BaseModel, EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password", status_code=202)
@limiter.limit("3/minute")
def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    """Start the password-reset flow.

    ALWAYS returns 202, whether or not the email exists — the response
    must not reveal which addresses have accounts (user enumeration).
    When the account exists, a single-use reset link (30-minute TTL,
    invalidated by any password change) is emailed; with SMTP not yet
    configured, the mailer logs the link instead so the flow remains
    testable.
    """
    from app.services.mailer import send_email

    user = db.query(User).filter(
        func.lower(User.email) == payload.email.lower(), User.is_active == True
    ).first()
    if user:
        token = create_password_reset_token(user.email, user.hashed_password)
        link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        send_email(
            to=user.email,
            subject="Diligenx — reimposta la tua password",
            body=(
                "Ciao,\n\n"
                "abbiamo ricevuto una richiesta di reimpostazione della password "
                "per il tuo account Diligenx.\n\n"
                f"Apri questo link per scegliere una nuova password (valido 30 minuti):\n{link}\n\n"
                "Se non hai richiesto tu la reimpostazione, ignora questa email: "
                "la tua password resta invariata.\n\n"
                "— Diligenx"
            ),
        )
    return {"detail": "Se l'indirizzo è registrato, riceverai un'email con le istruzioni."}


@router.post("/reset-password", status_code=204)
@limiter.limit("5/minute")
def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """Complete the password-reset flow with a token from the email link.

    The token embeds a fingerprint of the password hash it was issued
    against, so it is single-use: the first successful reset (or any
    password change) invalidates every outstanding token.
    """
    from app.core.security import validate_password
    try:
        validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    # Decode WITHOUT the fingerprint first to locate the user, then
    # validate properly against that user's current hash.
    from jose import jwt as _jwt, JWTError as _JWTError
    try:
        claims = _jwt.decode(
            payload.token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except _JWTError:
        raise HTTPException(status_code=400, detail="Link non valido o scaduto")

    user = db.query(User).filter(
        User.email == claims.get("sub"), User.is_active == True
    ).with_for_update().populate_existing().first()
    if not user:
        raise HTTPException(status_code=400, detail="Link non valido o scaduto")

    # Full validation: scope + fingerprint against the CURRENT hash.
    decode_password_reset_token(payload.token, user.hashed_password)

    user.hashed_password = hash_password(payload.new_password)
    db.commit()
