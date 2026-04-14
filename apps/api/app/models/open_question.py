import enum

from sqlalchemy import String, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class QuestionStatus(str, enum.Enum):
    open = "open"
    resolved = "resolved"


class OpenQuestion(TimestampMixin, Base):
    __tablename__ = "open_questions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    agent_name: Mapped[str] = mapped_column(String(200))
    question: Mapped[str] = mapped_column(Text)
    priority: Mapped[Priority] = mapped_column(Enum(Priority))
    status: Mapped[QuestionStatus] = mapped_column(
        Enum(QuestionStatus), default=QuestionStatus.open
    )

    deal = relationship("Deal", back_populates="open_questions")
    document = relationship("Document")
