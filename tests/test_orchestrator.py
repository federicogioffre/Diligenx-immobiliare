"""Tests for the multi-agent orchestration pipeline.

Covers:
- Return structure and stage key completeness
- AgentRun records created, timestamped, and in the correct status
- Idempotency: re-running produces the same row counts (no duplicates)
- Deal status transitions (reviewing → reviewed / draft)
- Per-stage outputs: classifications, clause findings, red flags,
  open questions, missing documents, and report
- Stage-failure isolation: one failing stage does not abort the pipeline;
  its AgentRun is marked *failed* and subsequent stages still execute
- Edge cases: no documents, multiple documents, deal not found
"""
import pytest
from sqlalchemy.orm import Session

from app.models.deal import Deal, DealStatus
from app.models.document import Document, DocumentStatus
from app.models.clause_finding import ClauseFinding
from app.models.red_flag import RedFlag, Severity
from app.models.report import Report, ReportStatus
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.agent_finding import AgentFinding
from app.models.open_question import OpenQuestion
from app.models.missing_document import MissingDocument
from packages.agents.deal_analysis_agent import FakeLLMProvider, set_llm_provider
from packages.agents.orchestrator import (
    run_deal_analysis_pipeline,
    AGENT_INTAKE,
    AGENT_ROUTER,
    AGENT_SPECIALIST,
    AGENT_CORPORATE,
    AGENT_CORPORATE_INTRO,
    AGENT_RED_FLAG,
    AGENT_REPORT,
)

# ── Module-level constants ─────────────────────────────────────────────────

_ALL_STAGES = {
    "intake",
    "document_routing",
    "specialist_analysis",
    "corporate_analysis",
    "corporate_intro_extraction",
    "red_flag_aggregation",
    "report_generation",
}

_ALL_AGENT_NAMES = {
    AGENT_INTAKE, AGENT_ROUTER, AGENT_SPECIALIST,
    AGENT_CORPORATE, AGENT_CORPORATE_INTRO,
    AGENT_RED_FLAG, AGENT_REPORT,
}


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def use_fake_llm():
    """Inject FakeLLMProvider globally for every test in this module."""
    set_llm_provider(FakeLLMProvider())
    yield
    set_llm_provider(None)


@pytest.fixture
def processed_doc(db: Session, test_deal: Deal) -> Document:
    """Fully processed contract document (simulates post-ingestion state)."""
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
            "TERMINATION: Either party may terminate this agreement with 30 days "
            "written notice.\n\n"
            "LIABILITY: In no event shall either party be liable for indirect, "
            "incidental, or consequential damages.\n\n"
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


@pytest.fixture
def failing_red_flag_llm():
    """LLM that raises on the red-flag prompt but succeeds for every other stage."""
    class FailOnRedFlags(FakeLLMProvider):
        def complete(self, prompt: str, max_tokens: int = 2048) -> str:
            p = prompt.upper()
            # RED_FLAG_DETECTION_PROMPT contains "RED FLAGS" but not "DUE DILIGENCE".
            # REPORT_GENERATION_PROMPT contains both "DUE DILIGENCE" and "RED FLAGS".
            if "RED FLAGS" in p and "DUE DILIGENCE" not in p:
                raise RuntimeError("Simulated red-flag LLM failure")
            return super().complete(prompt, max_tokens)

    return FailOnRedFlags()


# ── 1. Return-value structure ──────────────────────────────────────────────

