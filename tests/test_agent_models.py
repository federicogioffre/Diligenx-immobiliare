"""Unit tests for agent-related SQLAlchemy models (AgentRun, AgentFinding, OpenQuestion, MissingDocument)."""
from datetime import datetime, timezone

from app.models import (
    Deal,
    Document,
    DocumentStatus,
    AgentRun,
    AgentRunStatus,
    AgentFinding,
    OpenQuestion,
    Priority,
    QuestionStatus,
    MissingDocument,
    Severity,
)


# ---------------------------------------------------------------------------
# AgentRun
# ---------------------------------------------------------------------------

def test_agent_run_creation(db, test_deal):
    run = AgentRun(
        deal_id=test_deal.id,
        agent_name="deal_analysis",
        status=AgentRunStatus.pending,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    assert run.id is not None
    assert run.deal_id == test_deal.id
    assert run.agent_name == "deal_analysis"
    assert run.status == AgentRunStatus.pending
    assert run.document_id is None
    assert run.error_message is None
    assert run.input_hash is None
    assert run.created_at is not None


def test_agent_run_default_status(db, test_deal):
    run = AgentRun(deal_id=test_deal.id, agent_name="classifier")
    db.add(run)
    db.commit()
    db.refresh(run)

    assert run.status == AgentRunStatus.pending


def test_agent_run_with_document(db, test_deal):
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

    run = AgentRun(
        deal_id=test_deal.id,
        document_id=doc.id,
        agent_name="clause_extractor",
        status=AgentRunStatus.running,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    assert run.document_id == doc.id
    assert run.document.filename == "contract.pdf"
    assert run.started_at is not None


def test_agent_run_completed_with_timestamps(db, test_deal):
    now = datetime.now(timezone.utc)
    run = AgentRun(
        deal_id=test_deal.id,
        agent_name="red_flag_detector",
        status=AgentRunStatus.completed,
        started_at=now,
        completed_at=now,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    assert run.status == AgentRunStatus.completed
    assert run.completed_at is not None


def test_agent_run_failed_with_error(db, test_deal):
    run = AgentRun(
        deal_id=test_deal.id,
        agent_name="report_generator",
        status=AgentRunStatus.failed,
        error_message="LLM API timeout",
        input_hash="abc123def456",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    assert run.status == AgentRunStatus.failed
    assert run.error_message == "LLM API timeout"
    assert run.input_hash == "abc123def456"


def test_agent_run_deal_relationship(db, test_deal):
    run = AgentRun(deal_id=test_deal.id, agent_name="test_agent")
    db.add(run)
    db.commit()
    db.refresh(run)

    assert run.deal.title == "Test Deal"
    assert run in test_deal.agent_runs


# ---------------------------------------------------------------------------
# AgentFinding
# ---------------------------------------------------------------------------

def test_agent_finding_creation(db, test_deal):
    finding = AgentFinding(
        deal_id=test_deal.id,
        agent_name="clause_extractor",
        category="liability",
        title="Unlimited liability clause",
        description="The contractor accepts unlimited liability for damages.",
        severity=Severity.high,
        confidence=0.92,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)

    assert finding.id is not None
    assert finding.deal_id == test_deal.id
    assert finding.agent_name == "clause_extractor"
    assert finding.category == "liability"
    assert finding.severity == Severity.high
    assert finding.confidence == 0.92
    assert finding.document_id is None
    assert finding.source_page is None
    assert finding.source_excerpt is None
    assert finding.structured_payload_json is None


def test_agent_finding_with_document(db, test_deal):
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

    finding = AgentFinding(
        deal_id=test_deal.id,
        document_id=doc.id,
        agent_name="clause_extractor",
        category="confidentiality",
        title="NDA Scope",
        description="Broad confidentiality scope covering 5 years.",
        severity=Severity.medium,
        confidence=0.85,
        source_page=2,
        source_excerpt="Both parties shall maintain confidentiality for a period of 5 years.",
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)

    assert finding.document_id == doc.id
    assert finding.document.filename == "nda.pdf"
    assert finding.source_page == 2
    assert finding.source_excerpt is not None


def test_agent_finding_with_structured_payload(db, test_deal):
    payload = {
        "clause_type": "termination",
        "parties": ["Acme Corp", "Widget Inc"],
        "notice_period_days": 30,
    }
    finding = AgentFinding(
        deal_id=test_deal.id,
        agent_name="deep_analyzer",
        category="termination",
        title="Short notice termination",
        description="Only 30 days notice required for termination.",
        severity=Severity.low,
        structured_payload_json=payload,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)

    assert finding.structured_payload_json == payload
    assert finding.structured_payload_json["notice_period_days"] == 30


def test_agent_finding_severity_values(db, test_deal):
    """All severity values from the shared Severity enum are accepted."""
    for sev in Severity:
        finding = AgentFinding(
            deal_id=test_deal.id,
            agent_name="tester",
            category="test",
            title=f"Severity {sev.value}",
            description="Testing severity levels.",
            severity=sev,
        )
        db.add(finding)
    db.commit()

    count = db.query(AgentFinding).filter(AgentFinding.deal_id == test_deal.id).count()
    assert count == len(Severity)


def test_agent_finding_deal_relationship(db, test_deal):
    finding = AgentFinding(
        deal_id=test_deal.id,
        agent_name="test",
        category="test",
        title="Test finding",
        description="Testing.",
        severity=Severity.low,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)

    assert finding.deal.title == "Test Deal"
    assert finding in test_deal.agent_findings


# ---------------------------------------------------------------------------
# OpenQuestion
# ---------------------------------------------------------------------------

def test_open_question_creation(db, test_deal):
    q = OpenQuestion(
        deal_id=test_deal.id,
        agent_name="gap_analyzer",
        question="Is there an insurance certificate attached to the contract?",
        priority=Priority.high,
    )
    db.add(q)
    db.commit()
    db.refresh(q)

    assert q.id is not None
    assert q.deal_id == test_deal.id
    assert q.agent_name == "gap_analyzer"
    assert q.question == "Is there an insurance certificate attached to the contract?"
    assert q.priority == Priority.high
    assert q.status == QuestionStatus.open
    assert q.document_id is None
    assert q.created_at is not None


def test_open_question_default_status(db, test_deal):
    q = OpenQuestion(
        deal_id=test_deal.id,
        agent_name="checker",
        question="Test question?",
        priority=Priority.low,
    )
    db.add(q)
    db.commit()
    db.refresh(q)

    assert q.status == QuestionStatus.open


def test_open_question_resolved(db, test_deal):
    q = OpenQuestion(
        deal_id=test_deal.id,
        agent_name="checker",
        question="Was warranty discussed?",
        priority=Priority.medium,
        status=QuestionStatus.resolved,
    )
    db.add(q)
    db.commit()
    db.refresh(q)

    assert q.status == QuestionStatus.resolved


def test_open_question_with_document(db, test_deal):
    doc = Document(
        deal_id=test_deal.id,
        filename="agreement.docx",
        file_path="/uploads/agreement.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=2048,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    q = OpenQuestion(
        deal_id=test_deal.id,
        document_id=doc.id,
        agent_name="reviewer",
        question="Is the indemnification clause mutual?",
        priority=Priority.high,
    )
    db.add(q)
    db.commit()
    db.refresh(q)

    assert q.document_id == doc.id
    assert q.document.filename == "agreement.docx"


def test_open_question_priority_values(db, test_deal):
    """All priority values are accepted."""
    for pri in Priority:
        q = OpenQuestion(
            deal_id=test_deal.id,
            agent_name="tester",
            question=f"Priority {pri.value} question?",
            priority=pri,
        )
        db.add(q)
    db.commit()

    count = db.query(OpenQuestion).filter(OpenQuestion.deal_id == test_deal.id).count()
    assert count == len(Priority)


def test_open_question_deal_relationship(db, test_deal):
    q = OpenQuestion(
        deal_id=test_deal.id,
        agent_name="test",
        question="Test?",
        priority=Priority.low,
    )
    db.add(q)
    db.commit()
    db.refresh(q)

    assert q.deal.title == "Test Deal"
    assert q in test_deal.open_questions


# ---------------------------------------------------------------------------
# MissingDocument
# ---------------------------------------------------------------------------

def test_missing_document_creation(db, test_deal):
    md = MissingDocument(
        deal_id=test_deal.id,
        document_category="insurance",
        expected_item="Certificate of Insurance",
        reason="Standard due diligence requires proof of insurance coverage.",
        priority=Priority.high,
    )
    db.add(md)
    db.commit()
    db.refresh(md)

    assert md.id is not None
    assert md.deal_id == test_deal.id
    assert md.document_category == "insurance"
    assert md.expected_item == "Certificate of Insurance"
    assert md.priority == Priority.high
    assert md.created_at is not None


def test_missing_document_priority_values(db, test_deal):
    """All priority values are accepted."""
    for pri in Priority:
        md = MissingDocument(
            deal_id=test_deal.id,
            document_category="test",
            expected_item=f"Item {pri.value}",
            reason="Testing.",
            priority=pri,
        )
        db.add(md)
    db.commit()

    count = db.query(MissingDocument).filter(MissingDocument.deal_id == test_deal.id).count()
    assert count == len(Priority)


def test_missing_document_deal_relationship(db, test_deal):
    md = MissingDocument(
        deal_id=test_deal.id,
        document_category="financial",
        expected_item="Audited Financial Statements",
        reason="Required for valuation assessment.",
        priority=Priority.medium,
    )
    db.add(md)
    db.commit()
    db.refresh(md)

    assert md.deal.title == "Test Deal"
    assert md in test_deal.missing_documents


# ---------------------------------------------------------------------------
# Cascade delete
# ---------------------------------------------------------------------------

def test_cascade_delete_deal_removes_agent_runs(db, test_deal):
    run = AgentRun(deal_id=test_deal.id, agent_name="test_agent")
    db.add(run)
    db.commit()

    assert db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).count() == 1

    db.delete(test_deal)
    db.commit()

    assert db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).count() == 0


def test_cascade_delete_deal_removes_agent_findings(db, test_deal):
    finding = AgentFinding(
        deal_id=test_deal.id,
        agent_name="tester",
        category="test",
        title="To be deleted",
        description="Should be cascade deleted.",
        severity=Severity.low,
    )
    db.add(finding)
    db.commit()

    assert db.query(AgentFinding).filter(AgentFinding.deal_id == test_deal.id).count() == 1

    db.delete(test_deal)
    db.commit()

    assert db.query(AgentFinding).filter(AgentFinding.deal_id == test_deal.id).count() == 0


def test_cascade_delete_deal_removes_open_questions(db, test_deal):
    q = OpenQuestion(
        deal_id=test_deal.id,
        agent_name="tester",
        question="Will this be deleted?",
        priority=Priority.low,
    )
    db.add(q)
    db.commit()

    assert db.query(OpenQuestion).filter(OpenQuestion.deal_id == test_deal.id).count() == 1

    db.delete(test_deal)
    db.commit()

    assert db.query(OpenQuestion).filter(OpenQuestion.deal_id == test_deal.id).count() == 0


def test_cascade_delete_deal_removes_missing_documents(db, test_deal):
    md = MissingDocument(
        deal_id=test_deal.id,
        document_category="legal",
        expected_item="Operating Agreement",
        reason="Standard requirement.",
        priority=Priority.medium,
    )
    db.add(md)
    db.commit()

    assert db.query(MissingDocument).filter(MissingDocument.deal_id == test_deal.id).count() == 1

    db.delete(test_deal)
    db.commit()

    assert db.query(MissingDocument).filter(MissingDocument.deal_id == test_deal.id).count() == 0
