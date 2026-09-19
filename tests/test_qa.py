"""Tests for deal question-answering (RAG pipeline).

Covers:
- retrieval_service: cosine similarity search over embedded chunks
- deal_qa_agent: end-to-end Q&A with answer + sources
- POST /deals/{deal_id}/ask API route
- Edge cases: no chunks, no embeddings, auth, 404
"""
import math

import pytest
from sqlalchemy.orm import Session

from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk, EMBEDDING_DIM
from packages.retrieval.embedding_service import FakeEmbeddingProvider
from packages.retrieval.retrieval_service import (
    search_similar_chunks,
    _cosine_similarity,
    ChunkMatch,
)
from packages.agents.deal_analysis_agent import (
    FakeLLMProvider,
    set_llm_provider,
)
from packages.agents.deal_qa_agent import answer_deal_question


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def use_fake_llm():
    """Inject FakeLLMProvider globally for every test in this module."""
    set_llm_provider(FakeLLMProvider())
    yield
    set_llm_provider(None)


@pytest.fixture
def embedded_doc(db: Session, test_deal: Deal) -> Document:
    """A processed document with chunks that have embeddings."""
    fake_emb = FakeEmbeddingProvider(dimension=EMBEDDING_DIM)

    doc = Document(
        deal_id=test_deal.id,
        filename="contract.txt",
        file_path="/tmp/contract.txt",
        mime_type="text/plain",
        file_size=1500,
        status=DocumentStatus.processed,
        raw_text=(
            "Either party may terminate this agreement with 30 days notice. "
            "Liability shall not exceed the total contract value. "
            "All information shall be kept confidential."
        ),
        language="en",
        page_count=2,
    )
    db.add(doc)
    db.flush()

    texts = [
        "Either party may terminate this agreement with 30 days written notice.",
        "In no event shall liability exceed the total contract value.",
        "All information disclosed shall be kept strictly confidential.",
    ]
    embeddings = fake_emb.embed_texts(texts)

    for i, (text, vec) in enumerate(zip(texts, embeddings)):
        chunk = DocumentChunk(
            document_id=doc.id,
            chunk_index=i,
            content=text,
            page_number=i + 1,
            token_count=len(text.split()),
            embedding=vec,
        )
        db.add(chunk)

    db.commit()
    db.refresh(doc)
    return doc


# ── Unit tests: cosine similarity ─────────────────────────────────────────

class TestCosineSimilarity:

    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 1.0]
        assert _cosine_similarity(a, b) == 0.0


# ── Unit tests: search_similar_chunks ─────────────────────────────────────

class TestSearchSimilarChunks:

    def test_returns_chunk_matches(self, db: Session, test_deal: Deal, embedded_doc: Document):
        results = search_similar_chunks(
            deal_id=test_deal.id,
            query="termination notice",
            db=db,
            top_k=3,
        )
        assert len(results) > 0
        assert all(isinstance(r, ChunkMatch) for r in results)

    def test_results_sorted_by_score_desc(self, db: Session, test_deal: Deal, embedded_doc: Document):
        results = search_similar_chunks(
            deal_id=test_deal.id,
            query="termination",
            db=db,
            top_k=3,
        )
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_limits_results(self, db: Session, test_deal: Deal, embedded_doc: Document):
        results = search_similar_chunks(
            deal_id=test_deal.id,
            query="anything",
            db=db,
            top_k=2,
        )
        assert len(results) <= 2

    def test_no_chunks_returns_empty(self, db: Session, test_deal: Deal):
        """Deal with no documents returns empty list."""
        results = search_similar_chunks(
            deal_id=test_deal.id,
            query="anything",
            db=db,
        )
        assert results == []

    def test_results_contain_document_info(self, db: Session, test_deal: Deal, embedded_doc: Document):
        results = search_similar_chunks(
            deal_id=test_deal.id,
            query="liability",
            db=db,
            top_k=1,
        )
        r = results[0]
        assert r.document_id == embedded_doc.id
        assert r.content
        assert r.page_number is not None


