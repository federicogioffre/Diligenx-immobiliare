"""Tests for RedFlagAggregationAgent.

Covers:
- RedFlag creation: correct fields, FK linkage, severity coercion
- Deduplication: exact duplicates merged, normalisation (case/punctuation),
  highest-severity-wins, different category NOT deduped
- Context building: clause findings and agent findings appear in the
  context text forwarded to the LLM (verified via _ContextCaptureLLM)
- OpenQuestion generation: high → question; medium/low → no question;
  priority mapping; agent_name stamped correctly
- Return value: all required keys present, counts match DB, dedup_removed
- Idempotency: no accumulation on re-run; previous RedFlags and OpenQuestions cleared
- AgentRun lifecycle: created, timestamped, completed/failed, error_message
- Edge cases: deal not found, no documents, invalid JSON, empty array,
  convenience wrapper run_red_flag_aggregation
- Orchestrator compatibility: AGENT_NAME == "red_flag_aggregation", result keys match
"""
import json
import pytest

from packages.agents.deal_analysis_agent import LLMResponseError
from sqlalchemy.orm import Session

from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from app.models.clause_finding import ClauseFinding, ClauseType
from app.models.agent_finding import AgentFinding
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.red_flag import RedFlag, Severity
from app.models.open_question import OpenQuestion, Priority
from packages.agents.red_flag_aggregator import (
    RedFlagAggregationAgent,
    run_red_flag_aggregation,
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


# ── Test helpers ─────────────────────────────────────────────────────────────


def _make_doc(
    db: Session,
    deal: Deal,
    *,
    filename: str = "service_agreement.txt",
    raw_text: str = "SERVICE AGREEMENT. Termination: 30 days notice.",
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


def _make_clause_finding(
    db: Session,
    doc: Document,
    *,
    clause_type: ClauseType = ClauseType.termination,
    title: str = "Termination Clause",
    content: str = "Either party may terminate with 30 days notice.",
    confidence: float = 0.9,
    page_number: int | None = 1,
) -> ClauseFinding:
    cf = ClauseFinding(
        document_id=doc.id,
        clause_type=clause_type,
        title=title,
        content=content,
        page_number=page_number,
        confidence=confidence,
    )
    db.add(cf)
    db.commit()
    db.refresh(cf)
    return cf


def _make_agent_finding(
    db: Session,
    deal: Deal,
    *,
    doc: Document | None = None,
    agent_name: str = "corporate_governance",
    category: str = "veto_right",
    title: str = "Investor Veto",
    description: str = "Preferred shareholders hold veto rights.",
    severity: Severity = Severity.high,
    confidence: float = 0.85,
) -> AgentFinding:
    af = AgentFinding(
        deal_id=deal.id,
        document_id=doc.id if doc else None,
        agent_name=agent_name,
        category=category,
        title=title,
        description=description,
        severity=severity,
        confidence=confidence,
    )
    db.add(af)
    db.commit()
    db.refresh(af)
    return af


def _red_flags(db: Session, deal: Deal) -> list[RedFlag]:
    return db.query(RedFlag).filter(RedFlag.deal_id == deal.id).all()


def _open_questions(db: Session, deal: Deal) -> list[OpenQuestion]:
    return (
        db.query(OpenQuestion)
        .filter(
            OpenQuestion.deal_id == deal.id,
            OpenQuestion.agent_name == AGENT_NAME,
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


@pytest.fixture
def aggregation_source(db, test_deal):
    """Explicit evidence for tests of orchestration/metadata, not LLM quality."""
    document = _make_doc(db, test_deal, filename="test_source.txt")
    _make_clause_finding(db, document)
    return document


class UngroundedProvider(FakeLLMProvider):
    def complete(self, prompt, max_tokens=2048):
        return json.dumps([{"title": "Unsupported assertion", "issue": "No document supports this.",
                            "severity": "high", "category": "general"}])


# ── 1. RedFlag creation ────────────────────────────────────────────────────


@pytest.mark.usefixtures("aggregation_source")
class TestRedFlagCreation:
    """RedFlag rows are persisted with correct field values."""

    def test_red_flags_created_from_llm_output(self, db, test_deal):
        """FakeLLM returns 2 red flags → 2 RedFlag rows in DB."""
        _make_doc(db, test_deal)
        RedFlagAggregationAgent().run(test_deal.id, db)
        flags = _red_flags(db, test_deal)
        assert len(flags) == 2

    def test_red_flag_deal_id(self, db, test_deal):
        _make_doc(db, test_deal)
        RedFlagAggregationAgent().run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.deal_id == test_deal.id

    def test_red_flag_title_stored(self, db, test_deal):
        """FakeLLM returns title 'Unilateral Termination Right'."""
        _make_doc(db, test_deal)
        RedFlagAggregationAgent().run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert "Unilateral Termination Right" in flag.title

    def test_red_flag_issue_stored(self, db, test_deal):
        _make_doc(db, test_deal)
        RedFlagAggregationAgent().run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.issue  # non-empty

    def test_red_flag_severity_high(self, db, test_deal):
        """FakeLLM returns severity='high'."""
        _make_doc(db, test_deal)
        RedFlagAggregationAgent().run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.severity == Severity.high

    def test_red_flag_category_stored(self, db, test_deal):
        """FakeLLM returns category='termination'."""
        _make_doc(db, test_deal)
        RedFlagAggregationAgent().run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.category == "termination"

    def test_red_flag_confidence_stored(self, db, test_deal):
        _make_doc(db, test_deal)
        RedFlagAggregationAgent().run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.confidence is not None
        assert 0.0 <= flag.confidence <= 1.0

    def test_red_flag_source_document_id_null_from_fake(self, db, test_deal):
        """FakeLLM returns source_document_id=null → stored as None."""
        _make_doc(db, test_deal)
        RedFlagAggregationAgent().run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.source_document_id is None

    def test_invalid_severity_coerced_to_medium(self, db, test_deal):
        """Unrecognised severity values are normalised to 'medium'."""

        class BadSeverityLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    return json.dumps([{
                        "title": "Some Risk",
                        "description": "A risky thing.",
                        "severity": "ULTRA_CRITICAL",
                        "category": "compliance",
                        "confidence": 0.7,
                        "source_document_id": None,
                    }])
                return super().complete(prompt, max_tokens)

        _make_doc(db, test_deal)
        RedFlagAggregationAgent(provider=BadSeverityLLM()).run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.severity == Severity.medium

    def test_source_document_id_set_when_provided(self, db, test_deal):
        """When LLM returns a valid source_document_id it is persisted."""
        doc = _make_doc(db, test_deal)

        class DocLinkedLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    return json.dumps([{
                        "title": "Risky Clause",
                        "description": "Too broad indemnification.",
                        "severity": "high",
                        "category": "liability",
                        "confidence": 0.9,
                        "source_document_id": doc.id,
                    }])
                return super().complete(prompt, max_tokens)

        RedFlagAggregationAgent(provider=DocLinkedLLM()).run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.source_document_id == doc.id

    def _page_llm(self, doc_id, page):
        """A fake LLM that emits one red flag citing (doc_id, page)."""
        class _PageLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    return json.dumps([{
                        "title": "Cited Clause",
                        "issue": "A clause worth citing.",
                        "risk": "Some risk.",
                        "recommendation": "Do something.",
                        "severity": "high",
                        "category": "liability",
                        "confidence": 0.9,
                        "source_document_id": doc_id,
                        "source_page": page,
                    }])
                return super().complete(prompt, max_tokens)
        return _PageLLM()

    def test_source_page_persisted_when_it_matches_a_clause_page(self, db, test_deal):
        """A cited page independently backed by extracted text is kept."""
        doc = _make_doc(db, test_deal)
        finding = _make_clause_finding(db, doc, page_number=7)
        doc.raw_text = finding.content
        from app.models.document_chunk import DocumentChunk
        doc.page_count = 7
        db.add(DocumentChunk(document_id=doc.id, chunk_index=0, content=finding.content, page_number=7))
        db.commit()
        RedFlagAggregationAgent(provider=self._page_llm(doc.id, 7)).run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.source_page == 7

    def test_hallucinated_source_page_rejected(self, db, test_deal):
        """A cited page NOT backed by any clause finding is dropped to None,
        so a hallucinated citation never reaches the report."""
        doc = _make_doc(db, test_deal)
        _make_clause_finding(db, doc, page_number=7)
        RedFlagAggregationAgent(provider=self._page_llm(doc.id, 99)).run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.source_document_id == doc.id
        assert flag.source_page is None

    def test_source_page_ignored_without_source_document(self, db, test_deal):
        """A page with no source_document_id cannot be validated → None."""
        _make_doc(db, test_deal)
        RedFlagAggregationAgent(provider=self._page_llm(None, 3)).run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.source_page is None

    def test_no_documents_zero_flags(self, db, test_deal):
        """A model must not create unsupported flags from an empty corpus."""
        db.query(Document).filter_by(deal_id=test_deal.id).delete()
        db.commit()
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert result["red_flags_count"] == 0


# ── 2. Deduplication ───────────────────────────────────────────────────────


@pytest.mark.usefixtures("aggregation_source")
class TestDeduplication:
    """Near-duplicate flags are merged; highest severity wins."""

    def _dedup_llm(self, flags: list[dict]) -> FakeLLMProvider:
        """Return a FakeLLMProvider that yields *flags* for the red-flag prompt."""
        class CustomLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    return json.dumps(flags)
                return super().complete(prompt, max_tokens)
        return CustomLLM()

    def test_exact_duplicate_merged(self, db, test_deal):
        """Two identical flags collapse to one."""
        flags = [
            {"title": "Same Risk", "description": "desc", "severity": "high", "category": "termination", "confidence": 0.9, "source_document_id": None},
            {"title": "Same Risk", "description": "desc", "severity": "high", "category": "termination", "confidence": 0.8, "source_document_id": None},
        ]
        result = RedFlagAggregationAgent(provider=self._dedup_llm(flags)).run(test_deal.id, db)
        assert result["red_flags_count"] == 1
        assert result["dedup_removed"] == 1

    def test_case_normalisation_deduplicates(self, db, test_deal):
        """Titles differing only in case share the same fingerprint."""
        flags = [
            {"title": "High Risk Clause", "description": "...", "severity": "medium", "category": "liability", "confidence": 0.7, "source_document_id": None},
            {"title": "HIGH RISK CLAUSE", "description": "...", "severity": "medium", "category": "liability", "confidence": 0.7, "source_document_id": None},
        ]
        result = RedFlagAggregationAgent(provider=self._dedup_llm(flags)).run(test_deal.id, db)
        assert result["red_flags_count"] == 1
        assert result["dedup_removed"] == 1

    def test_punctuation_normalisation_deduplicates(self, db, test_deal):
        """Titles differing only in punctuation share the same fingerprint."""
        flags = [
            {"title": "Broad Indemnity!", "description": "...", "severity": "high", "category": "liability", "confidence": 0.9, "source_document_id": None},
            {"title": "Broad Indemnity", "description": "...", "severity": "high", "category": "liability", "confidence": 0.9, "source_document_id": None},
        ]
        result = RedFlagAggregationAgent(provider=self._dedup_llm(flags)).run(test_deal.id, db)
        assert result["red_flags_count"] == 1
        assert result["dedup_removed"] == 1

    def test_highest_severity_wins(self, db, test_deal):
        """When duplicates differ in severity, the highest severity is kept."""
        flags = [
            {"title": "Risk A", "description": "...", "severity": "low", "category": "payment", "confidence": 0.6, "source_document_id": None},
            {"title": "Risk A", "description": "...", "severity": "critical", "category": "payment", "confidence": 0.9, "source_document_id": None},
            {"title": "Risk A", "description": "...", "severity": "medium", "category": "payment", "confidence": 0.7, "source_document_id": None},
        ]
        result = RedFlagAggregationAgent(provider=self._dedup_llm(flags)).run(test_deal.id, db)
        assert result["red_flags_count"] == 1
        assert result["dedup_removed"] == 2
        flag = _red_flags(db, test_deal)[0]
        # "critical" wins the dedup but is normalized to high at persistence
        # (3-level Severity scale).
        assert flag.severity == Severity.high

    def test_different_category_not_deduped(self, db, test_deal):
        """Same title but different category → distinct risks."""
        flags = [
            {"title": "Same Title", "description": "...", "severity": "high", "category": "liability", "confidence": 0.9, "source_document_id": None},
            {"title": "Same Title", "description": "...", "severity": "high", "category": "termination", "confidence": 0.9, "source_document_id": None},
        ]
        result = RedFlagAggregationAgent(provider=self._dedup_llm(flags)).run(test_deal.id, db)
        assert result["red_flags_count"] == 2
        assert result["dedup_removed"] == 0

    def test_multiple_unique_flags_all_persisted(self, db, test_deal):
        """Three distinct flags all survive deduplication."""
        flags = [
            {"title": "Risk One", "description": "...", "severity": "high", "category": "termination", "confidence": 0.9, "source_document_id": None},
            {"title": "Risk Two", "description": "...", "severity": "medium", "category": "liability", "confidence": 0.7, "source_document_id": None},
            {"title": "Risk Three", "description": "...", "severity": "low", "category": "payment", "confidence": 0.5, "source_document_id": None},
        ]
        result = RedFlagAggregationAgent(provider=self._dedup_llm(flags)).run(test_deal.id, db)
        assert result["red_flags_count"] == 3
        assert result["dedup_removed"] == 0

    def test_dedup_removed_zero_for_unique_flags(self, db, test_deal):
        """FakeLLM returns 1 flag → dedup_removed should be 0."""
        _make_doc(db, test_deal)
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert result["dedup_removed"] == 0


# ── 3. Context building ────────────────────────────────────────────────────


@pytest.mark.usefixtures("aggregation_source")
class TestContextBuilding:
    """Clause and agent findings appear in the LLM context text."""

    class _ContextCaptureLLM(FakeLLMProvider):
        """Captures the last prompt before delegating to FakeLLMProvider."""
        def __init__(self):
            self.last_prompt = ""

        def complete(self, prompt, max_tokens=2048):
            if "GROUNDING REVIEW\n" not in prompt:
                self.last_prompt = prompt
            return super().complete(prompt, max_tokens)

    def test_clause_finding_appears_in_context(self, db, test_deal):
        """ClauseFinding title should appear in the prompt sent to the LLM."""
        doc = _make_doc(db, test_deal)
        _make_clause_finding(db, doc, title="Critical Termination Clause")

        llm = self._ContextCaptureLLM()
        RedFlagAggregationAgent(provider=llm).run(test_deal.id, db)
        assert "Critical Termination Clause" in llm.last_prompt

    def test_clause_content_appears_in_context(self, db, test_deal):
        """ClauseFinding content snippet is included in context."""
        doc = _make_doc(db, test_deal)
        _make_clause_finding(db, doc, content="Liability shall not exceed ten dollars.")

        llm = self._ContextCaptureLLM()
        RedFlagAggregationAgent(provider=llm).run(test_deal.id, db)
        assert "Liability shall not exceed ten dollars" in llm.last_prompt

    def test_agent_finding_appears_in_context(self, db, test_deal):
        """AgentFinding title should appear in the prompt."""
        doc = _make_doc(db, test_deal)
        _make_agent_finding(db, test_deal, doc=doc, title="Veto Right on Major Decisions")

        llm = self._ContextCaptureLLM()
        RedFlagAggregationAgent(provider=llm).run(test_deal.id, db)
        assert "Veto Right on Major Decisions" in llm.last_prompt

    def test_document_id_appears_in_context(self, db, test_deal):
        """Document ID is shown in the context headers."""
        doc = _make_doc(db, test_deal)
        _make_clause_finding(db, doc)

        llm = self._ContextCaptureLLM()
        RedFlagAggregationAgent(provider=llm).run(test_deal.id, db)
        assert str(doc.id) in llm.last_prompt

    def test_filename_appears_in_context(self, db, test_deal):
        """Document filename is shown in the context headers."""
        doc = _make_doc(db, test_deal, filename="shareholder_agreement.txt")
        _make_clause_finding(db, doc)

        llm = self._ContextCaptureLLM()
        RedFlagAggregationAgent(provider=llm).run(test_deal.id, db)
        assert "shareholder_agreement.txt" in llm.last_prompt

    def test_document_router_findings_excluded_from_context(self, db, test_deal):
        """document_router AgentFindings are filtered out (low signal)."""
        doc = _make_doc(db, test_deal)
        _make_agent_finding(
            db, test_deal, doc=doc,
            agent_name="document_router",
            category="document_classification",
            title="SHOULD_NOT_APPEAR_IN_CONTEXT",
        )

        llm = self._ContextCaptureLLM()
        RedFlagAggregationAgent(provider=llm).run(test_deal.id, db)
        assert "SHOULD_NOT_APPEAR_IN_CONTEXT" not in llm.last_prompt

    def test_no_findings_produces_fallback_context(self, db, test_deal):
        """When there are no clause or agent findings, context is a fallback string."""
        llm = self._ContextCaptureLLM()
        RedFlagAggregationAgent(provider=llm).run(test_deal.id, db)
        # The prompt should be non-empty (contains the template text at minimum)
        assert len(llm.last_prompt) > 0

    def test_multiple_documents_both_in_context(self, db, test_deal):
        """When two documents have findings, both appear in the context."""
        doc_a = _make_doc(db, test_deal, filename="contract_a.txt")
        doc_b = _make_doc(db, test_deal, filename="contract_b.txt")
        _make_clause_finding(db, doc_a, title="Clause from A")
        _make_clause_finding(db, doc_b, title="Clause from B")

        llm = self._ContextCaptureLLM()
        RedFlagAggregationAgent(provider=llm).run(test_deal.id, db)
        assert "Clause from A" in llm.last_prompt
        assert "Clause from B" in llm.last_prompt


# ── 4. OpenQuestion generation ─────────────────────────────────────────────


@pytest.mark.usefixtures("aggregation_source")
class TestOpenQuestionGeneration:
    """high/critical flags produce OpenQuestions; medium/low do not."""

    def _llm_with_flags(self, flags: list[dict]) -> FakeLLMProvider:
        class CustomLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    return json.dumps(flags)
                return super().complete(prompt, max_tokens)
        return CustomLLM()

    def test_high_severity_creates_open_question(self, db, test_deal):
        """Both stub red flags are high → one OpenQuestion each."""
        RedFlagAggregationAgent().run(test_deal.id, db)
        questions = _open_questions(db, test_deal)
        assert len(questions) == 2

    def test_critical_severity_creates_open_question(self, db, test_deal):
        flags = [{"title": "Critical Issue", "description": "...", "severity": "critical", "category": "compliance", "confidence": 0.95, "source_document_id": None}]
        RedFlagAggregationAgent(provider=self._llm_with_flags(flags)).run(test_deal.id, db)
        questions = _open_questions(db, test_deal)
        assert len(questions) == 1

    def test_medium_severity_no_open_question(self, db, test_deal):
        flags = [{"title": "Medium Risk", "description": "...", "severity": "medium", "category": "payment", "confidence": 0.7, "source_document_id": None}]
        RedFlagAggregationAgent(provider=self._llm_with_flags(flags)).run(test_deal.id, db)
        questions = _open_questions(db, test_deal)
        assert len(questions) == 0

    def test_low_severity_no_open_question(self, db, test_deal):
        flags = [{"title": "Low Risk", "description": "...", "severity": "low", "category": "insurance", "confidence": 0.5, "source_document_id": None}]
        RedFlagAggregationAgent(provider=self._llm_with_flags(flags)).run(test_deal.id, db)
        questions = _open_questions(db, test_deal)
        assert len(questions) == 0

    def test_high_priority_for_critical_flags(self, db, test_deal):
        """critical severity → Priority.high on the OpenQuestion."""
        flags = [{"title": "Critical Issue", "description": "...", "severity": "critical", "category": "compliance", "confidence": 0.95, "source_document_id": None}]
        RedFlagAggregationAgent(provider=self._llm_with_flags(flags)).run(test_deal.id, db)
        q = _open_questions(db, test_deal)[0]
        assert q.priority == Priority.high

    def test_high_priority_for_high_flags(self, db, test_deal):
        """high severity → Priority.high on the OpenQuestion."""
        RedFlagAggregationAgent().run(test_deal.id, db)
        q = _open_questions(db, test_deal)[0]
        assert q.priority == Priority.high

    def test_open_question_agent_name(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        q = _open_questions(db, test_deal)[0]
        assert q.agent_name == AGENT_NAME

    def test_open_question_deal_id(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        q = _open_questions(db, test_deal)[0]
        assert q.deal_id == test_deal.id

    def test_open_question_references_flag_title(self, db, test_deal):
        """The question text mentions the red flag title."""
        RedFlagAggregationAgent().run(test_deal.id, db)
        q = _open_questions(db, test_deal)[0]
        assert "Unilateral Termination Right" in q.question

    def test_open_question_count_matches_high_critical_flags(self, db, test_deal):
        """Two high flags → two open questions."""
        flags = [
            {"title": "Risk Alpha", "description": "...", "severity": "high", "category": "termination", "confidence": 0.9, "source_document_id": None},
            {"title": "Risk Beta", "description": "...", "severity": "critical", "category": "liability", "confidence": 0.95, "source_document_id": None},
            {"title": "Minor Risk", "description": "...", "severity": "low", "category": "payment", "confidence": 0.5, "source_document_id": None},
        ]
        RedFlagAggregationAgent(provider=self._llm_with_flags(flags)).run(test_deal.id, db)
        questions = _open_questions(db, test_deal)
        assert len(questions) == 2


# ── 5. Return value ────────────────────────────────────────────────────────


@pytest.mark.usefixtures("aggregation_source")
class TestReturnValue:
    """run() returns a dict with the expected structure and counts."""

    def test_required_keys_present(self, db, test_deal):
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        for key in (
            "deal_id",
            "red_flags_count",
            "open_questions_count",
            "flags_by_severity",
            "flags_by_category",
            "dedup_removed",
        ):
            assert key in result, f"Missing key: {key}"

    def test_deal_id_matches(self, db, test_deal):
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert result["deal_id"] == test_deal.id

    def test_red_flags_count_matches_db(self, db, test_deal):
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        db_count = db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count()
        assert result["red_flags_count"] == db_count

    def test_open_questions_count_matches_db(self, db, test_deal):
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        db_count = (
            db.query(OpenQuestion)
            .filter(
                OpenQuestion.deal_id == test_deal.id,
                OpenQuestion.agent_name == AGENT_NAME,
            )
            .count()
        )
        assert result["open_questions_count"] == db_count

    def test_flags_by_severity_is_dict(self, db, test_deal):
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert isinstance(result["flags_by_severity"], dict)

    def test_flags_by_severity_has_all_severities(self, db, test_deal):
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        fbs = result["flags_by_severity"]
        for sev in ("low", "medium", "high"):
            assert sev in fbs, f"Severity '{sev}' missing from flags_by_severity"

    def test_flags_by_severity_sum_equals_total(self, db, test_deal):
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        total = sum(result["flags_by_severity"].values())
        assert total == result["red_flags_count"]

    def test_flags_by_category_is_dict(self, db, test_deal):
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert isinstance(result["flags_by_category"], dict)

    def test_flags_by_category_sum_equals_total(self, db, test_deal):
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        total = sum(result["flags_by_category"].values())
        assert total == result["red_flags_count"]

    def test_dedup_removed_is_non_negative(self, db, test_deal):
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert result["dedup_removed"] >= 0

    def test_flags_by_category_contains_termination(self, db, test_deal):
        """FakeLLM returns category='termination'."""
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert "termination" in result["flags_by_category"]

    def test_flags_by_severity_high_count(self, db, test_deal):
        """FakeLLM returns 2 high-severity flags."""
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert result["flags_by_severity"]["high"] == 2


# ── 6. Idempotency ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("aggregation_source")
class TestIdempotency:
    """Re-running the agent produces stable counts — no row accumulation."""

    def test_red_flags_stable_on_rerun(self, db, test_deal):
        r1 = RedFlagAggregationAgent().run(test_deal.id, db)
        r2 = RedFlagAggregationAgent().run(test_deal.id, db)
        assert r1["red_flags_count"] == r2["red_flags_count"]

    def test_db_red_flag_count_stable_on_rerun(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        c1 = db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count()
        RedFlagAggregationAgent().run(test_deal.id, db)
        c2 = db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count()
        assert c1 == c2

    def test_open_questions_stable_on_rerun(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        c1 = len(_open_questions(db, test_deal))
        RedFlagAggregationAgent().run(test_deal.id, db)
        c2 = len(_open_questions(db, test_deal))
        assert c1 == c2

    def test_agent_run_count_stable(self, db, test_deal):
        """Each re-run replaces the previous AgentRun (no accumulation)."""
        RedFlagAggregationAgent().run(test_deal.id, db)
        RedFlagAggregationAgent().run(test_deal.id, db)
        assert len(_agent_runs(db, test_deal)) == 1

    def test_previous_red_flags_cleared_before_rerun(self, db, test_deal):
        """If the first run produces 1 flag and the second run produces 0,
        the DB ends up with 0 — not 1."""

        class NoFlagsLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    return json.dumps([])
                return super().complete(prompt, max_tokens)

        # First run: default FakeLLM → 2 flags
        RedFlagAggregationAgent().run(test_deal.id, db)
        assert db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count() == 2

        # Second run: NoFlagsLLM → 0 flags; old row must be gone
        RedFlagAggregationAgent(provider=NoFlagsLLM()).run(test_deal.id, db)
        assert db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count() == 0

    def test_previous_open_questions_cleared_before_rerun(self, db, test_deal):
        """If the first run produces open questions and the second produces
        fewer, old questions are not kept."""

        class NoFlagsLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    return json.dumps([])
                return super().complete(prompt, max_tokens)

        # First run: 2 high-severity flags → 2 open questions
        RedFlagAggregationAgent().run(test_deal.id, db)
        assert len(_open_questions(db, test_deal)) == 2

        # Second run: 0 flags → 0 questions
        RedFlagAggregationAgent(provider=NoFlagsLLM()).run(test_deal.id, db)
        assert len(_open_questions(db, test_deal)) == 0


# ── 7. AgentRun lifecycle ──────────────────────────────────────────────────


@pytest.mark.usefixtures("aggregation_source")
class TestAgentRunLifecycle:
    """AgentRun is created, timestamped, and correctly completed/failed."""

    def test_agent_run_created(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        assert len(_agent_runs(db, test_deal)) == 1

    def test_agent_run_status_completed(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.status == AgentRunStatus.completed

    def test_agent_run_started_at_set(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.started_at is not None

    def test_agent_run_completed_at_set(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.completed_at is not None

    def test_completed_at_after_started_at(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.completed_at >= run.started_at

    def test_agent_run_name(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.agent_name == AGENT_NAME

    def test_agent_run_deal_id(self, db, test_deal):
        RedFlagAggregationAgent().run(test_deal.id, db)
        run = _agent_runs(db, test_deal)[0]
        assert run.deal_id == test_deal.id

    def test_failed_run_marked_as_failed(self, db, test_deal):
        """When the LLM raises, AgentRun is marked failed before re-raise."""

        class BrokenLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    raise RuntimeError("Simulated aggregation failure")
                return super().complete(prompt, max_tokens)

        with pytest.raises(RuntimeError, match="Simulated aggregation failure"):
            RedFlagAggregationAgent(provider=BrokenLLM()).run(test_deal.id, db)

        run = _agent_runs(db, test_deal)[0]
        assert run.status == AgentRunStatus.failed

    def test_failed_run_has_error_message(self, db, test_deal):

        class BrokenLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    raise ValueError("aggregation error")
                return super().complete(prompt, max_tokens)

        with pytest.raises(ValueError):
            RedFlagAggregationAgent(provider=BrokenLLM()).run(test_deal.id, db)

        run = _agent_runs(db, test_deal)[0]
        assert run.error_message is not None
        assert "aggregation error" in run.error_message

    def test_no_previous_run_on_first_call(self, db, test_deal):
        """Before any run the table should have no matching AgentRun."""
        assert len(_agent_runs(db, test_deal)) == 0
        RedFlagAggregationAgent().run(test_deal.id, db)
        assert len(_agent_runs(db, test_deal)) == 1


# ── 8. Edge cases ──────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_deal_not_found_raises_value_error(self, db):
        with pytest.raises(ValueError, match="Deal 99999 not found"):
            RedFlagAggregationAgent().run(99999, db)

    def test_no_documents_unsupported_flags_fail(self, db, test_deal):
        with pytest.raises(LLMResponseError, match="without source evidence"):
            RedFlagAggregationAgent(UngroundedProvider()).run(test_deal.id, db)

    def test_no_documents_agent_run_created(self, db, test_deal):
        with pytest.raises(LLMResponseError):
            RedFlagAggregationAgent(UngroundedProvider()).run(test_deal.id, db)
        assert len(_agent_runs(db, test_deal)) == 1

    def test_no_documents_unsupported_flags_mark_run_failed(self, db, test_deal):
        with pytest.raises(LLMResponseError):
            RedFlagAggregationAgent(UngroundedProvider()).run(test_deal.id, db)
        assert _agent_runs(db, test_deal)[0].status == AgentRunStatus.failed

    def test_llm_returns_invalid_json_fails_stage(self, db, test_deal):
        """Unparseable LLM output fails the stage."""

        class GarbageLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    return "this is not valid json at all"
                return super().complete(prompt, max_tokens)

        with pytest.raises(LLMResponseError):
            RedFlagAggregationAgent(provider=GarbageLLM()).run(test_deal.id, db)

    def test_llm_returns_empty_array_produces_no_flags(self, db, test_deal):
        """An empty JSON array from the LLM produces zero red flags."""

        class NoFlagsLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    return json.dumps([])
                return super().complete(prompt, max_tokens)

        result = RedFlagAggregationAgent(provider=NoFlagsLLM()).run(test_deal.id, db)
        assert result["red_flags_count"] == 0
        assert result["open_questions_count"] == 0

    def test_llm_returns_non_list_fails_stage(self, db, test_deal):
        """A JSON object is not a valid red-flag response."""

        class ObjectLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    return json.dumps({"error": "unexpected object"})
                return super().complete(prompt, max_tokens)

        with pytest.raises(LLMResponseError):
            RedFlagAggregationAgent(provider=ObjectLLM()).run(test_deal.id, db)

    def test_module_level_run_red_flag_aggregation(self, db, test_deal):
        """run_red_flag_aggregation convenience function works correctly."""
        _make_doc(db, test_deal)
        result = run_red_flag_aggregation(test_deal.id, db)
        assert "red_flags_count" in result

    def test_module_level_with_provider(self, db, test_deal):
        """Provider is forwarded through the convenience wrapper."""
        _make_doc(db, test_deal)
        explicit = FakeLLMProvider()
        result = run_red_flag_aggregation(test_deal.id, db, provider=explicit)
        assert result["red_flags_count"] >= 0

    def test_existing_red_flags_from_other_sources_cleared(self, db, test_deal):
        """All RedFlags for the deal are cleared on each run (agent owns them all)."""
        _make_doc(db, test_deal)
        # Manually insert a red flag (simulating a previous run from any source)
        pre_existing = RedFlag(
            deal_id=test_deal.id,
            title="Pre-existing Flag",
            issue="From a previous run.",
            severity=Severity.low,
            category="other",
        )
        db.add(pre_existing)
        db.commit()

        # Run the agent — it should clear the pre-existing flag
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        # Only the flags from this run remain
        db_flags = _red_flags(db, test_deal)
        assert all(f.title != "Pre-existing Flag" for f in db_flags)
        assert result["red_flags_count"] == len(db_flags)


# ── 9. Orchestrator compatibility ──────────────────────────────────────────


@pytest.mark.usefixtures("aggregation_source")
class TestOrchestratorCompatibility:
    """Verify that RedFlagAggregationAgent output matches what the orchestrator
    expects from stages['red_flag_aggregation']."""

    def test_agent_name_constant_value(self):
        """AGENT_NAME must equal the orchestrator's AGENT_RED_FLAG constant."""
        assert AGENT_NAME == "red_flag_aggregation"
        assert RedFlagAggregationAgent.AGENT_NAME == "red_flag_aggregation"

    def test_result_contains_red_flags_count(self, db, test_deal):
        """Orchestrator tests check stages['red_flag_aggregation']['red_flags_count']."""
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert "red_flags_count" in result

    def test_result_contains_open_questions_count(self, db, test_deal):
        """Orchestrator tests check stages['red_flag_aggregation']['open_questions_count']."""
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert "open_questions_count" in result

    def test_result_does_not_contain_error_on_success(self, db, test_deal):
        """A successful run must NOT include the 'error' key."""
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        assert "error" not in result

    def test_re_raise_on_failure_for_orchestrator_isolation(self, db, test_deal):
        """The agent re-raises exceptions so the orchestrator's failure-isolation
        wrapper can catch them and mark the stage as 'error'."""

        class BrokenLLM(FakeLLMProvider):
            def complete(self, prompt, max_tokens=2048):
                if "RED FLAGS" in prompt.upper() and "DUE DILIGENCE" not in prompt.upper():
                    raise RuntimeError("stage failure")
                return super().complete(prompt, max_tokens)

        with pytest.raises(RuntimeError):
            RedFlagAggregationAgent(provider=BrokenLLM()).run(test_deal.id, db)

    def test_red_flags_count_matches_red_flag_table(self, db, test_deal):
        """Returned count must equal actual rows in red_flags table."""
        result = RedFlagAggregationAgent().run(test_deal.id, db)
        db_count = db.query(RedFlag).filter(RedFlag.deal_id == test_deal.id).count()
        assert result["red_flags_count"] == db_count

    def test_open_questions_use_agent_red_flag_name(self, db, test_deal):
        """OpenQuestion.agent_name must equal AGENT_NAME so orchestrator
        queries like OpenQuestion.agent_name == AGENT_RED_FLAG work."""
        from packages.agents.orchestrator import AGENT_RED_FLAG
        assert AGENT_RED_FLAG == AGENT_NAME
        RedFlagAggregationAgent().run(test_deal.id, db)
        for q in _open_questions(db, test_deal):
            assert q.agent_name == AGENT_RED_FLAG


# ── Remedy and impact tags, carried figures, severity floor ────────────────

from packages.agents.red_flag_aggregator import (  # noqa: E402
    _VALID_REMEDY_TYPES,
    _VALID_IMPACTS,
    _build_severity_floors,
    _apply_severity_floor,
    _summarize_payload,
)
from packages.agents.deal_analysis_agent import LLMProvider  # noqa: E402


def _flag_llm(**overrides) -> LLMProvider:
    """A stub returning exactly one red flag, with fields overridden."""
    item = {
        "finding_type": "red_flag",
        "title": "Notified tax assessment",
        "issue": "An assessment was notified for FY2022.",
        "risk": "The target bears the assessed amount.",
        "recommendation": "Insert a specific indemnity in the SPA.",
        "severity": "medium",
        "area": "tax",
        "category": "tax_assessment",
        "confidence": 0.9,
        "source_document_id": None,
    }
    item.update(overrides)

    class _Stub(FakeLLMProvider):
        def complete(self, prompt: str, max_tokens: int = 4096) -> str:
            if "GROUNDING REVIEW\n" in prompt:
                return super().complete(prompt, max_tokens)
            if "RED FLAGS" in prompt.upper():
                return json.dumps([item])
            return "[]"

    return _Stub()


def _tax_finding(db, deal, *, category="tax_assessment", payload=None) -> AgentFinding:
    af = AgentFinding(
        deal_id=deal.id,
        document_id=None,
        agent_name="tax_analysis",
        category=category,
        title="Assessment",
        description="An assessment was notified.",
        severity=Severity.high,
        confidence=0.9,
        structured_payload_json=payload,
    )
    db.add(af)
    db.flush()
    return af


@pytest.mark.usefixtures("aggregation_source")
class TestRemedyAndImpactTags:
    """Two axes: the instrument that answers a finding, and what it hits."""

    def test_tags_are_persisted(self, db, test_deal):
        agent = RedFlagAggregationAgent(
            provider=_flag_llm(remedy_type="indemnity", impact="value")
        )
        agent.run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.remedy_type == "indemnity"
        assert flag.impact == "value"

    @pytest.mark.parametrize("remedy", _VALID_REMEDY_TYPES)
    def test_every_remedy_in_the_vocabulary_is_accepted(
        self, db, test_deal, remedy: str
    ):
        RedFlagAggregationAgent(provider=_flag_llm(remedy_type=remedy)).run(
            test_deal.id, db
        )
        assert _red_flags(db, test_deal)[0].remedy_type == remedy

    @pytest.mark.parametrize("impact", _VALID_IMPACTS)
    def test_every_impact_in_the_vocabulary_is_accepted(
        self, db, test_deal, impact: str
    ):
        RedFlagAggregationAgent(provider=_flag_llm(impact=impact)).run(
            test_deal.id, db
        )
        assert _red_flags(db, test_deal)[0].impact == impact

    def test_normalisation_of_spacing_and_case(self, db, test_deal):
        RedFlagAggregationAgent(
            provider=_flag_llm(remedy_type="Condition Precedent", impact="SPA")
        ).run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.remedy_type == "condition_precedent"
        assert flag.impact == "spa"

    @pytest.mark.parametrize("bad", ["escrow", "", None, 7, "value_or_spa"])
    def test_unknown_tag_becomes_null_rather_than_a_guess(
        self, db, test_deal, bad
    ):
        """An untagged flag a lawyer completes beats a wrongly tagged one."""
        RedFlagAggregationAgent(provider=_flag_llm(remedy_type=bad)).run(
            test_deal.id, db
        )
        assert _red_flags(db, test_deal)[0].remedy_type is None

    def test_tags_absent_from_output_stay_null(self, db, test_deal):
        RedFlagAggregationAgent(provider=_flag_llm()).run(test_deal.id, db)
        flag = _red_flags(db, test_deal)[0]
        assert flag.remedy_type is None and flag.impact is None


@pytest.mark.usefixtures("aggregation_source")
class TestCarriedFigures:
    """The amount and the years the specialists extracted must survive."""

    def test_amount_and_years_are_carried(self, db, test_deal):
        doc = _make_doc(db, test_deal, raw_text="Avviso di accertamento: EUR 240000.")
        RedFlagAggregationAgent(
            provider=_flag_llm(amount_eur=240000, fiscal_years=[2022, 2021],
                               source_document_id=doc.id, amount_evidence="EUR 240000")
        ).run(test_deal.id, db)
        payload = _red_flags(db, test_deal)[0].structured_payload_json
        assert payload["amount_eur"] == 240000
        assert payload["fiscal_years"] == [2021, 2022]

    def test_payload_contains_review_provenance_without_inventing_amounts(self, db, test_deal):
        RedFlagAggregationAgent(provider=_flag_llm()).run(test_deal.id, db)
        payload = _red_flags(db, test_deal)[0].structured_payload_json
        assert payload["grounding_reviewed"] is True
        assert "amount_eur" not in payload

    @pytest.mark.parametrize("bad", ["circa 240k", -3, True, None])
    def test_unusable_amount_is_dropped(self, db, test_deal, bad):
        RedFlagAggregationAgent(provider=_flag_llm(amount_eur=bad)).run(
            test_deal.id, db
        )
        payload = _red_flags(db, test_deal)[0].structured_payload_json
        assert payload is None or "amount_eur" not in payload

    def test_non_numeric_years_are_dropped(self, db, test_deal):
        RedFlagAggregationAgent(
            provider=_flag_llm(fiscal_years=[2022, "duemilaventidue", None])
        ).run(test_deal.id, db)
        payload = _red_flags(db, test_deal)[0].structured_payload_json
        assert payload["fiscal_years"] == [2022]


@pytest.mark.usefixtures("aggregation_source")
class TestSeverityFloor:
    """A finding with no available defence cannot be reported as medium."""

    def test_actual_defensibility_raises_the_flag(self, db, test_deal):
        _tax_finding(db, test_deal, payload={"defensibility": "actual"})
        RedFlagAggregationAgent(provider=_flag_llm(severity="medium")).run(
            test_deal.id, db
        )
        flag = _red_flags(db, test_deal)[0]
        assert flag.severity == Severity.high
        assert flag.structured_payload_json["severity_floored"] is True

    def test_capital_loss_is_never_below_high(self, db, test_deal):
        _tax_finding(db, test_deal, category="capital_loss")
        RedFlagAggregationAgent(
            provider=_flag_llm(severity="low", category="capital_loss")
        ).run(test_deal.id, db)
        assert _red_flags(db, test_deal)[0].severity == Severity.high

    def test_floor_never_lowers_a_severity(self, db, test_deal):
        _tax_finding(db, test_deal, payload={"defensibility": "actual"})
        RedFlagAggregationAgent(provider=_flag_llm(severity="high")).run(
            test_deal.id, db
        )
        flag = _red_flags(db, test_deal)[0]
        assert flag.severity == Severity.high
        # Not marked as floored: the model already had it right.
        assert flag.structured_payload_json.get("severity_floored") is None

    def test_no_floor_without_a_matching_category(self, db, test_deal):
        """The floor is a safety net; a missed match costs nothing."""
        _tax_finding(db, test_deal, category="tax_debt", payload={"defensibility": "actual"})
        RedFlagAggregationAgent(
            provider=_flag_llm(severity="medium", category="something_else")
        ).run(test_deal.id, db)
        assert _red_flags(db, test_deal)[0].severity == Severity.medium

    def test_interpretative_grade_creates_no_floor(self, db, test_deal):
        _tax_finding(db, test_deal, payload={"defensibility": "high"})
        RedFlagAggregationAgent(provider=_flag_llm(severity="medium")).run(
            test_deal.id, db
        )
        assert _red_flags(db, test_deal)[0].severity == Severity.medium


class TestFloorHelpers:
    """Unit-level behaviour of the floor computation."""

    def test_floors_shared_ranking_understands_critical(self):
        """The floor and the deduplication must agree on what is higher."""
        assert _apply_severity_floor("critical", "high") == "critical"
        assert _apply_severity_floor("low", "high") == "high"
        assert _apply_severity_floor("high", None) == "high"

    def test_findings_without_a_category_are_ignored(self, db, test_deal):
        af = _tax_finding(db, test_deal, category="", payload={"defensibility": "actual"})
        assert _build_severity_floors([af]) == {}


class TestPayloadSummary:
    """What the aggregator is told about each specialist finding."""

    def test_present_fields_only(self):
        summary = _summarize_payload({
            "defensibility": "actual",
            "tax_kind": "iva",
            "amount_eur": 85000,
            "amount_source": "document",
            "fiscal_years": [2021, 2022],
            "mitigating_factors": ["instalment_plan_in_force"],
            "legal_basis": "art. 13 D.Lgs. 471/1997",
        })
        assert "defensibility=actual" in summary
        assert "tax=iva" in summary
        assert "EUR 85,000" in summary
        assert "FY 2021, 2022" in summary
        assert "instalment_plan_in_force" in summary
        assert "art. 13" in summary

    def test_empty_payload_renders_nothing(self):
        assert _summarize_payload(None) == ""
        assert _summarize_payload({}) == ""

    def test_generic_tax_kind_is_not_noise(self):
        assert _summarize_payload({"tax_kind": "altro"}) == ""

    def test_time_barred_years_are_surfaced(self):
        summary = _summarize_payload({
            "assessment_periods": [
                {"fiscal_year": 2004, "time_barred": True},
                {"fiscal_year": 2022, "time_barred": False},
            ]
        })
        assert "time-barred: FY 2004" in summary
        assert "2022" not in summary

    def test_keyword_floor_origin_is_disclosed(self):
        assert "keyword floor" in _summarize_payload({"source": "heuristic"})

    def test_covenant_flags_only_when_true(self):
        assert "change-of-control clause: yes" in _summarize_payload(
            {"change_of_control_clause": True}
        )
        assert _summarize_payload({"change_of_control_clause": False}) == ""
