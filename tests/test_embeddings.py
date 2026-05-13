"""Tests for the embedding service and its integration with the pipeline."""
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.retrieval.embedding_service import (
    EmbeddingProvider,
    FakeEmbeddingProvider,
    generate_embeddings_for_document,
    set_embedding_provider,
)

from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk, EMBEDDING_DIM
from packages.parsing.ingestion_pipeline import process_document


@pytest.fixture(autouse=True)
def _use_fake_embeddings():
    """Ensure all tests in this module use the FakeEmbeddingProvider."""
    provider = FakeEmbeddingProvider(dimension=EMBEDDING_DIM)
    set_embedding_provider(provider)
    yield
    set_embedding_provider(None)


def _make_txt(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.txt"
    p.write_text(content, encoding="utf-8")
    return p


def _insert_doc_with_chunks(db, test_deal, tmp_path, content: str) -> Document:
    """Create a document and run ingestion so chunks exist."""
    path = _make_txt(tmp_path, content)
    doc = Document(
        deal_id=test_deal.id,
        filename="test.txt",
        file_path=str(path),
        mime_type="text/plain",
        file_size=len(content),
        status=DocumentStatus.pending,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    process_document(doc.id, db)
    db.refresh(doc)
    return doc


# ---------------------------------------------------------------------------
# FakeEmbeddingProvider unit tests
# ---------------------------------------------------------------------------

class TestFakeEmbeddingProvider:
    def test_returns_correct_dimension(self):
        provider = FakeEmbeddingProvider(dimension=128)
        vecs = provider.embed_texts(["hello"])
        assert len(vecs) == 1
        assert len(vecs[0]) == 128

    def test_deterministic(self):
        provider = FakeEmbeddingProvider(dimension=64)
        v1 = provider.embed_texts(["same text"])
        v2 = provider.embed_texts(["same text"])
        assert v1 == v2

    def test_different_texts_differ(self):
        provider = FakeEmbeddingProvider(dimension=64)
        v1 = provider.embed_texts(["text A"])[0]
        v2 = provider.embed_texts(["text B"])[0]
        assert v1 != v2

    def test_batch(self):
        provider = FakeEmbeddingProvider(dimension=32)
        vecs = provider.embed_texts(["a", "b", "c"])
        assert len(vecs) == 3
        assert all(len(v) == 32 for v in vecs)

    def test_normalised(self):
        provider = FakeEmbeddingProvider(dimension=64)
        vec = provider.embed_texts(["test"])[0]
        norm = sum(x * x for x in vec) ** 0.5
        assert abs(norm - 1.0) < 1e-6

    def test_dimension_property(self):
        provider = FakeEmbeddingProvider(dimension=256)
        assert provider.dimension == 256


# ---------------------------------------------------------------------------
# generate_embeddings_for_document tests
# ---------------------------------------------------------------------------

class TestGenerateEmbeddingsForDocument:
    def test_generates_embeddings(self, db, test_deal, tmp_path):
        content = "The quick brown fox jumps over the lazy dog. " * 10
        doc = _insert_doc_with_chunks(db, test_deal, tmp_path, content)

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        assert len(chunks) >= 1

        # Verify embeddings were set by the pipeline
        for chunk in chunks:
            assert chunk.embedding is not None
            assert isinstance(chunk.embedding, list)
            assert len(chunk.embedding) == EMBEDDING_DIM

    def test_idempotent(self, db, test_deal, tmp_path):
        content = "Idempotency test content for embedding service. " * 10
        doc = _insert_doc_with_chunks(db, test_deal, tmp_path, content)

        chunks_before = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        embeddings_before = [c.embedding for c in chunks_before]

        # Run again — should produce identical results
        n = generate_embeddings_for_document(doc.id, db)
        assert n == len(chunks_before)

        chunks_after = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        embeddings_after = [c.embedding for c in chunks_after]
        assert embeddings_before == embeddings_after

    def test_no_chunks_returns_zero(self, db, test_deal, tmp_path):
        # Create a document without running ingestion
        path = _make_txt(tmp_path, "will not chunk")
        doc = Document(
            deal_id=test_deal.id,
            filename="no_chunks.txt",
            file_path=str(path),
            mime_type="text/plain",
            file_size=10,
            status=DocumentStatus.processed,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        n = generate_embeddings_for_document(doc.id, db)
        assert n == 0

    def test_nonexistent_document_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            generate_embeddings_for_document(99999, db)

    def test_explicit_provider(self, db, test_deal, tmp_path):
        content = "Testing explicit provider injection. " * 10
        doc = _insert_doc_with_chunks(db, test_deal, tmp_path, content)

        # Use a provider with a small dimension
        small_provider = FakeEmbeddingProvider(dimension=32)
        n = generate_embeddings_for_document(doc.id, db, provider=small_provider)
        assert n >= 1

        chunk = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .first()
        )
        # SQLite stores as JSON so dimension is preserved
        assert len(chunk.embedding) == 32

    def test_provider_called_with_chunk_texts(self, db, test_deal, tmp_path):
        content = "Verify provider receives correct texts. " * 20
        path = _make_txt(tmp_path, content)
        doc = Document(
            deal_id=test_deal.id,
            filename="spy.txt",
            file_path=str(path),
            mime_type="text/plain",
            file_size=len(content),
            status=DocumentStatus.pending,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        process_document(doc.id, db)

        # Reset embeddings and re-generate with a spy
        spy = MagicMock(spec=EmbeddingProvider)
        spy.dimension = 8
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        expected_texts = [c.content for c in chunks]
        spy.embed_texts.return_value = [[0.1] * 8 for _ in chunks]

        generate_embeddings_for_document(doc.id, db, provider=spy)
        spy.embed_texts.assert_called_once_with(expected_texts)


# ---------------------------------------------------------------------------
# Pipeline integration — embeddings generated after chunking
# ---------------------------------------------------------------------------

class TestPipelineEmbeddingIntegration:
    def test_pipeline_sets_embeddings(self, db, test_deal, tmp_path):
        content = "Pipeline integration test for embeddings. " * 10
        doc = _insert_doc_with_chunks(db, test_deal, tmp_path, content)

        assert doc.status == DocumentStatus.processed

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .all()
        )
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.embedding is not None
            assert len(chunk.embedding) == EMBEDDING_DIM

    def test_upload_route_generates_embeddings(
        self, client, auth_headers, test_deal
    ):
        content = b"Upload route should trigger embedding generation automatically."
        resp = client.post(
            f"/documents/upload?deal_id={test_deal.id}",
            headers=auth_headers,
            files={"file": ("embed_test.txt", io.BytesIO(content), "text/plain")},
        )
        assert resp.status_code == 201
        doc_id = resp.json()["id"]

        listing = client.get(
            f"/documents/deals/{test_deal.id}/documents", headers=auth_headers
        ).json()
        final = next(d for d in listing if d["id"] == doc_id)
        assert final["status"] == "processed"

        # Verify DB has embeddings produced by the background ingestion task.
        from app.models.document_chunk import DocumentChunk as DC
        from tests.conftest import TestingSession

        session = TestingSession()
        try:
            chunks = session.query(DC).filter(DC.document_id == doc_id).all()
            assert len(chunks) >= 1
            for chunk in chunks:
                assert chunk.embedding is not None
        finally:
            session.close()

    def test_reprocess_replaces_embeddings(self, db, test_deal, tmp_path):
        content = "Original content for reprocessing embedding test. " * 10
        doc = _insert_doc_with_chunks(db, test_deal, tmp_path, content)

        chunks_first = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .all()
        )
        first_embeddings = [c.embedding[:5] for c in chunks_first]  # sample

        # Re-process with same content → same embeddings (deterministic fake)
        doc.status = DocumentStatus.pending
        db.commit()
        process_document(doc.id, db)

        chunks_second = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        second_embeddings = [c.embedding[:5] for c in chunks_second]

        assert len(chunks_first) == len(chunks_second)
        assert first_embeddings == second_embeddings