class TestPipelineStructure:

    def test_returns_dict_with_required_keys(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert "deal_id" in result
        assert "stages" in result
        assert "completed" in result

    def test_deal_id_matches_input(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["deal_id"] == test_deal.id

    def test_all_stage_keys_present(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert set(result["stages"].keys()) == _ALL_STAGES

    def test_completed_true_when_all_stages_succeed(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["completed"] is True

    def test_deal_not_found_raises_value_error(self, db):
        with pytest.raises(ValueError, match="Deal 99999 not found"):
            run_deal_analysis_pipeline(99999, db)


# ── 2. AgentRun records ────────────────────────────────────────────────────

class TestAgentRunRecords:

    def test_exactly_seven_agent_runs_created(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        runs = db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).all()
        assert len(runs) == 7

    def test_all_seven_agent_names_present(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        names = {
            r.agent_name
            for r in db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).all()
        }
        assert names == _ALL_AGENT_NAMES

    def test_all_agent_runs_completed_on_success(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        for run in db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).all():
            assert run.status == AgentRunStatus.completed, (
                f"Stage '{run.agent_name}' expected completed, got {run.status}"
            )

    def test_agent_runs_have_started_at(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        for run in db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).all():
            assert run.started_at is not None, f"Stage '{run.agent_name}' missing started_at"

    def test_agent_runs_have_completed_at(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        for run in db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).all():
            assert run.completed_at is not None, f"Stage '{run.agent_name}' missing completed_at"

    def test_completed_at_after_started_at(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        for run in db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).all():
            assert run.completed_at >= run.started_at, (
                f"Stage '{run.agent_name}': completed_at before started_at"
            )

    def test_agent_runs_linked_to_correct_deal(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        for run in db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).all():
            assert run.deal_id == test_deal.id


# ── 3. Deal status transitions ────────────────────────────────────────────

class TestDealStatus:

    def test_deal_status_reviewed_after_full_success(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        db.refresh(test_deal)
        assert test_deal.status == DealStatus.reviewed

    def test_deal_status_draft_when_a_stage_fails(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        run_deal_analysis_pipeline(test_deal.id, db, provider=failing_red_flag_llm)
        db.refresh(test_deal)
        assert test_deal.status == DealStatus.draft


# ── 4. Stage-level outputs ────────────────────────────────────────────────

class TestIntakeStage:

    def test_intake_counts_documents(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        intake = result["stages"]["intake"]
        assert intake["total_documents"] == 1
        assert intake["processed_documents"] == 1

    def test_intake_creates_missing_document_rows(self, db, test_deal, processed_doc):
        """Checklist items not covered by the data room should appear as
        MissingDocument rows keyed by the firm's checklist codes (A.1, ...)."""
        from packages.agents.dd_checklist import CHECKLIST
        run_deal_analysis_pipeline(test_deal.id, db)
        missing = (
            db.query(MissingDocument)
            .filter(MissingDocument.deal_id == test_deal.id)
            .all()
        )
        # A single service-agreement doc covers very few of the ~80 items,
        # so the vast majority must be flagged as missing.
        assert len(missing) > 50
        keys = {m.document_category for m in missing}
        # Firm-coded keys, not the old broad categories.
        assert "A.1" in keys       # Visure Registro Imprese
        assert "C.1" in keys       # Bilanci
        # Every key must belong to the checklist.
        all_keys = {item["key"] for item in CHECKLIST}
        assert keys <= all_keys

    def test_intake_missing_count_matches_result(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        db_count = (
            db.query(MissingDocument)
            .filter(MissingDocument.deal_id == test_deal.id)
            .count()
        )
        assert result["stages"]["intake"]["missing_categories"] == db_count

    def test_intake_no_documents(self, db, test_deal):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["stages"]["intake"]["total_documents"] == 0
        assert result["stages"]["intake"]["processed_documents"] == 0


class TestDocumentRoutingStage:

    def test_routing_classifies_one_document(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["stages"]["document_routing"]["documents_classified"] == 1

    def test_routing_returns_classification_list(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        classifications = result["stages"]["document_routing"]["classifications"]
        assert len(classifications) == 1
        c = classifications[0]
        assert c["document_id"] == processed_doc.id
        assert c["document_type"] == "contract"   # FakeLLM always returns "contract"
        assert 0.0 <= c["confidence"] <= 1.0

    def test_routing_persists_agent_finding(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        findings = (
            db.query(AgentFinding)
            .filter(
                AgentFinding.deal_id == test_deal.id,
                AgentFinding.agent_name == AGENT_ROUTER,
            )
            .all()
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.category == "document_classification"
        assert f.document_id == processed_doc.id
        assert "contract" in f.title

    def test_routing_structured_payload_stored(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        finding = (
            db.query(AgentFinding)
            .filter(AgentFinding.agent_name == AGENT_ROUTER)
            .first()
        )
        assert finding.structured_payload_json is not None
        assert "document_type" in finding.structured_payload_json


class TestSpecialistStage:

    def test_specialist_extracts_clause_findings(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["stages"]["specialist_analysis"]["clause_findings_count"] > 0

    def test_specialist_count_matches_db(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        db_count = (
            db.query(ClauseFinding)
            .filter(ClauseFinding.document_id == processed_doc.id)
            .count()
        )
        assert result["stages"]["specialist_analysis"]["clause_findings_count"] == db_count

    def test_specialist_counts_one_contract_doc(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["stages"]["specialist_analysis"]["contract_documents"] == 1


class TestCorporateAnalysisStage:

    def test_corporate_stage_present_in_result(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert "corporate_analysis" in result["stages"]

    def test_corporate_stage_no_error(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert "error" not in result["stages"]["corporate_analysis"]

    def test_corporate_agent_run_created(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        run = (
            db.query(AgentRun)
            .filter(
                AgentRun.deal_id == test_deal.id,
                AgentRun.agent_name == AGENT_CORPORATE,
            )
            .first()
        )
        assert run is not None
        assert run.status == AgentRunStatus.completed

    def test_corporate_no_governance_docs_zero_findings(self, db, test_deal, processed_doc):
        """service_agreement.txt is not a corporate governance document."""
        result = run_deal_analysis_pipeline(test_deal.id, db)
        corp = result["stages"]["corporate_analysis"]
        assert corp["documents_analyzed"] == 0
        assert corp["agent_findings_count"] == 0

    def test_corporate_with_governance_document(self, db, test_deal):
        """A document with corporate governance keywords is analysed."""
        doc = Document(
            deal_id=test_deal.id,
            filename="articles_of_association.txt",
            file_path="/tmp/articles_of_association.txt",
            mime_type="text/plain",
            file_size=1500,
            status=DocumentStatus.processed,
            raw_text=(
                "ARTICLES OF ASSOCIATION\n\n"
                "Article 1: The company is established under the laws of Italy.\n"
                "Article 2: The board of directors shall consist of five members.\n"
                "Article 3: Shareholders shall meet annually."
            ),
            language="en",
        )
        db.add(doc)
        db.commit()

        result = run_deal_analysis_pipeline(test_deal.id, db)
        corp = result["stages"]["corporate_analysis"]
        assert corp["documents_analyzed"] >= 1
        assert corp["agent_findings_count"] >= 1


class TestRedFlagStage:

    def test_red_flag_stage_creates_red_flags(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["stages"]["red_flag_aggregation"]["red_flags_count"] > 0

    def test_red_flag_count_matches_db(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        db_count = (
            db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count()
        )
        assert result["stages"]["red_flag_aggregation"]["red_flags_count"] == db_count

    def test_open_questions_created_for_high_severity_flags(
        self, db, test_deal, processed_doc
    ):
        """Every high-severity red flag should generate an open question."""
        run_deal_analysis_pipeline(test_deal.id, db)
        high_flags = (
            db.query(RedFlag)
            .filter(
                RedFlag.deal_id == test_deal.id,
                RedFlag.severity == Severity.high,
            )
            .count()
        )
        questions = (
            db.query(OpenQuestion)
            .filter(
                OpenQuestion.deal_id == test_deal.id,
                OpenQuestion.agent_name == AGENT_RED_FLAG,
            )
            .count()
        )
        assert questions == high_flags

    def test_open_question_count_in_result(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        db_count = (
            db.query(OpenQuestion)
            .filter(OpenQuestion.deal_id == test_deal.id)
            .count()
        )
        assert result["stages"]["red_flag_aggregation"]["open_questions_count"] == db_count


class TestReportStage:

    def test_report_generated_in_db(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        report = db.query(Report).filter(Report.deal_id == test_deal.id).first()
        assert report is not None
        assert report.status == ReportStatus.completed
        assert report.content and len(report.content) > 0

    def test_report_stage_result_has_report_id(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        rpt = result["stages"]["report_generation"]
        assert "report_id" in rpt
        assert isinstance(rpt["report_id"], int)

    def test_report_stage_result_has_markdown_length(self, db, test_deal, processed_doc):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["stages"]["report_generation"]["markdown_length"] > 0


# ── 5. Idempotency ────────────────────────────────────────────────────────

class TestIdempotency:

    def test_clause_findings_stable_across_two_runs(self, db, test_deal, processed_doc):
        r1 = run_deal_analysis_pipeline(test_deal.id, db)
        r2 = run_deal_analysis_pipeline(test_deal.id, db)
        assert (
            r1["stages"]["specialist_analysis"]["clause_findings_count"]
            == r2["stages"]["specialist_analysis"]["clause_findings_count"]
        )

    def test_red_flags_stable_across_two_runs(self, db, test_deal, processed_doc):
        r1 = run_deal_analysis_pipeline(test_deal.id, db)
        r2 = run_deal_analysis_pipeline(test_deal.id, db)
        assert (
            r1["stages"]["red_flag_aggregation"]["red_flags_count"]
            == r2["stages"]["red_flag_aggregation"]["red_flags_count"]
        )

    def test_agent_run_count_stable(self, db, test_deal, processed_doc):
        """Re-running must not accumulate extra AgentRun rows."""
        run_deal_analysis_pipeline(test_deal.id, db)
        c1 = db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).count()
        run_deal_analysis_pipeline(test_deal.id, db)
        c2 = db.query(AgentRun).filter(AgentRun.deal_id == test_deal.id).count()
        assert c1 == c2

    def test_agent_findings_stable(self, db, test_deal, processed_doc):
        """Routing findings must not double-up on re-run."""
        run_deal_analysis_pipeline(test_deal.id, db)
        c1 = db.query(AgentFinding).filter(AgentFinding.deal_id == test_deal.id).count()
        run_deal_analysis_pipeline(test_deal.id, db)
        c2 = db.query(AgentFinding).filter(AgentFinding.deal_id == test_deal.id).count()
        assert c1 == c2

    def test_missing_documents_stable(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        c1 = db.query(MissingDocument).filter(MissingDocument.deal_id == test_deal.id).count()
        run_deal_analysis_pipeline(test_deal.id, db)
        c2 = db.query(MissingDocument).filter(MissingDocument.deal_id == test_deal.id).count()
        assert c1 == c2

    def test_open_questions_stable(self, db, test_deal, processed_doc):
        """Open questions from the pipeline must not accumulate."""
        run_deal_analysis_pipeline(test_deal.id, db)
        c1 = (
            db.query(OpenQuestion)
            .filter(
                OpenQuestion.deal_id == test_deal.id,
                OpenQuestion.agent_name == AGENT_RED_FLAG,
            )
            .count()
        )
        run_deal_analysis_pipeline(test_deal.id, db)
        c2 = (
            db.query(OpenQuestion)
            .filter(
                OpenQuestion.deal_id == test_deal.id,
                OpenQuestion.agent_name == AGENT_RED_FLAG,
            )
            .count()
        )
        assert c1 == c2

    def test_only_one_report_row_after_two_runs(self, db, test_deal, processed_doc):
        run_deal_analysis_pipeline(test_deal.id, db)
        run_deal_analysis_pipeline(test_deal.id, db)
        count = db.query(Report).filter(Report.deal_id == test_deal.id).count()
        assert count == 1


# ── 6. Stage-failure isolation ────────────────────────────────────────────

class TestFailureIsolation:
    """A single failing stage must not abort the rest of the pipeline."""

    def test_pipeline_does_not_raise_on_stage_failure(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        # Must not raise any exception
        result = run_deal_analysis_pipeline(
            test_deal.id, db, provider=failing_red_flag_llm
        )
        assert result is not None

    def test_failed_stage_has_error_key(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        result = run_deal_analysis_pipeline(
            test_deal.id, db, provider=failing_red_flag_llm
        )
        assert "error" in result["stages"]["red_flag_aggregation"]

    def test_failed_stage_agent_run_status_is_failed(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        run_deal_analysis_pipeline(test_deal.id, db, provider=failing_red_flag_llm)
        run = (
            db.query(AgentRun)
            .filter(
                AgentRun.deal_id == test_deal.id,
                AgentRun.agent_name == AGENT_RED_FLAG,
            )
            .first()
        )
        assert run is not None
        assert run.status == AgentRunStatus.failed

    def test_failed_agent_run_has_error_message(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        run_deal_analysis_pipeline(test_deal.id, db, provider=failing_red_flag_llm)
        run = (
            db.query(AgentRun)
            .filter(
                AgentRun.deal_id == test_deal.id,
                AgentRun.agent_name == AGENT_RED_FLAG,
            )
            .first()
        )
        assert run.error_message is not None
        assert len(run.error_message) > 0

    def test_stages_before_failure_are_completed(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        result = run_deal_analysis_pipeline(
            test_deal.id, db, provider=failing_red_flag_llm
        )
        assert "error" not in result["stages"]["intake"]
        assert "error" not in result["stages"]["document_routing"]
        assert "error" not in result["stages"]["specialist_analysis"]
        assert "error" not in result["stages"]["corporate_analysis"]

    def test_report_stage_still_runs_after_red_flag_failure(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        """Stage 6 must execute even though Stage 5 failed."""
        result = run_deal_analysis_pipeline(
            test_deal.id, db, provider=failing_red_flag_llm
        )
        rpt = result["stages"]["report_generation"]
        assert "error" not in rpt
        assert "report_id" in rpt

    def test_completed_is_false_on_any_failure(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        result = run_deal_analysis_pipeline(
            test_deal.id, db, provider=failing_red_flag_llm
        )
        assert result["completed"] is False

    def test_prior_agent_runs_stay_completed_after_later_stage_fails(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        run_deal_analysis_pipeline(test_deal.id, db, provider=failing_red_flag_llm)
        for name in (AGENT_INTAKE, AGENT_ROUTER, AGENT_SPECIALIST, AGENT_CORPORATE):
            run = (
                db.query(AgentRun)
                .filter(
                    AgentRun.deal_id == test_deal.id,
                    AgentRun.agent_name == name,
                )
                .first()
            )
            assert run is not None
            assert run.status == AgentRunStatus.completed, (
                f"Expected {name} to be completed, got {run.status}"
            )

    def test_failed_red_flag_stage_preserves_prior_red_flags(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        """Regression: a red-flag stage deletes prior RedFlag rows before
        regenerating them. If it then fails, the transactional rollback must
        restore the previous run's rows — otherwise a transient LLM error
        would silently wipe a deal's red flags and yield a falsely-clean
        report."""
        # First run succeeds and commits red flags.
        run_deal_analysis_pipeline(test_deal.id, db)
        before = db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count()
        assert before > 0, "precondition: first run should produce red flags"

        # Second run: red-flag aggregation deletes the rows then fails.
        result = run_deal_analysis_pipeline(
            test_deal.id, db, provider=failing_red_flag_llm
        )
        assert "error" in result["stages"]["red_flag_aggregation"]

        after = db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count()
        assert after == before, (
            f"red flags must survive a failed aggregation "
            f"(had {before}, now {after})"
        )

    def test_clause_findings_present_despite_red_flag_failure(
        self, db, test_deal, processed_doc, failing_red_flag_llm
    ):
        """Clause extraction (stage 3) must have run and committed its data."""
        run_deal_analysis_pipeline(test_deal.id, db, provider=failing_red_flag_llm)
        count = (
            db.query(ClauseFinding)
            .filter(ClauseFinding.document_id == processed_doc.id)
            .count()
        )
        assert count > 0


# ── 7. Edge cases ─────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_no_documents_pipeline_completes_without_error(self, db, test_deal):
        """A deal with no documents must run all stages cleanly."""
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["completed"] is True
        assert set(result["stages"].keys()) == _ALL_STAGES
        for stage_name, stage_result in result["stages"].items():
            assert "error" not in stage_result, (
                f"Stage '{stage_name}' errored with no documents: {stage_result}"
            )

    def test_no_documents_zero_clause_findings(self, db, test_deal):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["stages"]["specialist_analysis"]["clause_findings_count"] == 0
        assert result["stages"]["specialist_analysis"]["contract_documents"] == 0

    def test_no_documents_zero_classifications(self, db, test_deal):
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["stages"]["document_routing"]["documents_classified"] == 0

    def test_multiple_documents_all_classified(self, db, test_deal):
        """Three processed documents → three classifications in routing."""
        for i in range(3):
            doc = Document(
                deal_id=test_deal.id,
                filename=f"contract_{i}.txt",
                file_path=f"/tmp/contract_{i}.txt",
                mime_type="text/plain",
                file_size=500,
                status=DocumentStatus.processed,
                raw_text=f"SERVICE AGREEMENT {i}. Either party may terminate with 30 days notice.",
            )
            db.add(doc)
        db.commit()

        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["stages"]["document_routing"]["documents_classified"] == 3

    def test_multiple_documents_all_clauses_extracted(self, db, test_deal):
        """All three contract documents should have clauses extracted."""
        for i in range(3):
            doc = Document(
                deal_id=test_deal.id,
                filename=f"contract_{i}.txt",
                file_path=f"/tmp/contract_{i}.txt",
                mime_type="text/plain",
                file_size=500,
                status=DocumentStatus.processed,
                raw_text=f"SERVICE AGREEMENT {i}. Either party may terminate with 30 days written notice. Liability shall not exceed the total contract value.",
            )
            db.add(doc)
        db.commit()

        result = run_deal_analysis_pipeline(test_deal.id, db)
        # FakeLLM returns 2 clauses per doc → 3 × 2 = 6
        assert result["stages"]["specialist_analysis"]["clause_findings_count"] == 6
        assert result["stages"]["specialist_analysis"]["contract_documents"] == 3

    def test_pending_documents_not_classified(self, db, test_deal):
        """Documents still in *pending* status must be skipped by the router."""
        doc = Document(
            deal_id=test_deal.id,
            filename="pending_contract.txt",
            file_path="/tmp/pending_contract.txt",
            mime_type="text/plain",
            file_size=200,
            status=DocumentStatus.pending,   # not processed
            raw_text="Agreement between parties.",
        )
        db.add(doc)
        db.commit()

        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert result["stages"]["document_routing"]["documents_classified"] == 0

    def test_pipeline_uses_injected_provider(self, db, test_deal, processed_doc):
        """Provider kwarg is forwarded to all LLM calls (no global singleton needed)."""
        explicit_provider = FakeLLMProvider()
        result = run_deal_analysis_pipeline(
            test_deal.id, db, provider=explicit_provider
        )
        assert result["completed"] is True
