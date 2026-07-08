import enum

from sqlalchemy import String, Float, Text, Integer, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class Severity(str, enum.Enum):
    """Three-level scale used by practitioners in red-flag DD reports.

    Deliberately has no "critical" value: real reports express criticality
    by concentration of HIGH findings, not by inflating the scale. (The
    deal-level risk_level computed by scoring_service keeps its own 4-step
    scale — that is a different axis.)
    """

    low = "low"
    medium = "medium"
    high = "high"


class DueDiligenceArea(str, enum.Enum):
    """The standard legal-DD areas a red-flag report is organized by.

    Mirrors the section taxonomy used in Italian M&A red-flag reports
    (Corporate Matters, Indebtedness, Real Estate, ...). A RedFlag's
    ``area`` places it in the right section of the generated report;
    ``category`` remains free text for finer-grained labelling.
    """

    corporate = "corporate"                    # Corporate Matters
    indebtedness = "indebtedness"              # Loans, bonds, guarantees, pledges
    real_estate = "real_estate"                # Owned / leased property
    employees = "employees"                    # Labour / employment
    suppliers_customers = "suppliers_customers"  # Commercial agreements
    insurance = "insurance"
    litigation = "litigation"
    ip_it = "ip_it"                            # IP / IT
    data_protection = "data_protection"        # GDPR / privacy
    other = "other"


class RedFlag(TimestampMixin, Base):
    __tablename__ = "red_flags"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    # The Issue / Risk / Recommendation triple mirrors the column structure
    # of professional red-flag DD reports:
    #   issue          → what was found (factual)
    #   risk           → what could happen (impact)
    #   recommendation → what to do about it (CP, R&W, indemnity, ...)
    issue: Mapped[str] = mapped_column(Text)
    risk: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[Severity] = mapped_column(Enum(Severity))
    area: Mapped[DueDiligenceArea | None] = mapped_column(
        Enum(DueDiligenceArea, name="dd_area"), index=True
    )
    category: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    # Page within source_document_id where the flagged item appears. NULL when
    # the aggregator could not attribute (or validate) a specific page.
    source_page: Mapped[int | None] = mapped_column(Integer)

    deal = relationship("Deal", back_populates="red_flags")
    source_document = relationship("Document", overlaps="red_flags")
