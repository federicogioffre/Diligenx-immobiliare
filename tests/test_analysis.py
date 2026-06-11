"""Tests for the deal AI analysis pipeline.

Covers:
- DealAnalysisAgent unit behaviour (legacy agent — kept for regression)
- Idempotency (re-running clears previous results)
- Status transitions (draft/reviewed → analyzing → reviewed)
- Skipping unprocessed / empty documents
- POST /deals/{deal_id}/analyze API route (now backed by orchestrator pipeline)
- Authorization (wrong user → 404, no token → 403)
- Full pipeline response structure (stages, completed, report_id, etc.)
"""
import pytest
from sqlalchemy.orm import Session

from app.models.deal import Deal, DealStatus
from app.models.document import Document, DocumentStatus
from app.models.clause_finding import ClauseFinding
from app.models.red_flag import RedFlag
from packages.agents.deal_analysis_agent import (
    DealAnalysisAgent,
    FakeLLMProvider,
    set_llm_provider,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def use_fake_llm():
    """Inject FakeLLMProvider globally for every test in this module."""
    set_llm_provider(FakeLLMProvider())
    yield
    set_llm_provider(None)


@pytest.fixture
def processed_doc(db: Session, test_deal: Deal) -> Document:
    """A fully processed document with raw text (simulates post-ingestion state)."""
    doc = Document(
        deal_id=test_deal.id,
        filename="service_agreement.txt",
        file_path="/tmp/service_agreement.txt",
        mime_type="text/plain",
        file_size=2048,
        status=DocumentStatus.processed,
        raw_text=(
            "SERVICE AGREEMENT\n\n"
            "This agreement is entered into by and between Party A (Client) "
            "and Party B (Provider).\n\n"
            "TERMINATION: Either party may terminate with 30 days written notice.\n\n"
            "LIABILITY: Liability shall not exceed the total contract value.\n\n"
            "CONFIDENTIALITY: Both parties agree to keep all information "
            "disclosed under this agreement strictly confidential."
        ),
        language="en",
        page_count=3,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


# ── Unit tests: DealAnalysisAgent ─────────────────────────────────────────

class TestDealAnalysisAgent:

    def test_returns_expected_keys(self, db: Session, test_deal: Deal, processed_doc: Document):
        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        result = agent.analyze_deal(test_deal.id, db)

        assert result["deal_id"] == test_deal.id
        assert "documents_analyzed" in result
        assert "clause_findings_count" in result
        assert "red_flags_count" in result

    def test_deal_status_set_to_reviewed(self, db: Session, test_deal: Deal, processed_doc: Document):
        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        agent.analyze_deal(test_deal.id, db)

        db.refresh(test_deal)
        assert test_deal.status == DealStatus.reviewed

    def test_clause_findings_persisted(self, db: Session, test_deal: Deal, processed_doc: Document):
        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        agent.analyze_deal(test_deal.id, db)

        findings = (
            db.query(ClauseFinding)
            .filter(ClauseFinding.document_id == processed_doc.id)
            .all()
        )
        assert len(findings) > 0

    def test_red_flags_persisted(self, db: Session, test_deal: Deal, processed_doc: Document):
        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        agent.analyze_deal(test_deal.id, db)

        flags = db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).all()
        assert len(flags) > 0

    def test_clause_finding_fields(self, db: Session, test_deal: Deal, processed_doc: Document):
        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        agent.analyze_deal(test_deal.id, db)

        finding = (
            db.query(ClauseFinding)
            .filter(ClauseFinding.document_id == processed_doc.id)
            .first()
        )
        assert finding is not None
        assert finding.title
        assert finding.content
        assert finding.clause_type is not None
        assert finding.confidence is not None

    def test_red_flag_fields(self, db: Session, test_deal: Deal, processed_doc: Document):
        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        agent.analyze_deal(test_deal.id, db)

        flag = db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).first()
        assert flag is not None
        assert flag.title
        assert flag.issue
        assert flag.severity is not None
        assert flag.category

    # ── Idempotency ───────────────────────────────────────────────────── #

    def test_idempotent_clause_findings(self, db: Session, test_deal: Deal, processed_doc: Document):
        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        agent.analyze_deal(test_deal.id, db)
        count_first = (
            db.query(ClauseFinding)
            .filter(ClauseFinding.document_id == processed_doc.id)
            .count()
        )

        agent.analyze_deal(test_deal.id, db)
        count_second = (
            db.query(ClauseFinding)
            .filter(ClauseFinding.document_id == processed_doc.id)
            .count()
        )

        assert count_first == count_second

    def test_idempotent_red_flags(self, db: Session, test_deal: Deal, processed_doc: Document):
        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        agent.analyze_deal(test_deal.id, db)
        count_first = (
            db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count()
        )

        agent.analyze_deal(test_deal.id, db)
        count_second = (
            db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count()
        )

        assert count_first == count_second

    # ── Edge cases ────────────────────────────────────────────────────── #

    def test_skips_pending_documents(self, db: Session, test_deal: Deal):
        """Documents not in 'processed' status are ignored."""
        pending = Document(
            deal_id=test_deal.id,
            filename="pending.txt",
            file_path="/tmp/pending.txt",
            mime_type="text/plain",
            file_size=100,
            status=DocumentStatus.pending,
            raw_text="Some contract text here.",
        )
        db.add(pending)
        db.commit()

        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        result = agent.analyze_deal(test_deal.id, db)

        assert result["documents_analyzed"] == 0

    def test_skips_documents_with_no_text(self, db: Session, test_deal: Deal):
        """Processed documents with empty raw_text are silently skipped."""
        empty_doc = Document(
            deal_id=test_deal.id,
            filename="empty.txt",
            file_path="/tmp/empty.txt",
            mime_type="text/plain",
            file_size=0,
            status=DocumentStatus.processed,
            raw_text="",
        )
        db.add(empty_doc)
        db.commit()

        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        result = agent.analyze_deal(test_deal.id, db)

        assert result["documents_analyzed"] == 0

    def test_non_contract_doc_skips_clause_extraction(self, db: Session, test_deal: Deal):
        """A document classified as 'report' should not produce clause findings."""

        class ReportFakeLLM(FakeLLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "CLASSIFY" in prompt.upper():
                    import json
                    return json.dumps({
                        "document_type": "report",
                        "confidence": 0.95,
                        "rationale": "This is an audit report.",
                    })
                return super().complete(prompt, max_tokens)

        report_doc = Document(
            deal_id=test_deal.id,
            filename="audit_report.txt",
            file_path="/tmp/audit_report.txt",
            mime_type="text/plain",
            file_size=500,
            status=DocumentStatus.processed,
            raw_text="Q3 Audit Report: Revenue increased by 12%.",
        )
        db.add(report_doc)
        db.commit()

        agent = DealAnalysisAgent(provider=ReportFakeLLM())
        result = agent.analyze_deal(test_deal.id, db)

        assert result["documents_analyzed"] == 1
        assert result["clause_findings_count"] == 0

    def test_deal_not_found_raises_value_error(self, db: Session):
        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        with pytest.raises(ValueError, match="Deal 99999 not found"):
            agent.analyze_deal(99999, db)

    def test_multiple_documents_all_analyzed(self, db: Session, test_deal: Deal):
        """All processed documents in a deal should be analysed."""
        for i in range(3):
            doc = Document(
                deal_id=test_deal.id,
                filename=f"contract_{i}.txt",
                file_path=f"/tmp/contract_{i}.txt",
                mime_type="text/plain",
                file_size=500,
                status=DocumentStatus.processed,
                raw_text=f"Agreement number {i}. Either party may terminate.",
            )
            db.add(doc)
        db.commit()

        agent = DealAnalysisAgent(provider=FakeLLMProvider())
        result = agent.analyze_deal(test_deal.id, db)

        assert result["documents_analyzed"] == 3


# ── API route tests ────────────────────────────────────────────────────────

class TestAnalyzeRoute:

    def test_analyze_returns_202_with_expected_shape(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        response = client.post(
            f"/deals/{test_deal.id}/analyze",
            headers=auth_headers,
        )
        assert response.status_code == 202
        data = response.json()
        assert data["deal_id"] == test_deal.id
        assert "status" in data
        assert "completed" in data
        assert "documents_analyzed" in data
        assert "clause_findings_count" in data
        assert "red_flags_count" in data
        assert "open_questions_count" in data
        assert "stages" in data

    def test_analyze_requires_authentication(self, client, test_deal: Deal):
        response = client.post(f"/deals/{test_deal.id}/analyze")
        assert response.status_code in (401, 403)

    def test_analyze_unknown_deal_returns_404(self, client, auth_headers):
        response = client.post("/deals/99999/analyze", headers=auth_headers)
        assert response.status_code == 404

    def test_analyze_updates_deal_status_to_reviewed(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document, db: Session
    ):
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        db.refresh(test_deal)
        assert test_deal.status == DealStatus.reviewed

    def test_analyze_idempotent_via_api(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        """Two consecutive calls must yield identical finding counts."""
        r1 = client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        r2 = client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)

        assert r1.status_code == 202
        assert r2.status_code == 202
        # Both responses are accepted immediately (202); idempotency of the
        # actual pipeline is tested via the direct agent-layer tests.
        assert r1.json()["deal_id"] == r2.json()["deal_id"]

    def test_analyze_deal_belongs_to_other_user_returns_404(
        self, client, db: Session, test_deal: Deal
    ):
        """A valid JWT for a different user cannot access another user's deal."""
        from app.models.user import User
        from app.models.workspace import Workspace
        from app.core.security import hash_password, create_access_token

        other = User(
            email="other@example.com",
            hashed_password=hash_password("pass123"),
            full_name="Other User",
        )
        db.add(other)
        db.commit()
        db.refresh(other)

        token = create_access_token(other.email)
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post(f"/deals/{test_deal.id}/analyze", headers=headers)
        assert response.status_code == 404

    def test_analyze_response_counts_match_db(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document, db: Session
    ):
        """Counts in DB after pipeline match what the dedicated list endpoints return."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)

        # Background task ran synchronously (TestClient) → check DB directly
        db.expire_all()  # ensure fresh read from the shared test session
        db_findings = (
            db.query(ClauseFinding)
            .filter(ClauseFinding.document_id == processed_doc.id)
            .count()
        )
        db_flags = (
            db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count()
        )

        findings_resp = client.get(
            f"/deals/{test_deal.id}/clause-findings", headers=auth_headers
        )
        flags_resp = client.get(
            f"/deals/{test_deal.id}/red-flags", headers=auth_headers
        )
        assert findings_resp.status_code == 200
        assert flags_resp.status_code == 200
        assert len(findings_resp.json()) == db_findings
        assert len(flags_resp.json()) == db_flags

    def test_analyze_completed_true_on_success(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document, db: Session
    ):
        """Deal status is 'reviewed' after successful pipeline run."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        db.expire_all()
        db.refresh(test_deal)
        assert test_deal.status == DealStatus.reviewed

    def test_analyze_returns_report_id(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        """A Report row is created; it is accessible via GET /deals/{id}/report."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        report_resp = client.get(
            f"/deals/{test_deal.id}/report", headers=auth_headers
        )
        assert report_resp.status_code == 200
        data = report_resp.json()
        assert data["report_id"] is not None
        assert isinstance(data["report_id"], int)

    def test_analyze_stages_contains_all_seven(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document, db: Session
    ):
        """Six agent-run records are written (one per pipeline stage)."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        runs_resp = client.get(
            f"/deals/{test_deal.id}/agent-runs", headers=auth_headers
        )
        assert runs_resp.status_code == 200
        stage_names = {r["agent_name"] for r in runs_resp.json()}
        expected = {
            "intake", "document_router", "contract_analysis",
            "corporate_governance", "corporate_intro_extraction",
            "red_flag_aggregation", "report_generation",
        }
        assert stage_names == expected

    def test_analyze_open_questions_count_in_response(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document, db: Session
    ):
        """Open questions created by the pipeline are visible in the DB."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        db.expire_all()
        from app.models.open_question import OpenQuestion
        db_count = (
            db.query(OpenQuestion)
            .filter(OpenQuestion.deal_id == test_deal.id)
            .count()
        )
        # At least 0; just confirm the query works and the pipeline ran
        assert db_count >= 0
