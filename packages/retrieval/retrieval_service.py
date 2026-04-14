"""Semantic search over DocumentChunk embeddings.

Embeds a query string, then ranks all chunks belonging to a deal by
cosine similarity.  Works on both PostgreSQL (pgvector) and SQLite
(FakeEmbeddingProvider) — the similarity is computed in Python so
it is dialect-agnostic.
"""
import logging
import math
from dataclasses import dataclass

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
    """Compute cosine similarity between two equal-length vectors."""
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

    Steps
    -----
    1. Embed the query text using the configured ``EmbeddingProvider``.
    2. Load all ``DocumentChunk`` rows (with embeddings) for processed
       documents in *deal_id*.
    3. Compute cosine similarity in Python.
    4. Return the top-k results sorted by descending similarity.

    Returns an empty list when there are no chunks with embeddings.
    """
    from app.models.document import Document, DocumentStatus
    from app.models.document_chunk import DocumentChunk

    emb_provider = provider or get_embedding_provider()

    # 1. Embed query
    query_vec = emb_provider.embed_texts([query])[0]

    # 2. Load all chunks for this deal's processed documents
    chunks = (
        db.query(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(
            Document.deal_id == deal_id,
            Document.status == DocumentStatus.processed,
            DocumentChunk.embedding.isnot(None),
        )
        .all()
    )

    if not chunks:
        logger.info("No embedded chunks found for deal %d.", deal_id)
        return []

    # 3. Rank by cosine similarity
    scored: list[tuple[float, DocumentChunk]] = []
    for chunk in chunks:
        vec = chunk.embedding
        if vec is None:
            continue
        # SQLite returns JSON-decoded list; pgvector returns list-like
        if isinstance(vec, str):
            import json
            vec = json.loads(vec)
        sim = _cosine_similarity(query_vec, vec)
        scored.append((sim, chunk))

    scored.sort(key=lambda t: t[0], reverse=True)

    # 4. Return top-k
    results = [
        ChunkMatch(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            content=chunk.content,
            page_number=chunk.page_number,
            score=round(sim, 4),
        )
        for sim, chunk in scored[:top_k]
    ]

    logger.info(
        "Retrieved %d chunks for deal %d (query=%r, top score=%.4f).",
        len(results),
        deal_id,
        query[:60],
        results[0].score if results else 0.0,
    )
    return results
