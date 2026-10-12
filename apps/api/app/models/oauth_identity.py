from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class OAuthIdentity(TimestampMixin, Base):
    """An external sign-in (Microsoft, Google) bound to a local account.

    Keyed by the provider's stable subject, never by email: an address can
    be reassigned inside a tenant, a subject cannot. ``email`` records what
    the provider asserted when the identity was linked.
    """

    __tablename__ = "oauth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_oauth_identity_provider_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))

    user = relationship("User", back_populates="oauth_identities")
