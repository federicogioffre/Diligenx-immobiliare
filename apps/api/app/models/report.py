import enum

from sqlalchemy import String, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class ReportType(str, enum.Enum):
    due_diligence = "due_diligence"
    risk_assessment = "risk_assessment"
    executive_summary = "executive_summary"


class ReportStatus(str, enum.Enum):
    generating = "generating"
    completed = "completed"
    failed = "failed"


class Report(TimestampMixin, Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    report_type: Mapped[ReportType] = mapped_column(Enum(ReportType))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str | None] = mapped_column(Text)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus), default=ReportStatus.generating
    )

    deal = relationship("Deal", back_populates="reports")
