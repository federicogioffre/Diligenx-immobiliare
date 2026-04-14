"""Tests for ContractAgent — clause extraction from contract documents.

Covers:
- Clause extraction: ClauseFinding rows created with correct fields
- Invalid clause type values coerced to 'other'
- AgentFinding summary: one per document, correct category/fields/payload
- Return value shape and key counts
- Document filtering via contract_document_ids
- Idempotency: no accumulation on re-run
- AgentRun lifecycle: created, timestamped, completed/failed
- Edge cases: deal not found, empty docs, no documents, convenience wrapper
"""
import json
import pytest
from sqlalchemy.orm import Session

from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from app.models.clause_finding import ClauseFinding, ClauseType
from app.models.agent_finding import AgentFinding
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.red_flag import Severity
from packages.agents.contract_agent import (
    ContractAgent,
    run_contract_analysis,
    AGENT_NAME,
)
from packages.agents.deal_analysis_agent import FakeLLMProvider, set_llm_provider

# ── Module-level fixtures ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def use_fake_llm():
    """Inject FakeLLMProvider globally for every test in this module."""
    set_llm_provider(FakeLLMProvider())
    yield
    set_llm_provider(None)


# ── Test helpers ────────────────────────────────────────────────────────────

def _make_doc(
    db: Session,
    deal: Deal,
    *,
    filename: str = "service_agreement.txt",
    raw_text: str = (
        "SERVICE AGREEMENT\n\n"
        "TERMINATION: Either party may terminate with 30 days written notice.\n"
        "LIABILITY: Liability shall not exceed the total contract value.\n"
    ),
    status: DocumentStatus = DocumentStatus.processed,
    file_size: int = 1024,
) -> Document:
    doc = Document(
        deal_id=deal.id,
        filename=filename,
        file_path=f"/tmp/{filename}",
        mime_type="text/plain",
        file_size=file_size,
        status=status,
        raw_text=raw_text,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _clause_findings(db: Session, doc: Document) -> list[ClauseFinding]:
    return (
        db.query(ClauseFinding)
        .filter(ClauseFinding.document_id == doc.id)
        .all()
    )


def _agent_findings(db: Session, deal: Deal) -> list[AgentFinding]:
    return (
        db.query(AgentFinding)
        .filter(
            AgentFinding.deal_id == deal.id,
            AgentFinding.agent_name == AGENT_NAME,
        )
        .all()
    )


def _agent_runs(db: Session, deal: Deal) -> list[AgentRun]:
    return (
        db.query(AgentRun)
        .filter(
            AgentRun.deal_id == deal.id,
            AgentRun.agent_name == AGENT_NAME,
        )
        .all()
    )


# ── 1. Clause extraction ───────────────────────────────────────────────────

class TestClauseExtraction:
    """ClauseFinding rows are persisted with correct field values."""

    def test_clause_findings_created(self, db, test_deal):
        """FakeLLM returns 2 clauses → 2 ClauseFinding rows in DB."""
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        assert len(_clause_findings(db, doc)) == 2

    def test_clause_findings_linked_to_document(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        for cf in _clause_findings(db, doc):
            assert cf.document_id == doc.id

    def test_clause_types_are_valid_enum_values(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        valid = {ct.value for ct in ClauseType}
        for cf in db.query(ClauseFinding).all():
            assert cf.clause_type.value in valid

    def test_clause_termination_type_stored(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        types = {cf.clause_type for cf in _clause_findings(db, doc)}
        assert ClauseType.termination in types

    def test_clause_liability_type_stored(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        types = {cf.clause_type for cf in _clause_findings(db, doc)}
        assert ClauseType.liability in types

    def test_clause_title_stored(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        titles = [cf.title for cf in _clause_findings(db, doc)]
        assert any("Termination" in t for t in titles)

    def test_clause_content_stored(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        for cf in _clause_findings(db, doc):
            assert cf.content  # non-empty

    def test_clause_page_number_stored(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        for cf in _clause_findings(db, doc):
            assert cf.page_number is not None

    def test_clause_confidence_stored(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        for cf in _clause_findings(db, doc):
            assert cf.confidence is not None
            assert 0.0 <= cf.confidence <= 1.0

    def test_invalid_clause_type_coerced_to_other(self, db, test_deal):
        """Unrecognised clause_type values must be normalised to 'other'."""

        class LLMWithBadType(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                p = prompt.upper()
                if "EXTRACT CLAUSES" in p:
                    return json.dumps([{
                        "clause_type": "TOTALLY_INVALID",
                        "title": "Unknown Clause",
                        "content": "Either party may terminate with 30 days written notice.",
                        "page_number": 1,
                        "confidence": 0.75,
                    }])
                return super().complete(prompt, max_tokens)

        doc = _make_doc(db, test_deal)
        ContractAgent(provider=LLMWithBadType()).run(test_deal.id, db)
        findings = _clause_findings(db, doc)
        assert len(findings) == 1
        assert findings[0].clause_type == ClauseType.other

    def test_multiple_documents_all_extracted(self, db, test_deal):
        """FakeLLM returns 2 clauses per doc → 3 × 2 = 6 ClauseFindings."""
        docs = [_make_doc(db, test_deal, filename=f"contract_{i}.txt") for i in range(3)]
        ContractAgent().run(test_deal.id, db)
        total = sum(len(_clause_findings(db, d)) for d in docs)
        assert total == 6


# ── 2. AgentFinding summaries ──────────────────────────────────────────────

class TestAgentFindingSummaries:
    """One AgentFinding summary is created per document analysed."""

    def test_one_agent_finding_per_document(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        assert len(_agent_findings(db, test_deal)) == 1

    def test_multiple_docs_multiple_findings(self, db, test_deal):
        for i in range(3):
            _make_doc(db, test_deal, filename=f"contract_{i}.txt")
        ContractAgent().run(test_deal.id, db)
        assert len(_agent_findings(db, test_deal)) == 3

    def test_agent_finding_category(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        f = _agent_findings(db, test_deal)[0]
        assert f.category == "clause_extraction_summary"

    def test_agent_finding_agent_name(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        f = _agent_findings(db, test_deal)[0]
        assert f.agent_name == AGENT_NAME

    def test_agent_finding_title_contains_clause_count(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        f = _agent_findings(db, test_deal)[0]
        assert "2" in f.title  # FakeLLM returns 2 clauses

    def test_agent_finding_title_contains_filename(self, db, test_deal):
        _make_doc(db, test_deal, filename="my_contract.txt")
        ContractAgent().run(test_deal.id, db)
        f = _agent_findings(db, test_deal)[0]
        assert "my_contract.txt" in f.title

    def test_agent_finding_severity_low(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        f = _agent_findings(db, test_deal)[0]
        assert f.severity == Severity.low

    def test_agent_finding_document_id_linked(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        f = _agent_findings(db, test_deal)[0]
        assert f.document_id == doc.id

    def test_agent_finding_deal_id(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        f = _agent_findings(db, test_deal)[0]
        assert f.deal_id == test_deal.id

    def test_agent_finding_payload_clause_count(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload is not None
        assert payload["clause_count"] == 2

    def test_agent_finding_payload_clause_types(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert "clause_types" in payload
        assert isinstance(payload["clause_types"], list)
        assert len(payload["clause_types"]) > 0

    def test_agent_finding_payload_document_id(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload["document_id"] == doc.id

    def test_agent_finding_payload_filename(self, db, test_deal):
        _make_doc(db, test_deal, filename="agreement.txt")
        ContractAgent().run(test_deal.id, db)
        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload["filename"] == "agreement.txt"

    def test_agent_finding_clause_types_sorted(self, db, test_deal):
        """Clause types in the payload should be alphabetically sorted."""
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        types = payload["clause_types"]
        assert types == sorted(types)

    def test_no_text_doc_produces_no_agent_finding(self, db, test_deal):
        """Documents with empty raw_text are silently skipped (no summary)."""
        _make_doc(db, test_deal, raw_text="")
        ContractAgent().run(test_deal.id, db)
        assert len(_agent_findings(db, test_deal)) == 0


# ── 3. Return value ────────────────────────────────────────────────────────

class TestReturnValue:
    """run() returns a dict with the expected structure and counts."""

    def test_required_keys_present(self, db, test_deal):
        _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        for key in (
            "deal_id",
            "contract_documents",
            "clause_findings_count",
            "agent_findings_count",
            "clauses_by_document",
        ):
            assert key in result, f"Missing key: {key}"

    def test_deal_id_matches(self, db, test_deal):
        result = ContractAgent().run(test_deal.id, db)
        assert result["deal_id"] == test_deal.id

    def test_contract_documents_count(self, db, test_deal):
        _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        assert result["contract_documents"] == 1

    def test_clause_findings_count_matches_db(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        db_count = len(_clause_findings(db, doc))
        assert result["clause_findings_count"] == db_count

    def test_agent_findings_count_matches_db(self, db, test_deal):
        _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        db_count = len(_agent_findings(db, test_deal))
        assert result["agent_findings_count"] == db_count

    def test_clauses_by_document_is_list(self, db, test_deal):
        _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        assert isinstance(result["clauses_by_document"], list)

    def test_clauses_by_document_entry_keys(self, db, test_deal):
        _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        entry = result["clauses_by_document"][0]
        assert "document_id" in entry
        assert "filename" in entry
        assert "clause_count" in entry

    def test_clauses_by_document_clause_count(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        entry = next(
            e for e in result["clauses_by_document"] if e["document_id"] == doc.id
        )
        assert entry["clause_count"] == 2  # FakeLLM always returns 2

    def test_clauses_by_document_filename(self, db, test_deal):
        _make_doc(db, test_deal, filename="my_deal.txt")
        result = ContractAgent().run(test_deal.id, db)
        assert result["clauses_by_document"][0]["filename"] == "my_deal.txt"


# ── 4. Document filtering ──────────────────────────────────────────────────

class TestDocumentFiltering:
    """contract_document_ids restricts which documents are processed."""

    def test_specific_ids_filter_correctly(self, db, test_deal):
        """Only the document whose ID is in the set should be analysed."""
        doc_a = _make_doc(db, test_deal, filename="a.txt")
        doc_b = _make_doc(db, test_deal, filename="b.txt")
        ContractAgent().run(test_deal.id, db, contract_document_ids={doc_a.id})
        assert len(_clause_findings(db, doc_a)) == 2
        assert len(_clause_findings(db, doc_b)) == 0

    def test_empty_set_returns_zero_documents(self, db, test_deal):
        """An empty set means 'no documents to process'."""
        _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db, contract_document_ids=set())
        assert result["contract_documents"] == 0
        assert result["clause_findings_count"] == 0

    def test_empty_set_creates_no_clause_findings(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db, contract_document_ids=set())
        assert len(_clause_findings(db, doc)) == 0

    def test_none_analyses_all_processed_docs(self, db, test_deal):
        """Passing None (default) analyses every processed document."""
        for i in range(3):
            _make_doc(db, test_deal, filename=f"doc_{i}.txt")
        result = ContractAgent().run(test_deal.id, db, contract_document_ids=None)
        assert result["contract_documents"] == 3

    def test_pending_docs_skipped_regardless_of_id_set(self, db, test_deal):
        """Pending documents are excluded by the status filter even if their
        ID is in contract_document_ids."""
        doc = _make_doc(db, test_deal, status=DocumentStatus.pending)
        result = ContractAgent().run(
            test_deal.id, db, contract_document_ids={doc.id}
        )
        assert result["contract_documents"] == 0
        assert len(_clause_findings(db, doc)) == 0

    def test_doc_without_text_skipped(self, db, test_deal):
        """A document with empty raw_text is silently skipped."""
        doc = _make_doc(db, test_deal, raw_text="")
        result = ContractAgent().run(test_deal.id, db, contract_document_ids={doc.id})
        assert result["contract_documents"] == 0
        assert len(_clause_findings(db, doc)) == 0

    def test_whitespace_only_text_skipped(self, db, test_deal):
        """A document with only whitespace is treated as having no text."""
        doc = _make_doc(db, test_deal, raw_text="   \n\t  ")
        result = ContractAgent().run(test_deal.id, db, contract_document_ids={doc.id})
        assert result["contract_documents"] == 0


# ── 5. Idempotency ─────────────────────────────────────────────────────────

class TestIdempotency:
    """Re-running the agent produces stable counts — no row accumulation."""

    def test_clause_findings_stable_on_rerun(self, db, test_deal):
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        c1 = len(_clause_findings(db, doc))
        ContractAgent().run(test_deal.id, db)
        c2 = len(_clause_findings(db, doc))
        assert c1 == c2

    def test_agent_findings_stable_on_rerun(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        c1 = len(_agent_findings(db, test_deal))
        ContractAgent().run(test_deal.id, db)
        c2 = len(_agent_findings(db, test_deal))
        assert c1 == c2

    def test_agent_run_count_stable(self, db, test_deal):
        """Each re-run should produce exactly one AgentRun (no accumulation)."""
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        ContractAgent().run(test_deal.id, db)
        assert len(_agent_runs(db, test_deal)) == 1

    def test_previous_clause_findings_cleared(self, db, test_deal):
        """Old clause findings are deleted before new ones are written.

        Verified by using a custom LLM on the first run (1 clause) and the
        default FakeLLM on the second run (2 clauses).  If old rows were NOT
        cleared we'd see 3 rows, not 2.
        """
        class SingleClauseLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "EXTRACT CLAUSES" in prompt.upper():
                    return json.dumps([{
                        "clause_type": "termination",
                        "title": "One Clause Only",
                        "content": "Either party may terminate with 30 days written notice.",
                        "page_number": 1,
                        "confidence": 0.9,
                    }])
                return super().complete(prompt, max_tokens)

        doc = _make_doc(db, test_deal)
        ContractAgent(provider=SingleClauseLLM()).run(test_deal.id, db)
        assert len(_clause_findings(db, doc)) == 1  # sanity check

        # Second run with FakeLLM (returns 2 clauses); if old row isn't
        # cleared the total would be 3, not 2.
        ContractAgent().run(test_deal.id, db)
        assert len(_clause_findings(db, doc)) == 2

    def test_previous_agent_findings_cleared(self, db, test_deal):
        """Old AgentFinding summaries are deleted before new ones are written.

        First run covers 2 docs (2 summaries); second run covers only 1 doc
        (1 summary).  Without proper cleanup the count would grow to 3.
        """
        doc_a = _make_doc(db, test_deal, filename="a.txt")
        doc_b = _make_doc(db, test_deal, filename="b.txt")

        ContractAgent().run(test_deal.id, db)
        assert len(_agent_findings(db, test_deal)) == 2  # sanity check

        # Second run restricted to one document.
        ContractAgent().run(test_deal.id, db, contract_document_ids={doc_a.id})
        assert len(_agent_findings(db, test_deal)) == 1


# ── 6. AgentRun lifecycle ──────────────────────────────────────────────────

class TestAgentRunLifecycle:
    """AgentRun is created, timestamped, and correctly completed/failed."""

    def test_agent_run_created(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        assert len(_agent_runs(db, test_deal)) == 1

    def test_agent_run_status_completed(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.status == AgentRunStatus.completed

    def test_agent_run_started_at_set(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.started_at is not None

    def test_agent_run_completed_at_set(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.completed_at is not None

    def test_completed_at_after_started_at(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.completed_at >= run.started_at

    def test_agent_run_name(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.agent_name == AGENT_NAME

    def test_agent_run_deal_id(self, db, test_deal):
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.deal_id == test_deal.id

    def test_failed_run_marked_as_failed(self, db, test_deal):
        """When the LLM raises, the AgentRun is marked failed before re-raise."""

        class BrokenLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "EXTRACT CLAUSES" in prompt.upper():
                    raise RuntimeError("Simulated extraction failure")
                return super().complete(prompt, max_tokens)

        doc = _make_doc(db, test_deal)
        with pytest.raises(RuntimeError, match="Simulated extraction failure"):
            ContractAgent(provider=BrokenLLM()).run(test_deal.id, db)

        run = _agent_runs(db, test_deal)[0]
        assert run.status == AgentRunStatus.failed
        assert "Simulated extraction failure" in run.error_message

    def test_failed_run_has_error_message(self, db, test_deal):
        """error_message is populated on failure."""

        class BrokenLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "EXTRACT CLAUSES" in prompt.upper():
                    raise ValueError("oops")
                return super().complete(prompt, max_tokens)

        _make_doc(db, test_deal)
        with pytest.raises(ValueError):
            ContractAgent(provider=BrokenLLM()).run(test_deal.id, db)

        run = _agent_runs(db, test_deal)[0]
        assert run.error_message is not None
        assert len(run.error_message) > 0


# ── 7. Edge cases ──────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_deal_not_found_raises_value_error(self, db):
        with pytest.raises(ValueError, match="Deal 99999 not found"):
            ContractAgent().run(99999, db)

    def test_no_documents_completes_without_error(self, db, test_deal):
        """A deal with no documents should complete cleanly."""
        result = ContractAgent().run(test_deal.id, db)
        assert result["contract_documents"] == 0
        assert result["clause_findings_count"] == 0
        assert result["agent_findings_count"] == 0
        assert result["clauses_by_document"] == []

    def test_no_documents_agent_run_still_created(self, db, test_deal):
        """AgentRun is created even when there are no documents."""
        ContractAgent().run(test_deal.id, db)
        assert len(_agent_runs(db, test_deal)) == 1

    def test_no_documents_agent_run_completed(self, db, test_deal):
        ContractAgent().run(test_deal.id, db)
        assert _agent_runs(db, test_deal)[0].status == AgentRunStatus.completed

    def test_llm_returns_empty_array(self, db, test_deal):
        """If the LLM returns [], no ClauseFindings are created."""

        class NoClausesLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "EXTRACT CLAUSES" in prompt.upper():
                    return json.dumps([])
                return super().complete(prompt, max_tokens)

        doc = _make_doc(db, test_deal)
        result = ContractAgent(provider=NoClausesLLM()).run(test_deal.id, db)
        assert result["clause_findings_count"] == 0
        assert len(_clause_findings(db, doc)) == 0
        # AgentFinding is still created (summarises 0 clauses found)
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].structured_payload_json["clause_count"] == 0

    def test_llm_returns_invalid_json_produces_no_clauses(self, db, test_deal):
        """Unparseable LLM output results in zero clauses (no crash)."""

        class GarbageLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "EXTRACT CLAUSES" in prompt.upper():
                    return "this is not json at all"
                return super().complete(prompt, max_tokens)

        doc = _make_doc(db, test_deal)
        result = ContractAgent(provider=GarbageLLM()).run(test_deal.id, db)
        assert result["clause_findings_count"] == 0
        assert len(_clause_findings(db, doc)) == 0

    def test_module_level_run_contract_analysis(self, db, test_deal):
        """run_contract_analysis convenience function works correctly."""
        _make_doc(db, test_deal)
        result = run_contract_analysis(test_deal.id, db)
        assert result["clause_findings_count"] > 0

    def test_module_level_with_provider(self, db, test_deal):
        """Provider is forwarded through the convenience wrapper."""
        _make_doc(db, test_deal)
        explicit = FakeLLMProvider()
        result = run_contract_analysis(test_deal.id, db, provider=explicit)
        assert result["contract_documents"] == 1

    def test_module_level_with_document_ids(self, db, test_deal):
        """contract_document_ids forwarded through convenience wrapper."""
        doc = _make_doc(db, test_deal)
        result = run_contract_analysis(
            test_deal.id, db, contract_document_ids={doc.id}
        )
        assert result["contract_documents"] == 1


# ── 8. Relevance filtering ─────────────────────────────────────────────────

class TestRelevanceFiltering:
    """_classify_and_filter_clauses() removes low-relevance findings."""

    # Custom LLM that marks first clause as high, second as low.
    class _MixedRelevanceLLM(FakeLLMProvider):
        def complete(self, prompt, max_tokens=2048):
            p = prompt.upper()
            if "RELEVANCE FILTERING" in p:
                import re as _re
                indices = [int(m) for m in _re.findall(r'"clause_index"\s*:\s*(\d+)', prompt)]
                result = []
                for idx in indices:
                    relevance = "high" if idx == 0 else "low"
                    result.append({"clause_index": idx, "relevance": relevance, "reason": "Test"})
                import json as _json
                return _json.dumps(result)
            return super().complete(prompt, max_tokens)

    def test_low_relevance_clauses_filtered_out(self, db, test_deal):
        """Second clause (low relevance) must NOT be present in DB after run."""
        _make_doc(db, test_deal)
        ContractAgent(provider=self._MixedRelevanceLLM()).run(test_deal.id, db)
        all_findings = db.query(ClauseFinding).all()
        assert len(all_findings) == 1

    def test_high_relevance_clause_kept(self, db, test_deal):
        """First clause (high relevance) must be present in DB."""
        _make_doc(db, test_deal)
        ContractAgent(provider=self._MixedRelevanceLLM()).run(test_deal.id, db)
        cf = db.query(ClauseFinding).first()
        assert cf is not None
        assert cf.relevance_score == "high"

    def test_relevance_score_stored_on_finding(self, db, test_deal):
        """FakeLLM returns high for both → relevance_score = 'high' on all."""
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        for cf in db.query(ClauseFinding).all():
            assert cf.relevance_score in ("high", "medium", "low")

    def test_relevance_reason_stored_on_finding(self, db, test_deal):
        """relevance_reason is populated after classification."""
        _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        for cf in db.query(ClauseFinding).all():
            assert cf.relevance_reason is not None
            assert len(cf.relevance_reason) > 0

    def test_return_count_reflects_filtered_count(self, db, test_deal):
        """clause_findings_count in result must equal DB row count after filter."""
        _make_doc(db, test_deal)
        result = ContractAgent(provider=self._MixedRelevanceLLM()).run(test_deal.id, db)
        db_count = db.query(ClauseFinding).count()
        assert result["clause_findings_count"] == db_count
        assert result["clause_findings_count"] == 1  # only high kept

    def test_all_high_relevance_keeps_all(self, db, test_deal):
        """FakeLLM marks all as high → both clauses retained."""
        _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        assert result["clause_findings_count"] == 2

    def test_classification_failure_keeps_all_clauses(self, db, test_deal):
        """If relevance LLM raises, all clauses are retained (fail-open)."""
        class _FailRelevanceLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RELEVANCE FILTERING" in prompt.upper():
                    raise RuntimeError("Simulated relevance failure")
                return super().complete(prompt, max_tokens)

        _make_doc(db, test_deal)
        result = ContractAgent(provider=_FailRelevanceLLM()).run(test_deal.id, db)
        assert result["clause_findings_count"] == 2  # all kept on failure

    def test_ccnl_detected_by_filename(self, db, test_deal):
        """Document with 'ccnl' in filename is flagged as CCNL."""
        from packages.agents.contract_agent import ContractAgent as CA
        assert CA._is_ccnl("CCNL_metalmeccanici.pdf", "") is True
        assert CA._is_ccnl("service_agreement.pdf", "") is False

    def test_ccnl_detected_by_content(self, db, test_deal):
        """Document with CCNL indicator in raw_text is flagged as CCNL."""
        from packages.agents.contract_agent import ContractAgent as CA
        text = "Contratto Collettivo Nazionale di Lavoro per i dipendenti"
        assert CA._is_ccnl("documento.pdf", text) is True

    def test_medium_relevance_clause_kept(self, db, test_deal):
        """Medium-relevance clauses are retained (not filtered out)."""
        class _MediumLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RELEVANCE FILTERING" in prompt.upper():
                    import re as _re
                    import json as _json
                    indices = [int(m) for m in _re.findall(r'"clause_index"\s*:\s*(\d+)', prompt)]
                    return _json.dumps([
                        {"clause_index": idx, "relevance": "medium", "reason": "Medium"}
                        for idx in indices
                    ])
                return super().complete(prompt, max_tokens)

        _make_doc(db, test_deal)
        result = ContractAgent(provider=_MediumLLM()).run(test_deal.id, db)
        assert result["clause_findings_count"] == 2  # medium → kept


# ── 9. Orchestrator compatibility ──────────────────────────────────────────

class TestOrchestratorCompatibility:
    """Verify that ContractAgent output matches what the orchestrator expects
    from stages["specialist_analysis"]."""

    def test_return_contains_contract_documents_key(self, db, test_deal):
        """Orchestrator tests check stages["specialist_analysis"]["contract_documents"]."""
        _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        assert "contract_documents" in result

    def test_return_contains_clause_findings_count_key(self, db, test_deal):
        """Orchestrator tests check stages["specialist_analysis"]["clause_findings_count"]."""
        _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        assert "clause_findings_count" in result

    def test_clause_findings_count_matches_clause_finding_table(self, db, test_deal):
        """Returned count must equal actual rows in clause_findings table."""
        doc = _make_doc(db, test_deal)
        result = ContractAgent().run(test_deal.id, db)
        db_count = (
            db.query(ClauseFinding)
            .filter(ClauseFinding.document_id == doc.id)
            .count()
        )
        assert result["clause_findings_count"] == db_count

    def test_agent_name_constant_equals_contract_analysis(self):
        """AGENT_NAME constant value must match ContractAgent.AGENT_NAME."""
        assert AGENT_NAME == "contract_analysis"
        assert ContractAgent.AGENT_NAME == "contract_analysis"


# ── CCNL filtering ────────────────────────────────────────────────────────────

class TestCCNLFiltering:
    """CCNL documents are skipped; individual CCNL-referencing clauses are removed."""

    # --------------------------------------------------------------------- #
    # CCNL document-level skip                                               #
    # --------------------------------------------------------------------- #

    def test_ccnl_irrelevant_clause_types_removed(self, db, test_deal):
        """Non-allowlist clause types are removed from a CCNL document.

        FakeLLM returns termination + liability for every EXTRACT CLAUSES call.
        For a CCNL document, 'liability' is outside the allowlist and is removed
        deterministically; 'termination' is in the allowlist and survives.
        The default raw_text is used so the grounding check passes.
        """
        # CCNL is detected via filename; default raw_text contains the exact
        # strings FakeLLM uses as clause content, so grounding check passes.
        doc = _make_doc(db, test_deal, filename="CCNL_metalmeccanici_2024.txt")
        ContractAgent().run(test_deal.id, db)
        types = {c.clause_type.value for c in _clause_findings(db, doc)}
        assert "liability" not in types  # removed: not in allowlist

    def test_ccnl_allowlist_type_survives(self, db, test_deal):
        """Allowlist clause types (e.g. termination) survive the CCNL doc filter."""
        doc = _make_doc(db, test_deal, filename="CCNL_metalmeccanici_2024.txt")
        ContractAgent().run(test_deal.id, db)
        types = {c.clause_type.value for c in _clause_findings(db, doc)}
        assert "termination" in types  # in allowlist → kept

    def test_ccnl_document_analyzed_not_skipped(self, db, test_deal):
        """A CCNL document is analysed (not skipped), just heavily filtered."""
        _make_doc(db, test_deal, filename="ccnl_commercio.txt")
        result = ContractAgent().run(test_deal.id, db)
        # Document goes through the pipeline — shows up in contract_documents
        assert result["contract_documents"] == 1

    # --------------------------------------------------------------------- #
    # CCNL clause-level filter in non-CCNL documents                         #
    # --------------------------------------------------------------------- #

    def test_ccnl_clause_removed_from_regular_doc(self, db, test_deal):
        """A clause mentioning CCNL in a regular document is removed."""
        # FakeLLMProvider sees "EXTRACT CLAUSES" and returns 2 clauses.
        # One clause has "ccnl" in its content — it should be removed by the
        # deterministic filter BEFORE the relevance LLM is called.
        from packages.agents.contract_agent import ContractAgent as CA
        import types

        original_extract = CA._extract_clauses

        def patched_extract(self_inner, document_id, text, db_inner):
            """Inject a CCNL clause alongside a real M&A clause."""
            from app.models.clause_finding import ClauseFinding, ClauseType
            rows = [
                ClauseFinding(
                    document_id=document_id,
                    clause_type=ClauseType.termination,
                    title="Termination for Change of Control",
                    content="Either party may terminate upon change of control of the counterparty.",
                    confidence=0.9,
                ),
                ClauseFinding(
                    document_id=document_id,
                    clause_type=ClauseType.other,
                    title="CCNL Applicability",
                    content="The employment relationship is governed by the CCNL Metalmeccanici.",
                    confidence=0.85,
                ),
            ]
            for r in rows:
                db_inner.add(r)
            db_inner.flush()
            return rows

        CA._extract_clauses = patched_extract
        try:
            _make_doc(db, test_deal, filename="employment_agreement.txt")
            ContractAgent().run(test_deal.id, db)
        finally:
            CA._extract_clauses = original_extract

        all_clauses = db.query(ClauseFinding).filter(
            ClauseFinding.document_id.in_(
                [d.id for d in db.query(Document).filter(Document.deal_id == test_deal.id).all()]
            )
        ).all()
        titles = [c.title for c in all_clauses]
        assert "CCNL Applicability" not in titles
        assert any("Termination" in t or "Change of Control" in t for t in titles)

    def test_non_ccnl_clause_not_removed(self, db, test_deal):
        """A non-CCNL clause is NOT removed by the CCNL filter."""
        doc = _make_doc(db, test_deal)
        ContractAgent().run(test_deal.id, db)
        clauses = _clause_findings(db, doc)
        # FakeLLM returns termination + liability clauses (no CCNL refs)
        assert len(clauses) >= 1

    # --------------------------------------------------------------------- #
    # _is_ccnl static method                                                 #
    # --------------------------------------------------------------------- #

    def test_is_ccnl_filename(self):
        assert ContractAgent._is_ccnl("CCNL_metalmeccanici.pdf", "") is True

    def test_is_ccnl_content(self):
        assert ContractAgent._is_ccnl("document.txt", "Contratto Collettivo Nazionale...") is True

    def test_is_ccnl_false_for_regular_contract(self):
        assert ContractAgent._is_ccnl("service_agreement.pdf", "Termination clause...") is False

    # --------------------------------------------------------------------- #
    # _remove_ccnl_clauses                                                   #
    # --------------------------------------------------------------------- #

    def test_ccnl_keywords_list_nonempty(self):
        assert len(ContractAgent._CCNL_CLAUSE_KEYWORDS) > 0
        assert "ccnl" in ContractAgent._CCNL_CLAUSE_KEYWORDS

    def test_ccnl_relevant_clause_types_allowlist(self):
        """Verify the M&A-relevant allowlist for CCNL documents."""
        relevant = ContractAgent._CCNL_RELEVANT_CLAUSE_TYPES
        assert "non_compete" in relevant
        assert "indemnification" in relevant
        assert "change_of_control" in relevant
        assert "termination" in relevant
        # These should NOT be in the allowlist
        assert "liability" not in relevant
        assert "payment_terms" not in relevant
        assert "other" not in relevant


# ── CCNL compliance analysis ──────────────────────────────────────────────────

class TestCCNLComplianceAnalysis:
    """CCNL documents trigger the compliance check; findings stored as AgentFinding."""

    def test_ccnl_doc_creates_compliance_agent_findings(self, db, test_deal):
        """FakeLLM returns 1 CCNL compliance finding → stored as AgentFinding."""
        _make_doc(db, test_deal, filename="CCNL_metalmeccanici_2024.txt")
        ContractAgent().run(test_deal.id, db)
        compliance = [
            f for f in _agent_findings(db, test_deal)
            if f.category == "ccnl_compliance"
        ]
        assert len(compliance) == 1

    def test_compliance_finding_has_correct_fields(self, db, test_deal):
        """AgentFinding for CCNL compliance has title, description, severity."""
        _make_doc(db, test_deal, filename="CCNL_metalmeccanici_2024.txt")
        ContractAgent().run(test_deal.id, db)
        finding = next(
            f for f in _agent_findings(db, test_deal)
            if f.category == "ccnl_compliance"
        )
        assert finding.title
        assert finding.description
        assert finding.severity is not None
        assert finding.agent_name == AGENT_NAME

    def test_compliance_finding_payload_has_ccnl_category(self, db, test_deal):
        """structured_payload_json contains 'ccnl_category' key."""
        _make_doc(db, test_deal, filename="CCNL_metalmeccanici_2024.txt")
        ContractAgent().run(test_deal.id, db)
        finding = next(
            f for f in _agent_findings(db, test_deal)
            if f.category == "ccnl_compliance"
        )
        assert "ccnl_category" in (finding.structured_payload_json or {})

    def test_regular_doc_does_not_trigger_compliance_check(self, db, test_deal):
        """Non-CCNL documents do not produce ccnl_compliance AgentFindings."""
        _make_doc(db, test_deal, filename="service_agreement.txt")
        ContractAgent().run(test_deal.id, db)
        compliance = [
            f for f in _agent_findings(db, test_deal)
            if f.category == "ccnl_compliance"
        ]
        assert compliance == []

    def test_compliance_findings_cleared_on_rerun(self, db, test_deal):
        """Re-running the agent replaces previous compliance findings (idempotency)."""
        _make_doc(db, test_deal, filename="CCNL_metalmeccanici_2024.txt")
        ContractAgent().run(test_deal.id, db)
        first_count = len([
            f for f in _agent_findings(db, test_deal)
            if f.category == "ccnl_compliance"
        ])
        ContractAgent().run(test_deal.id, db)
        second_count = len([
            f for f in _agent_findings(db, test_deal)
            if f.category == "ccnl_compliance"
        ])
        assert first_count == second_count  # no duplication
