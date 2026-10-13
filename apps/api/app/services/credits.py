"""Prepaid credits: what an analysis, a question or a report costs the user.

The unit is the analysed page, because the model bill grows with the data
room, not with the number of runs: a 300-page ledger costs what a hundred
three-page letters cost. A document without a page count (DOCX, TXT) is
counted at ``PAGE_CHARS`` characters per page.

A charge is a conditional ``UPDATE ... WHERE credit_balance >= cost``, so
two concurrent requests cannot both spend the last credits, plus a ledger
row. Nothing here commits: the caller commits the charge together with
whatever it pays for, and refunds when that does not happen.
"""
import math

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.credit_transaction import CreditTransaction
from app.models.document import Document, DocumentStatus
from app.models.user import User

PAGE_CHARS = 3000


def is_unlimited(user: User) -> bool:
    unlimited = {email.strip().lower() for email in settings.CREDITS_UNLIMITED_EMAILS}
    return (user.email or "").lower() in unlimited


def is_admin(user: User) -> bool:
    """An address in ADMIN_EMAILS that a provider vouched for on this account."""
    admins = {email.strip().lower() for email in settings.ADMIN_EMAILS}
    email = (user.email or "").lower()
    return email in admins and any(
        (identity.email or "").lower() == email for identity in user.oauth_identities
    )


def is_charged(user: User) -> bool:
    return settings.CREDITS_ENABLED and not is_unlimited(user)


def analysis_cost(db: Session, deal_id: int) -> int:
    """Pages of the deal's processed documents (at least 1 per document)."""
    rows = db.query(
        Document.page_count, func.length(func.coalesce(Document.raw_text, "")),
    ).filter(Document.deal_id == deal_id, Document.status == DocumentStatus.processed)
    return sum(pages or max(1, math.ceil((chars or 0) / PAGE_CHARS)) for pages, chars in rows)


def _record(db: Session, user_id: int, delta: int, reason: str,
            deal_id: int | None, note: str | None) -> int:
    balance = db.query(User.credit_balance).filter(User.id == user_id).scalar()
    db.add(CreditTransaction(user_id=user_id, delta=delta, balance_after=balance,
                             reason=reason, deal_id=deal_id, note=note))
    db.flush()
    return balance


def grant(db: Session, user_id: int, amount: int, reason: str = "grant", *,
          deal_id: int | None = None, note: str | None = None) -> int:
    """Add (or, with a negative amount, remove) credits; returns the new balance."""
    db.query(User).filter(User.id == user_id).update(
        {User.credit_balance: User.credit_balance + amount}, synchronize_session=False,
    )
    return _record(db, user_id, amount, reason, deal_id, note)


def grant_signup(db: Session, user: User) -> None:
    """Opening balance of a new account; call after the user row is flushed."""
    if settings.SIGNUP_CREDITS > 0:
        db.flush()
        grant(db, user.id, settings.SIGNUP_CREDITS, "signup")


def charge(db: Session, user: User, cost: int, reason: str, *,
           deal_id: int | None = None, note: str | None = None) -> int:
    """Spend ``cost`` credits or raise 402. Returns what was actually charged
    (0 when credits are off or the user is unlimited) — the amount to refund."""
    if cost <= 0 or not is_charged(user):
        return 0
    spent = db.query(User).filter(User.id == user.id, User.credit_balance >= cost).update(
        {User.credit_balance: User.credit_balance - cost}, synchronize_session=False,
    )
    if spent != 1:
        balance = db.query(User.credit_balance).filter(User.id == user.id).scalar() or 0
        raise HTTPException(status_code=402, detail={
            "code": "insufficient_credits",
            "message": (f"Crediti insufficienti: servono {cost} crediti, ne hai {balance}. "
                        "Contatta l’amministratore per una ricarica."),
            "required": cost,
            "balance": balance,
        })
    _record(db, user.id, -cost, reason, deal_id, note)
    return cost


def refund(db: Session, user_id: int, amount: int, *,
           deal_id: int | None = None, note: str | None = None) -> None:
    if amount > 0:
        grant(db, user_id, amount, "refund", deal_id=deal_id, note=note)
