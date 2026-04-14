import enum

from sqlalchemy import String, Integer, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    processed = "processed"
    failed = "failed"


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(String(1000))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.pending
    )
    page_count: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(10))
    raw_text: Mapped[str | None] = mapped_column(Text)

    deal = relationship("Deal", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    clause_findings = relationship(
        "ClauseFinding", back_populates="document", cascade="all, delete-orphan"
    )
    # nullable back-refs — DB handles SET NULL via ondelete="SET NULL" on FK
    red_flags = relationship(
        "RedFlag", foreign_keys="RedFlag.source_document_id",
        passive_deletes=True, overlaps="source_document",
    )
    agent_runs = relationship(
        "AgentRun", foreign_keys="AgentRun.document_id",
        passive_deletes=True, overlaps="document",
    )
