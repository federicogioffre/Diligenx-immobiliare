from sqlalchemy import String, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin
from app.models.open_question import Priority


class MissingDocument(TimestampMixin, Base):
    __tablename__ = "missing_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    document_category: Mapped[str] = mapped_column(String(200))
    expected_item: Mapped[str] = mapped_column(String(500))
    reason: Mapped[str] = mapped_column(Text)
    priority: Mapped[Priority] = mapped_column(Enum(Priority, name="priority", create_constraint=False))

    deal = relationship("Deal", back_populates="missing_documents")
