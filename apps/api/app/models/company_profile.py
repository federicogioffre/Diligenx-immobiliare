from sqlalchemy import String, Text, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class CompanyProfile(TimestampMixin, Base):
    """The "Corporate Introductory Information" record for a single target
    company in a deal — populated by the corporate_intro_agent from
    visure / atti costitutivi / statuti / patti parasociali.

    Mirrors the columns of the Corporate Introductory Information table in
    professional red-flag DD reports. Every field is nullable: the agent
    fills what it can ground on, the deal team completes the rest.
    """

    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)

    # Identity
    company_name: Mapped[str] = mapped_column(String(500))
    legal_form: Mapped[str | None] = mapped_column(String(200))
    incorporation_date: Mapped[str | None] = mapped_column(String(100))
    registered_office: Mapped[str | None] = mapped_column(String(500))

    # Capital & ownership
    corporate_capital: Mapped[str | None] = mapped_column(Text)
    shareholders: Mapped[str | None] = mapped_column(Text)
    pledge: Mapped[str | None] = mapped_column(Text)

    # Governance
    managing_body: Mapped[str | None] = mapped_column(Text)
    auditors: Mapped[str | None] = mapped_column(Text)
    auditing_company: Mapped[str | None] = mapped_column(Text)

    # Business and term
    business: Mapped[str | None] = mapped_column(Text)
    fiscal_year: Mapped[str | None] = mapped_column(String(200))
    duration: Mapped[str | None] = mapped_column(String(200))

    # Provenance
    confidence: Mapped[float | None] = mapped_column(Float)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )

    deal = relationship("Deal", back_populates="company_profiles")
    source_document = relationship("Document")
