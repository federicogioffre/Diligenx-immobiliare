"""Resume only a verified unchanged corpus and its contiguous completed stages."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.agent_finding import AgentFinding
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.deal import Deal, DealStatus
from app.models.document import Document, DocumentStatus
from app.models.red_flag import Severity
from app.models.report import Report, ReportStatus, ReportType
from packages.agents import orchestrator
from packages.agents.analysis_checkpoint import (
    CheckpointError, STAGES, adopt_legacy_checkpoint, corpus_fingerprint, validate_resume,
)
from packages.agents.deal_analysis_agent import FakeLLMProvider


PREFIX = tuple(key for key, _ in STAGES[:6])
PREFIX_FUNCTIONS = (
    "_stage_intake", "_stage_document_routing", "_stage_specialist_analysis",
    "_stage_corporate_analysis", "_stage_corporate_intro_extraction", "_stage_tax_analysis",
)
TEXT = ("Either party may terminate with 30 days written notice. "
        "Liability shall not exceed the total contract value.")


@pytest.fixture
def checkpoint_case(db, test_deal):
    """A known interrupted run, with older published aggregation/report rows."""
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    test_deal.status = DealStatus.analyzing
    test_deal.report_language = "it"
    test_deal.updated_at = start - timedelta(seconds=1)
    docs = []
    for filename in ("contract.txt", "financial_statements.txt"):
        doc = Document(deal_id=test_deal.id, filename=filename, file_path="fixture/" + filename,
                       mime_type="text/plain", file_size=len(TEXT), status=DocumentStatus.processed,
                       raw_text=TEXT, language="en", page_count=1,
                       created_at=start - timedelta(days=1), updated_at=start - timedelta(minutes=5))
        db.add(doc)
        docs.append(doc)
    db.flush()
    fingerprint, _ = corpus_fingerprint(db, test_deal.id)
    runs = {}
    for index, (key, name) in enumerate(STAGES):
        current = index < 7
        run_start = start + timedelta(seconds=index * 10) if current else start - timedelta(days=1)
        run = AgentRun(deal_id=test_deal.id, agent_name=name,
                       status=AgentRunStatus.failed if index == 6 else AgentRunStatus.completed,
                       started_at=run_start, completed_at=run_start + timedelta(seconds=5),
                       error_message="Interrupted finance" if index == 6 else None,
                       input_hash=fingerprint if index == 0 else None)
        db.add(run)
        runs[key] = run
    for doc, kind in zip(docs, ("contract", "financial_statement")):
        db.add(AgentFinding(deal_id=test_deal.id, document_id=doc.id, agent_name="document_router",
                            category="document_classification", title="Classified", description="Fixture routing",
                            severity=Severity.low, structured_payload_json={"document_type": kind, "confidence": 0.9}))
    preserved = AgentFinding(deal_id=test_deal.id, document_id=docs[0].id, agent_name="contract_analysis",
                             category="contract", title="Preserved contract result", description=TEXT,
                             severity=Severity.medium)
    report = Report(deal_id=test_deal.id, report_type=ReportType.due_diligence,
                    title="Previous published report", content="Do not replace on failure",
                    status=ReportStatus.completed)
    db.add_all([preserved, report])
    db.commit()
    return SimpleNamespace(deal=test_deal, docs=docs, runs=runs, start=start,
                           fingerprint=fingerprint, preserved=preserved, report=report)


def run_snapshot(db, deal_id, names):
    return [tuple(getattr(run, column.name) for column in AgentRun.__table__.columns)
            for run in db.query(AgentRun).filter(AgentRun.deal_id == deal_id,
                                                AgentRun.agent_name.in_(names)).order_by(AgentRun.id)]


def fail_if_called(*args, **kwargs):
    pytest.fail("A checkpointed/dependency-blocked stage was executed")


def test_checkpoint_contains_exact_completed_prefix_and_saved_routing(db, checkpoint_case):
    case = checkpoint_case
    plan = validate_resume(db, case.deal.id)
    assert plan.completed == PREFIX
    assert plan.fingerprint == case.fingerprint
    assert {row["document_id"] for row in plan.classifications} == {doc.id for doc in case.docs}
    assert {row["document_type"] for row in plan.classifications} == {"contract", "financial_statement"}


@pytest.mark.parametrize("mutation", [
    "text", "filename", "storage_key", "language", "page_count", "size", "not_ready",
    "deal_title", "deal_description", "deal_value", "report_language", "add_document", "delete_document",
])
def test_resume_rejects_changed_documents_or_deal_inputs(db, checkpoint_case, mutation):
    case = checkpoint_case
    doc = case.docs[0]
    changes = {
        "text": (doc, "raw_text", TEXT + " Amended liability clause."),
        "filename": (doc, "filename", "amended-contract.txt"),
        "storage_key": (doc, "file_path", "replacement/object"),
        "language": (doc, "language", "it"),
        "page_count": (doc, "page_count", 2),
        "size": (doc, "file_size", 9999),
        "not_ready": (doc, "status", DocumentStatus.pending),
        "deal_title": (case.deal, "title", "Another acquisition"),
        "deal_description": (case.deal, "description", "Changed scope"),
        "deal_value": (case.deal, "value", 2_000_000),
        "report_language": (case.deal, "report_language", "en"),
    }
    if mutation == "add_document":
        db.add(Document(deal_id=case.deal.id, filename="new.txt", file_path="fixture/new.txt",
                        mime_type="text/plain", file_size=10, raw_text="New evidence",
                        status=DocumentStatus.processed))
    elif mutation == "delete_document":
        db.delete(doc)
    else:
        target, field, value = changes[mutation]
        setattr(target, field, value)
    db.commit()
    with pytest.raises(CheckpointError):
        validate_resume(db, case.deal.id)


def test_legacy_run_is_never_adopted_automatically(db, checkpoint_case):
    case = checkpoint_case
    case.runs["intake"].input_hash = None
    db.commit()
    with pytest.raises(CheckpointError):
        validate_resume(db, case.deal.id)
    with pytest.raises(CheckpointError):
        orchestrator.run_deal_analysis_pipeline(case.deal.id, db, provider=FakeLLMProvider(), resume=True)
    db.refresh(case.runs["intake"])
    assert case.runs["intake"].input_hash is None


def test_verified_legacy_adoption_records_fingerprint_and_preserves_stages(db, checkpoint_case):
    case = checkpoint_case
    case.runs["intake"].input_hash = None
    db.commit()
    before = {key: run.id for key, run in case.runs.items()}
    # Maintenance has separately proved queue inactivity; hold its deal lock.
    db.query(Deal).filter_by(id=case.deal.id).with_for_update().one()
    plan = adopt_legacy_checkpoint(db, case.deal.id,
                                  expected_intake_started_at=case.start, expected_document_count=2)
    db.commit()
    assert plan.completed == PREFIX
    assert case.runs["intake"].input_hash == case.fingerprint
    assert {key: run.id for key, run in case.runs.items()} == before


@pytest.mark.parametrize("mismatch", ["created_after", "updated_after", "missing_updated", "deal_metadata", "wrong_start", "wrong_count", "unlocked", "existing_hash"])
def test_legacy_adoption_rejects_changed_or_unverifiable_inventory(db, checkpoint_case, mismatch):
    case = checkpoint_case
    case.runs["intake"].input_hash = None
    expected_start, expected_count = case.start, 2
    if mismatch == "created_after":
        case.docs[0].created_at = case.start + timedelta(seconds=1)
    elif mismatch == "updated_after":
        case.docs[0].updated_at = case.start + timedelta(seconds=1)
    elif mismatch == "missing_updated":
        case.docs[0].updated_at = None
    elif mismatch == "deal_metadata":
        case.deal.title = "Edited after the recorded intake"
    elif mismatch == "wrong_start":
        expected_start += timedelta(seconds=1)
    elif mismatch == "wrong_count":
        expected_count = 3
    elif mismatch == "unlocked":
        case.deal.status = DealStatus.draft
    elif mismatch == "existing_hash":
        case.runs["intake"].input_hash = "a" * 64
    db.commit()
    original_hash = case.runs["intake"].input_hash
    with pytest.raises(CheckpointError):
        adopt_legacy_checkpoint(db, case.deal.id, expected_intake_started_at=expected_start,
                               expected_document_count=expected_count)
    assert case.runs["intake"].input_hash == original_hash


@pytest.mark.parametrize("defect", ["missing", "duplicate", "foreign_document", "missing_type", "blank_type"])
def test_resume_requires_exact_valid_routing_coverage(db, checkpoint_case, defect):
    case = checkpoint_case
    row = db.query(AgentFinding).filter_by(deal_id=case.deal.id, agent_name="document_router").first()
    if defect == "missing":
        db.delete(row)
    elif defect == "duplicate":
        db.add(AgentFinding(deal_id=case.deal.id, document_id=row.document_id, agent_name="document_router",
                            category="document_classification", title="Duplicate", description="Duplicate route",
                            severity=Severity.low, structured_payload_json=row.structured_payload_json))
    elif defect == "foreign_document":
        other = Deal(workspace_id=case.deal.workspace_id, title="Other deal")
        db.add(other)
        db.flush()
        foreign = Document(deal_id=other.id, filename="other.txt", file_path="other/object",
                           mime_type="text/plain", file_size=1, raw_text="Other", status=DocumentStatus.processed)
        db.add(foreign)
        db.flush()
        row.document_id = foreign.id
    else:
        row.structured_payload_json = {"document_type": "   "} if defect == "blank_type" else {}
    db.commit()
    with pytest.raises(CheckpointError):
        validate_resume(db, case.deal.id)


def test_failed_legacy_adoption_restores_missing_fingerprint(db, checkpoint_case):
    case = checkpoint_case
    case.runs["intake"].input_hash = None
    row = db.query(AgentFinding).filter_by(deal_id=case.deal.id, agent_name="document_router").first()
    db.delete(row)
    db.commit()
    with pytest.raises(CheckpointError):
        adopt_legacy_checkpoint(db, case.deal.id, expected_intake_started_at=case.start,
                               expected_document_count=2)
    assert case.runs["intake"].input_hash is None


def test_old_completed_finance_does_not_count_as_current_checkpoint(db, checkpoint_case):
    case = checkpoint_case
    run = case.runs["financial_analysis"]
    run.status = AgentRunStatus.completed
    run.started_at = case.start - timedelta(days=1)
    run.completed_at = run.started_at + timedelta(seconds=10)
    db.commit()
    assert validate_resume(db, case.deal.id).completed == PREFIX


def test_a_new_intake_cannot_reuse_completed_stages_from_older_run(db, checkpoint_case):
    case = checkpoint_case
    started = case.start + timedelta(minutes=10)
    db.add(AgentRun(deal_id=case.deal.id, agent_name="intake", status=AgentRunStatus.completed,
                    started_at=started, completed_at=started + timedelta(seconds=1), input_hash=case.fingerprint))
    db.commit()
    plan = validate_resume(db, case.deal.id)
    assert plan.completed == ("intake",)
    assert plan.classifications == []


def test_resuming_finance_skips_first_six_stages_and_preserves_their_results(db, checkpoint_case, monkeypatch):
    case = checkpoint_case
    names = [name for _, name in STAGES[:6]]
    before = run_snapshot(db, case.deal.id, names)
    for function in PREFIX_FUNCTIONS:
        monkeypatch.setattr(orchestrator, function, fail_if_called)
    result = orchestrator.run_deal_analysis_pipeline(case.deal.id, db, provider=FakeLLMProvider(), resume=True)
    assert result["completed"], result
    assert all(result["stages"][key]["resumed_from_checkpoint"] for key in PREFIX)
    assert run_snapshot(db, case.deal.id, names) == before
    assert db.get(AgentFinding, case.preserved.id).title == "Preserved contract result"
    assert db.query(AgentRun).filter_by(deal_id=case.deal.id, agent_name="financial_analysis").one().status == AgentRunStatus.completed
    assert db.query(Report).filter_by(deal_id=case.deal.id).count() > 0
    db.refresh(case.deal)
    assert case.deal.status == DealStatus.reviewed


def test_failed_resumed_finance_blocks_publication_and_keeps_previous_report(db, checkpoint_case, monkeypatch):
    case = checkpoint_case
    before = run_snapshot(db, case.deal.id, [name for _, name in STAGES[:6]])
    for function in (*PREFIX_FUNCTIONS, "_stage_red_flag_aggregation", "_stage_report_generation"):
        monkeypatch.setattr(orchestrator, function, fail_if_called)

    class FailedFinance(FakeLLMProvider):
        def complete(self, prompt, max_tokens=2048):
            if "ANALYZE FINANCIAL STATEMENTS" in prompt.upper():
                return "{broken"
            return super().complete(prompt, max_tokens)

    result = orchestrator.run_deal_analysis_pipeline(case.deal.id, db, provider=FailedFinance(), resume=True)
    assert not result["completed"]
    for key in ("financial_analysis", "red_flag_aggregation", "report_generation"):
        assert "error" in result["stages"][key]
    assert run_snapshot(db, case.deal.id, [name for _, name in STAGES[:6]]) == before
    assert db.get(Report, case.report.id).content == "Do not replace on failure"
    assert db.get(AgentFinding, case.preserved.id).title == "Preserved contract result"
    db.refresh(case.deal)
    assert case.deal.status == DealStatus.draft


def test_normal_intake_writes_fingerprint_before_later_failure(db, test_deal):
    doc = Document(deal_id=test_deal.id, filename="financial_statements.txt", file_path="fixture/financial.txt",
                   mime_type="text/plain", file_size=len(TEXT), status=DocumentStatus.processed,
                   raw_text=TEXT, language="en")
    db.add(doc)
    db.commit()

    class FailedFinance(FakeLLMProvider):
        def complete(self, prompt, max_tokens=2048):
            if "ANALYZE FINANCIAL STATEMENTS" in prompt.upper():
                return "{broken"
            return super().complete(prompt, max_tokens)

    result = orchestrator.run_deal_analysis_pipeline(test_deal.id, db, provider=FailedFinance())
    assert not result["completed"]
    assert "error" in result["stages"]["financial_analysis"]
    intake = db.query(AgentRun).filter_by(deal_id=test_deal.id, agent_name="intake").one()
    assert intake.input_hash == corpus_fingerprint(db, test_deal.id)[0]
    assert validate_resume(db, test_deal.id).completed == PREFIX
