"""Unit tests for SQLAlchemy models and relationships."""
from app.models import (
    User, Workspace, Deal, DealStatus,
    Document, DocumentStatus,
    DocumentChunk, ClauseFinding, ClauseType,
    RedFlag, Severity, Report, ReportType, ReportStatus,
)


def test_user_creation(db, test_user):
    user = db.query(User).filter(User.email == "test@example.com").first()
    assert user is not None
    assert user.full_name == "Test User"
    assert user.is_active is True


def test_workspace_belongs_to_user(db, test_user, test_workspace):
    assert test_workspace.owner_id == test_user.id
    assert test_workspace.owner.email == test_user.email


def test_deal_default_status(db, test_deal):
    assert test_deal.status == DealStatus.draft


def test_deal_workspace_relationship(db, test_deal, test_workspace):
    assert test_deal.workspace_id == test_workspace.id
    assert test_deal.workspace.name == test_workspace.name


def test_document_creation(db, test_deal):
    doc = Document(
        deal_id=test_deal.id,
        filename="contract.pdf",
        file_path="/uploads/contract.pdf",
        mime_type="application/pdf",
        file_size=1024,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    assert doc.status == DocumentStatus.pending
    assert doc.deal_id == test_deal.id


def test_document_chunk_creation(db, test_deal):
    doc = Document(
        deal_id=test_deal.id,
        filename="doc.pdf",
        file_path="/uploads/doc.pdf",
        mime_type="application/pdf",
        file_size=2048,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content="This is a chunk of text.",
        page_number=1,
        token_count=6,
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)

    assert chunk.document_id == doc.id
    assert chunk.chunk_index == 0
    assert chunk.document.filename == "doc.pdf"


def test_clause_finding_creation(db, test_deal):
    doc = Document(
        deal_id=test_deal.id,
        filename="nda.pdf",
        file_path="/uploads/nda.pdf",
        mime_type="application/pdf",
        file_size=512,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    finding = ClauseFinding(
        document_id=doc.id,
        clause_type=ClauseType.confidentiality,
        title="Confidentiality Clause",
        content="Both parties agree to keep information confidential.",
        page_number=3,
        confidence=0.95,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)

    assert finding.clause_type == ClauseType.confidentiality
    assert finding.confidence == 0.95


def test_red_flag_creation(db, test_deal):
    flag = RedFlag(
        deal_id=test_deal.id,
        title="Unusual termination clause",
        issue="The contract allows termination without notice.",
        severity=Severity.high,
        category="legal",
        confidence=0.88,
    )
    db.add(flag)
    db.commit()
    db.refresh(flag)

    assert flag.severity == Severity.high
    assert flag.deal.title == "Test Deal"


def test_report_creation(db, test_deal):
    report = Report(
        deal_id=test_deal.id,
        report_type=ReportType.due_diligence,
        title="Due Diligence Report",
        content="Full analysis content here.",
        status=ReportStatus.completed,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    assert report.report_type == ReportType.due_diligence
    assert report.status == ReportStatus.completed
    assert report.deal_id == test_deal.id


def test_cascade_delete_deal_documents(db, test_deal):
    doc = Document(
        deal_id=test_deal.id,
        filename="to_delete.pdf",
        file_path="/uploads/to_delete.pdf",
        mime_type="application/pdf",
        file_size=100,
    )
    db.add(doc)
    db.commit()

    assert db.query(Document).filter(Document.deal_id == test_deal.id).count() == 1

    db.delete(test_deal)
    db.commit()

    assert db.query(Document).filter(Document.deal_id == test_deal.id).count() == 0
