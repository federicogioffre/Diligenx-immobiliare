import enum

from sqlalchemy import String, Float, Text, Integer, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship


from app.db.session import Base
from app.models.base import TimestampMixin


class ClauseType(str, enum.Enum):
    termination = "termination"
    liability = "liability"
    indemnification = "indemnification"
    confidentiality = "confidentiality"
    non_compete = "non_compete"
    payment_terms = "payment_terms"
    warranty = "warranty"
    intellectual_property = "intellectual_property"
    governing_law = "governing_law"
    change_of_control = "change_of_control"
    other = "other"


class ClauseFinding(TimestampMixin, Base):
    __tablename__ = "clause_findings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    clause_type: Mapped[ClauseType] = mapped_column(Enum(ClauseType))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    relevance_score: Mapped[str | None] = mapped_column(String(20))   # "high" | "medium" | "low"
    relevance_reason: Mapped[str | None] = mapped_column(Text)

    document = relationship("Document", back_populates="clause_findings")
