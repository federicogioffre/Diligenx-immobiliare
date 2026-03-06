import json
from typing import Any

from sqlalchemy import String, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator, Text as SAText

from app.db.session import Base
from app.models.base import TimestampMixin

# Must match the embedding model's output dimension.
# OpenAI text-embedding-3-small = 1536
EMBEDDING_DIM = 1536


class VectorType(TypeDecorator):
    """Uses pgvector VECTOR on PostgreSQL, JSON text on SQLite (tests)."""

    impl = SAText
    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(SAText())

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if dialect.name != "postgresql":
            return json.dumps(value)
        return value

    def process_result_value(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if dialect.name != "postgresql" and isinstance(value, str):
            return json.loads(value)
        return value


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding_id: Mapped[str | None] = mapped_column(String(255))
    embedding: Mapped[Any | None] = mapped_column(VectorType(EMBEDDING_DIM), nullable=True)

    document = relationship("Document", back_populates="chunks")
