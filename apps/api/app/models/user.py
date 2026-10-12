from sqlalchemy import String, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # An account created through Microsoft or Google sign-in holds an
    # unusable marker here (see core.security.make_unusable_password) until
    # its owner sets a password through the reset flow.
    hashed_password: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Prepaid credits (see app.services.credits); 1 credit = 1 analysed page.
    credit_balance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    workspaces = relationship("Workspace", back_populates="owner")
    oauth_identities = relationship(
        "OAuthIdentity", back_populates="user", cascade="all, delete-orphan",
    )
    credit_transactions = relationship(
        "CreditTransaction", back_populates="user", cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def has_password(self) -> bool:
        from app.core.security import has_usable_password
        return has_usable_password(self.hashed_password)

    @property
    def auth_providers(self) -> list[str]:
        return sorted({identity.provider for identity in self.oauth_identities})
