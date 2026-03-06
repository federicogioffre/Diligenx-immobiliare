from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    owner = relationship("User", back_populates="workspaces")
    deals = relationship("Deal", back_populates="workspace", cascade="all, delete-orphan")
