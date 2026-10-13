"""Credit administration: list accounts and grant or remove credits.

Open only to ``ADMIN_EMAILS`` accounts whose address a provider vouched for
(``services.credits.is_admin``); everyone else gets 403. ``users`` is not
under row-level security, so an administrator reads every account.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.services import credits
from app.services.auth import get_current_user

router = APIRouter()


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not credits.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Riservato agli amministratori")
    return current_user


def _account(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "credit_balance": user.credit_balance,
        "credits_unlimited": credits.is_unlimited(user),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/users")
def list_accounts(
    q: str = "", db: Session = Depends(get_db), admin: User = Depends(require_admin),
):
    query = db.query(User)
    if q.strip():
        pattern = f"%{q.strip().lower()}%"
        query = query.filter(or_(func.lower(User.email).like(pattern),
                                 func.lower(func.coalesce(User.full_name, "")).like(pattern)))
    return [_account(u) for u in query.order_by(User.email).limit(200)]


class CreditGrant(BaseModel):
    email: str
    # Negative removes credits; zero is refused.
    amount: int = Field(ge=-1_000_000, le=1_000_000)
    note: str | None = Field(default=None, max_length=200)


@router.post("/credits")
@limiter.limit("30/minute")
def grant_credits(
    request: Request, payload: CreditGrant,
    db: Session = Depends(get_db), admin: User = Depends(require_admin),
):
    if payload.amount == 0:
        raise HTTPException(status_code=422, detail="Indica un numero di crediti diverso da zero.")
    user = (db.query(User).filter(func.lower(User.email) == payload.email.strip().lower())
            .with_for_update().first())
    if user is None:
        raise HTTPException(status_code=404, detail="Nessun account con questa email.")
    if user.credit_balance + payload.amount < 0:
        raise HTTPException(status_code=400, detail=(
            f"{user.email} ha {user.credit_balance} crediti: non puoi toglierne {-payload.amount}."))
    note = f"{payload.note.strip()} · {admin.email}" if payload.note and payload.note.strip() else admin.email
    credits.grant(db, user.id, payload.amount, "grant", note=note[:255])
    db.commit()
    db.refresh(user)
    return _account(user)
