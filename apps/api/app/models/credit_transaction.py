from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class CreditTransaction(TimestampMixin, Base):
    """One movement of a user's prepaid credits: a grant, a charge or a refund.

    ``users.credit_balance`` is the balance that admission checks; this ledger
    says how it got there. ``deal_id`` is a plain integer, not a foreign key:
    the charge for an analysis outlives the deal it paid for.
    """

    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    # signup | grant | analysis | ask | report | refund
    reason: Mapped[str] = mapped_column(String(32))
    deal_id: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(255))

    user = relationship("User", back_populates="credit_transactions")
