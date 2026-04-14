"""Tests for due-diligence report generation.

Covers:
- generate_due_diligence_report() unit behaviour
- Idempotency (re-running replaces the previous report)
- Report stored in DB with correct status
- Required Markdown sections present
- POST /deals/{deal_id}/report API route
- Authorization & 404 handling
"""
import pytest
from sqlalchemy.orm import Session

from app.models.deal import Deal, DealStatus
from app.models.document import Document, DocumentStatus
from app.models.clause_finding import ClauseFinding, ClauseType
from app.models.red_flag import RedFlag, Severity
from app.models.report import Report, ReportType, ReportStatus
from packages.agents.deal_analysis_agent import (
    FakeLLMProvider,
    set_llm_provider,
)
from packages.agents.report_agent import generate_due_diligence_report


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def use_fake_llm():
    """Inject FakeLLMProvider globally for every test in this module."""
    set_llm_provider(FakeLLMProvider())
    yield
    set_llm_provider(None)


@pytest.fixture
def analyzed_deal(db: Session, test_deal: Deal) -> Deal:
    """A deal that has been fully analysed (has documents, findings, red flags)."""
    # Processed document
    doc = Document(
        deal_id=test_deal.id,
        filename="service_agreement.txt",
        file_path="/tmp/service_agreement.txt",
        mime_type="text/plain",
        file_size=2048,
        status=DocumentStatus.processed,
        raw_text=(
            "SERVICE AGREEMENT between Party A and Party B. "
            "Either party may terminate with 30 days notice. "
            "Liability shall not exceed the contract value."
        ),
        language="en",
        page_count=3,
    )
    db.add(doc)
    db.flush()

    # Clause findings
    db.add(ClauseFinding(
        document_id=doc.id,
        clause_type=ClauseType.termination,
        title="Termination Clause",
        content="Either party may terminate with 30 days written notice.",
        page_number=1,
        confidence=0.85,
    ))
    db.add(ClauseFinding(
        document_id=doc.id,
        clause_type=ClauseType.liability,
        title="Limitation of Liability",
        content="Liability shall not exceed the total contract value.",
        page_number=2,
        confidence=0.80,
    ))

    # Red flag
    db.add(RedFlag(
        deal_id=test_deal.id,
        title="Unilateral Termination Right",
        description="Only one party may terminate without cause.",
        severity=Severity.high,
        category="termination",
        confidence=0.88,
    ))

    test_deal.status = DealStatus.reviewed
    db.commit()
    db.refresh(test_deal)
    return test_deal


# ── Unit tests: generate_due_diligence_report ──────────────────────────────

class TestGenerateDueDiligenceReport:

    def test_returns_expected_keys(self, db: Session, analyzed_deal: Deal):
        result = generate_due_diligence_report(analyzed_deal.id, db)
        assert "report_id" in result
        assert "deal_id" in result
        assert "markdown" in result
        assert result["deal_id"] == analyzed_deal.id

    def test_report_persisted_in_db(self, db: Session, analyzed_deal: Deal):
        result = generate_due_diligence_report(analyzed_deal.id, db)
        report = db.query(Report).filter(Report.id == result["report_id"]).first()
        assert report is not None
        assert report.deal_id == analyzed_deal.id
        assert report.report_type == ReportType.due_diligence
        assert report.status == ReportStatus.completed
        assert report.content is not None
        assert len(report.content) > 0

    def test_report_title(self, db: Session, analyzed_deal: Deal):
        generate_due_diligence_report(analyzed_deal.id, db)
        report = (
            db.query(Report)
            .filter(
                Report.deal_id == analyzed_deal.id,
                Report.report_type == ReportType.due_diligence,
            )
            .first()
        )
        assert analyzed_deal.title in report.title

    def test_markdown_contains_required_sections(self, db: Session, analyzed_deal: Deal):
        result = generate_due_diligence_report(analyzed_deal.id, db)
        md = result["markdown"]
        assert "## Executive Summary" in md
        assert "## Red Flags" in md
        assert "## Observations" in md
        assert "## Information Requests" in md
        assert "## Documents Reviewed" in md

    def test_markdown_is_stored_as_content(self, db: Session, analyzed_deal: Deal):
        result = generate_due_diligence_report(analyzed_deal.id, db)
        report = db.query(Report).filter(Report.id == result["report_id"]).first()
        assert report.content == result["markdown"]

    # ── Idempotency ───────────────────────────────────────────────────── #

    def test_idempotent_replaces_report(self, db: Session, analyzed_deal: Deal):
        r1 = generate_due_diligence_report(analyzed_deal.id, db)
        r2 = generate_due_diligence_report(analyzed_deal.id, db)

        # Same report row is reused (same ID)
        assert r1["report_id"] == r2["report_id"]

    def test_idempotent_only_one_report_row(self, db: Session, analyzed_deal: Deal):
        generate_due_diligence_report(analyzed_deal.id, db)
        generate_due_diligence_report(analyzed_deal.id, db)

        count = (
            db.query(Report)
            .filter(
                Report.deal_id == analyzed_deal.id,
                Report.report_type == ReportType.due_diligence,
            )
            .count()
        )
        assert count == 1

    # ── Edge cases ────────────────────────────────────────────────────── #

    def test_deal_not_found_raises(self, db: Session):
        with pytest.raises(ValueError, match="Deal 99999 not found"):
            generate_due_diligence_report(99999, db)

    def test_deal_with_no_findings(self, db: Session, test_deal: Deal):
        """Report is still generated even if no analysis has been run."""
        result = generate_due_diligence_report(test_deal.id, db)
        assert result["markdown"]
        report = db.query(Report).filter(Report.id == result["report_id"]).first()
        assert report.status == ReportStatus.completed


# ── API route tests ────────────────────────────────────────────────────────

class TestReportRoute:

    def test_generate_report_returns_200(
        self, client, auth_headers, analyzed_deal: Deal
    ):
        response = client.post(
            f"/deals/{analyzed_deal.id}/report",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "report_id" in data
        assert "deal_id" in data
        assert "markdown" in data
        assert data["deal_id"] == analyzed_deal.id

    def test_report_markdown_has_sections(
        self, client, auth_headers, analyzed_deal: Deal
    ):
        response = client.post(
            f"/deals/{analyzed_deal.id}/report",
            headers=auth_headers,
        )
        md = response.json()["markdown"]
        for section in (
            "Executive Summary",
            "Red Flags",
            "Observations",
            "Information Requests",
            "Documents Reviewed",
        ):
            assert section in md

    def test_report_requires_authentication(self, client, test_deal: Deal):
        response = client.post(f"/deals/{test_deal.id}/report")
        assert response.status_code in (401, 403)

    def test_report_unknown_deal_returns_404(self, client, auth_headers):
        response = client.post("/deals/99999/report", headers=auth_headers)
        assert response.status_code == 404

    def test_report_idempotent_via_api(
        self, client, auth_headers, analyzed_deal: Deal
    ):
        r1 = client.post(
            f"/deals/{analyzed_deal.id}/report", headers=auth_headers
        )
        r2 = client.post(
            f"/deals/{analyzed_deal.id}/report", headers=auth_headers
        )
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["report_id"] == r2.json()["report_id"]

    def test_report_wrong_user_returns_404(self, client, db: Session, analyzed_deal: Deal):
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

        token = create_access_token(other.email)
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            f"/deals/{analyzed_deal.id}/report", headers=headers
        )
        assert response.status_code == 404
