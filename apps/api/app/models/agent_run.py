import enum
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class AgentRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    agent_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus), default=AgentRunStatus.pending
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    input_hash: Mapped[str | None] = mapped_column(String(64))

    deal = relationship("Deal", back_populates="agent_runs")
    document = relationship("Document", overlaps="agent_runs")

    @property
    def duration_seconds(self) -> float | None:
        """Elapsed wall-clock time in seconds.

        Returns ``None`` when either timestamp is absent (e.g. a run that is
        still *running* or was never started).

        Normalises naive datetimes to UTC before subtracting so the
        computation is safe on both PostgreSQL (timezone-aware) and
        SQLite (naive strings).
        """
        if self.started_at is None or self.completed_at is None:
            return None
        start = (
            self.started_at
            if self.started_at.tzinfo is not None
            else self.started_at.replace(tzinfo=timezone.utc)
        )
        end = (
            self.completed_at
            if self.completed_at.tzinfo is not None
            else self.completed_at.replace(tzinfo=timezone.utc)
        )
        return (end - start).total_seconds()
