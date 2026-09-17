"""Semantic search over DocumentChunk embeddings.

PostgreSQL ranks vectors in the database and returns only the requested
matches. SQLite retains a streaming Python fallback for development/tests.
"""
import heapq
import logging
import math
from dataclasses import dataclass

from sqlalchemy import Float, bindparam, select
from sqlalchemy.orm import Session

from packages.retrieval.embedding_service import (
    EmbeddingProvider,
    get_embedding_provider,
)

logger = logging.getLogger(__name__)


@dataclass
class ChunkMatch:
    """A single retrieval result."""

    chunk_id: int
    document_id: int
    content: str
    page_number: int | None
    score: float  # cosine similarity


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two equal-length vectors.

    Returns 0.0 on a dimension mismatch rather than silently comparing the
    common prefix (``zip`` truncation), which would yield a plausible-but-wrong
    score — e.g. after swapping embedding providers or dimensions.
    """
    if len(a) != len(b):
        logger.warning(
            "cosine similarity dimension mismatch: %d vs %d — treating as no match",
            len(a), len(b),
        )
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_similar_chunks(
    deal_id: int,
    query: str,
    db: Session,
    top_k: int = 5,
    provider: EmbeddingProvider | None = None,
) -> list[ChunkMatch]:
    """Return the *top_k* chunks most similar to *query* within a deal.

    Only processed documents in the requested deal participate. PostgreSQL
    requires the pgvector extension installed by the normal migrations; a
    database error is surfaced instead of downloading the entire corpus.
    ``top_k <= 0`` returns no matches without invoking the embedding provider.
    """
    from app.models.document import Document, DocumentStatus
    from app.models.document_chunk import DocumentChunk

    if top_k <= 0:
        return []

    emb_provider = provider or get_embedding_provider()
    query_vec = emb_provider.embed_texts([query])[0]
    if not query_vec or not all(math.isfinite(value) for value in query_vec):
        raise ValueError("Query embedding must contain finite values")
    if not any(query_vec):
        return []

    if db.get_bind().dialect.name == "postgresql":
        return _search_postgres(deal_id, query_vec, db, top_k)

    # Keep the portable fallback bounded in memory too: the heap retains
    # only top_k ORM rows and yield_per bounds each database fetch.
    chunks = (
        db.query(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(
            Document.deal_id == deal_id,
            Document.status == DocumentStatus.processed,
            DocumentChunk.embedding.isnot(None),
        )
        .yield_per(128)
    )

    def scored_chunks():
        for chunk in chunks:
            vec = chunk.embedding
            if isinstance(vec, str):
                import json
                vec = json.loads(vec)
            if vec is not None:
                sim = _cosine_similarity(query_vec, vec)
                if math.isfinite(sim):
                    yield sim, -chunk.id, chunk

    results = [
        ChunkMatch(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            content=chunk.content,
            page_number=chunk.page_number,
            score=round(sim, 4),
        )
        for sim, _, chunk in heapq.nlargest(top_k, scored_chunks())
    ]

    logger.info(
        "Retrieved %d chunks for deal %d (top score=%.4f).",
        len(results),
        deal_id,
        results[0].score if results else 0.0,
    )
    return results


def _postgres_search_statement(deal_id: int, query_vec: list[float], top_k: int):
    from pgvector.sqlalchemy import Vector
    from app.models.document import Document, DocumentStatus
    from app.models.document_chunk import DocumentChunk, EMBEDDING_DIM

    if len(query_vec) != EMBEDDING_DIM:
        raise ValueError(f"Query embedding dimension must be {EMBEDDING_DIM}")
    # VectorType is a portable TypeDecorator, so use an explicitly typed
    # operand and Float result instead of its underlying Text comparator.
    distance = DocumentChunk.embedding.op("<=>", return_type=Float)(
        bindparam("query_embedding", value=query_vec, type_=Vector(EMBEDDING_DIM))
    )
    return (
        select(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id,
            DocumentChunk.content,
            DocumentChunk.page_number,
            distance.label("distance"),
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(
            Document.deal_id == deal_id,
            Document.status == DocumentStatus.processed,
            DocumentChunk.embedding.isnot(None),
        )
        .order_by(distance.asc(), DocumentChunk.id.asc())
        .limit(top_k)
    )


def _search_postgres(
    deal_id: int, query_vec: list[float], db: Session, top_k: int
) -> list[ChunkMatch]:
    rows = db.execute(_postgres_search_statement(deal_id, query_vec, top_k))
    return [
        ChunkMatch(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            content=row.content,
            page_number=row.page_number,
            score=round(max(-1.0, min(1.0, 1.0 - row.distance)), 4),
        )
        for row in rows
        if row.distance is not None and math.isfinite(row.distance)
    ]
