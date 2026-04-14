import enum

from sqlalchemy import String, Float, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class Severity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RedFlag(TimestampMixin, Base):
    __tablename__ = "red_flags"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[Severity] = mapped_column(Enum(Severity))
    category: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )

    deal = relationship("Deal", back_populates="red_flags")
    source_document = relationship("Document", overlaps="red_flags")
