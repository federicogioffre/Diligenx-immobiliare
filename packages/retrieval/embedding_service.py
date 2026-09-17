"""Embedding generation for document chunks.

Supports pluggable embedding providers via ``EmbeddingProvider``.
The default is OpenAI's ``text-embedding-3-small`` (1536 dims).
For tests or offline use, ``FakeEmbeddingProvider`` returns deterministic
vectors without network calls.
"""
import hashlib
import logging
import math
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class EmbeddingProvider(ABC):
    """Abstract interface for embedding providers."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of the output vectors."""
        ...

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------

class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Generate embeddings via the OpenAI API.

    Requires the ``openai`` package and ``OPENAI_API_KEY`` env var.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
        batch_size: int = 100,
    ):
        import openai
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model
        self._dimension = dimension
        self._batch_size = batch_size

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            response = self._client.embeddings.create(
                input=batch,
                model=self._model,
            )
            all_embeddings.extend(item.embedding for item in response.data)
        return all_embeddings


# ---------------------------------------------------------------------------
# Fake provider (deterministic, for tests)
# ---------------------------------------------------------------------------

class FakeEmbeddingProvider(EmbeddingProvider):
    """Returns deterministic, content-derived vectors. No network calls."""

    def __init__(self, dimension: int = 1536):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        """Derive a reproducible unit-length vector from text content.

        Uses a stable hash (SHA-256) rather than the builtin ``hash()``, which
        is salted per process (``PYTHONHASHSEED``). Embeddings are written in
        the ingestion process and queried in the API process; a per-process
        salt would put the two in incompatible vector spaces and make retrieval
        return random results with no error.
        """
        raw = []
        for i in range(self._dimension):
            digest = hashlib.sha256(f"{text}:{i}".encode("utf-8")).digest()
            h = int.from_bytes(digest[:4], "big") % 10000
            raw.append(h / 10000.0 - 0.5)
        # L2 normalise
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]


# ---------------------------------------------------------------------------
# Default provider singleton
# ---------------------------------------------------------------------------

_default_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured embedding provider.

    Tries OpenAI if ``OPENAI_API_KEY`` is set, otherwise falls back
    to FakeEmbeddingProvider.
    """
    global _default_provider
    if _default_provider is not None:
        return _default_provider

    import os
    from app.core.config import settings
    api_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        _default_provider = OpenAIEmbeddingProvider(api_key=api_key)
    else:
        if settings.BETA_MODE:
            raise RuntimeError("BETA_MODE cannot use fake embeddings")
        logger.warning(
            "OPENAI_API_KEY not set — using FakeEmbeddingProvider. "
            "Embeddings will be deterministic but not semantically meaningful."
        )
        _default_provider = FakeEmbeddingProvider()
    return _default_provider


def set_embedding_provider(provider: EmbeddingProvider | None) -> None:
    """Override the default provider (useful for tests)."""
    global _default_provider
    _default_provider = provider


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_embeddings_for_document(
    document_id: int,
    db: Session,
    provider: EmbeddingProvider | None = None,
) -> int:
    """Generate and store embeddings for all chunks of a document.

    Returns the number of chunks that received embeddings.

    This function is **idempotent**: calling it again overwrites
    existing embeddings for the same document.
    """
    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk

    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise ValueError(f"Document {document_id} not found")

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )

    if not chunks:
        logger.info("Document %d has no chunks — skipping embeddings.", document_id)
        return 0

    if provider is None:
        provider = get_embedding_provider()

    texts = [c.content for c in chunks]
    embeddings = provider.embed_texts(texts)

    # Guard against a provider returning a partial batch: zip() would silently
    # leave the trailing chunks with NULL embeddings while the document is still
    # marked processed, quietly shrinking retrieval coverage.
    if len(embeddings) != len(chunks):
        raise ValueError(
            f"Embedding count mismatch for document {document_id}: "
            f"{len(embeddings)} vectors for {len(chunks)} chunks"
        )

    for chunk, vec in zip(chunks, embeddings):
        chunk.embedding = vec

    db.commit()

    logger.info(
        "Generated %d embeddings for document %d (dim=%d).",
        len(embeddings), document_id, provider.dimension,
    )
    return len(embeddings)