# ── Unit tests: answer_deal_question ──────────────────────────────────────

class TestAnswerDealQuestion:

    def test_returns_answer_and_sources(self, db: Session, test_deal: Deal, embedded_doc: Document):
        result = answer_deal_question(test_deal.id, "What is the termination notice?", db)
        assert "answer" in result
        assert "sources" in result
        assert isinstance(result["answer"], str)
        assert isinstance(result["sources"], list)

    def test_answer_is_non_empty(self, db: Session, test_deal: Deal, embedded_doc: Document):
        result = answer_deal_question(test_deal.id, "What is the liability cap?", db)
        assert len(result["answer"]) > 0

    def test_sources_have_expected_keys(self, db: Session, test_deal: Deal, embedded_doc: Document):
        result = answer_deal_question(test_deal.id, "termination clause", db)
        assert len(result["sources"]) > 0
        src = result["sources"][0]
        assert "document_id" in src
        assert "page_number" in src
        assert "excerpt" in src

    def test_sources_reference_actual_document(self, db: Session, test_deal: Deal, embedded_doc: Document):
        result = answer_deal_question(test_deal.id, "confidentiality", db)
        doc_ids = {s["document_id"] for s in result["sources"]}
        assert embedded_doc.id in doc_ids

    def test_no_documents_returns_fallback(self, db: Session, test_deal: Deal):
        """Deal with no embedded chunks returns a fallback answer."""
        result = answer_deal_question(test_deal.id, "What is the contract about?", db)
        assert "No document content" in result["answer"]
        assert result["sources"] == []

    def test_deal_not_found_raises(self, db: Session):
        with pytest.raises(ValueError, match="Deal 99999 not found"):
            answer_deal_question(99999, "anything", db)


# ── API route tests ────────────────────────────────────────────────────────

class TestAskRoute:

    def test_ask_returns_200(
        self, client, auth_headers, test_deal: Deal, embedded_doc: Document
    ):
        response = client.post(
            f"/deals/{test_deal.id}/ask",
            json={"question": "What is the termination clause?"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "sources" in data

    def test_ask_response_sources_shape(
        self, client, auth_headers, test_deal: Deal, embedded_doc: Document
    ):
        response = client.post(
            f"/deals/{test_deal.id}/ask",
            json={"question": "liability limit?"},
            headers=auth_headers,
        )
        data = response.json()
        assert isinstance(data["sources"], list)
        if data["sources"]:
            src = data["sources"][0]
            assert "document_id" in src
            assert "page_number" in src
            assert "excerpt" in src

    def test_ask_requires_authentication(self, client, test_deal: Deal):
        response = client.post(
            f"/deals/{test_deal.id}/ask",
            json={"question": "test?"},
        )
        assert response.status_code in (401, 403)

    def test_ask_unknown_deal_returns_404(self, client, auth_headers):
        response = client.post(
            "/deals/99999/ask",
            json={"question": "test?"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_ask_missing_question_returns_422(self, client, auth_headers, test_deal: Deal):
        response = client.post(
            f"/deals/{test_deal.id}/ask",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_ask_wrong_user_returns_404(
        self, client, db: Session, test_deal: Deal
    ):
        from app.models.user import User
        from app.core.security import hash_password, create_access_token

        other = User(
            email="other@example.com",
            hashed_password=hash_password("pass123"),
            full_name="Other User",
        )
        db.add(other)
        db.commit()
        db.refresh(other)

        token = create_access_token(other.email, user_id=other.id, hashed_password=other.hashed_password)
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            f"/deals/{test_deal.id}/ask",
            json={"question": "test?"},
            headers=headers,
        )
        assert response.status_code == 404

    def test_ask_no_documents_returns_fallback(
        self, client, auth_headers, test_deal: Deal
    ):
        """A deal with no embedded chunks should still return 200 with fallback."""
        response = client.post(
            f"/deals/{test_deal.id}/ask",
            json={"question": "What is this about?"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "No document content" in data["answer"]
        assert data["sources"] == []
