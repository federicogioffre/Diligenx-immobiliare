import enum

from sqlalchemy import String, Float, Text, ForeignKey, Enum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class DealStatus(str, enum.Enum):
    draft = "draft"
    analyzing = "analyzing"
    reviewed = "reviewed"
    closed = "closed"


class Deal(TimestampMixin, Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)
    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus), default=DealStatus.draft
    )
    # Output language for LLM prose and report boilerplate: "it" | "en".
    # None = auto-detect from the majority language of processed documents.
    report_language: Mapped[str | None] = mapped_column(String(10))
    # Explicit legal entities in the introductory section; no inference from
    # deal titles, document frequency, or customer/supplier references.
    target_company_names: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    workspace = relationship("Workspace", back_populates="deals")
    documents = relationship("Document", back_populates="deal", cascade="all, delete-orphan")
    red_flags = relationship("RedFlag", back_populates="deal", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="deal", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="deal", cascade="all, delete-orphan")
    agent_findings = relationship("AgentFinding", back_populates="deal", cascade="all, delete-orphan")
    open_questions = relationship("OpenQuestion", back_populates="deal", cascade="all, delete-orphan")
    missing_documents = relationship("MissingDocument", back_populates="deal", cascade="all, delete-orphan")
    company_profiles = relationship("CompanyProfile", back_populates="deal", cascade="all, delete-orphan")
    property_profiles = relationship("PropertyProfile", back_populates="deal", cascade="all, delete-orphan")
