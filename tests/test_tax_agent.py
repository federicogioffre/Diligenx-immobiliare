"""Tests for TaxAgent — tax documentary review.

Covers:
- Finding extraction: AgentFinding rows created with correct fields
  (category=finding_type, severity, confidence, title, description,
   structured_payload_json)
- Invalid finding_type values coerced to 'other_tax'
- Return value shape and aggregation counts
- Auto-detection of tax documents via keyword matching
  (filename, raw_text[:1500]) and union with routed_document_ids
- Deterministic heuristics: floor findings written when the LLM misses a
  high-signal keyword; skipped when the LLM already covered the type
- Defensibility grading (actual/high/medium/low), severity derived from it,
  and the legacy `severity` fallback for providers that predate the field
- Amounts taken only from the document, never computed; assessment periods
  resolved from the rules registry and time-barring added as a mitigation
- Document filtering via document_ids (None/set()/explicit set)
- Idempotency: no accumulation on re-run
- AgentRun lifecycle: created, timestamped, completed/failed
- Edge cases: deal not found, empty text, no matching docs, wrapper
"""
import json
import pytest
from sqlalchemy.orm import Session

from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from app.models.agent_finding import AgentFinding
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.red_flag import Severity
from packages.agents.tax_agent import (
    TaxAgent,
    run_tax_analysis,
    AGENT_NAME,
    _TAX_DOC_KEYWORDS,
    _VALID_FINDING_TYPES,
    _VALID_DEFENSIBILITY,
    _HEURISTIC_CONFIDENCE,
)
from packages.agents.deal_analysis_agent import (
    FakeLLMProvider,
    LLMProvider,
    set_llm_provider,
)

# ── Module-level fixtures ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def use_fake_llm():
    """Inject FakeLLMProvider globally for every test in this module."""
    set_llm_provider(FakeLLMProvider())
    yield
    set_llm_provider(None)


# ── Sample document texts ──────────────────────────────────────────────────

_TAX_ASSESSMENT_DOC = """\
AGENZIA DELLE ENTRATE — DIREZIONE PROVINCIALE DI MILANO
AVVISO DI ACCERTAMENTO n. T9B012345678/2024

Contribuente: TargetCo S.p.A. — P.IVA 01234567890
Periodo d'imposta: 2022

Dall'attività di controllo è emersa una maggiore IRES dovuta pari a
Euro 240.000, oltre sanzioni e interessi. Avverso il presente avviso è
ammesso ricorso alla Corte di Giustizia Tributaria di primo grado entro
sessanta giorni dalla notifica.
"""

_INSTALMENT_PLAN_DOC = """\
AGENZIA DELLE ENTRATE-RISCOSSIONE
Piano di rateizzazione n. 2024/000123

Con riferimento alla cartella di pagamento n. 068 2023 00012345 67,
si comunica l'accoglimento dell'istanza di rateizzazione in 72 rate
mensili per un importo complessivo di Euro 85.000.
"""

_NON_TAX_DOC = """\
SERVICE AGREEMENT
This Service Agreement is entered into between Alpha Corp ("Client") and Beta
Services Ltd ("Provider").

1. Services: Provider agrees to deliver software development services.
2. Term: This agreement begins on 1 January 2025 and runs for 12 months.
3. Payment: Client shall pay monthly invoices within 30 days of receipt.
4. Termination: Either party may terminate with 30 days written notice.
"""


# ── Test helpers ────────────────────────────────────────────────────────────


def _make_doc(
    db: Session,
    deal: Deal,
    *,
    filename: str = "avviso_di_accertamento_2022.txt",
    raw_text: str = _TAX_ASSESSMENT_DOC,
    status: DocumentStatus = DocumentStatus.processed,
    file_size: int = 2048,
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


# ── Fake LLM helpers ────────────────────────────────────────────────────────


class _ZeroFindingLLM(LLMProvider):
    """Always returns an empty finding array — heuristics still apply."""

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        return json.dumps([])


class _SingleFindingLLM(LLMProvider):
    """Returns exactly one tax finding — used in idempotency tests."""

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        if "ANALYZE TAX MATTERS" in prompt.upper():
            return json.dumps([{
                "finding_type": "tax_regime",
                "title": "Single Finding",
                "description": "Consolidato fiscale election in force since 2021.",
                "severity": "low",
                "confidence": 0.75,
            }])
        return json.dumps([])


class _UnknownFindingTypeLLM(LLMProvider):
    """Returns a finding with an invalid finding_type — coercion test."""

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        if "ANALYZE TAX MATTERS" in prompt.upper():
            return json.dumps([{
                "finding_type": "totally_invalid_type",
                "title": "Some Finding",
                "description": "Some description.",
                "severity": "medium",
                "confidence": 0.7,
            }])
        return json.dumps([])


class _RaisingLLM(LLMProvider):
    """Always raises RuntimeError — used in AgentRun failure tests."""

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        raise RuntimeError("LLM unavailable")


# ═══════════════════════════════════════════════════════════════════════════
# Test classes
# ═══════════════════════════════════════════════════════════════════════════


class TestTaxFindingExtraction:
    """AgentFinding rows are created with correct field values."""

    def test_agent_findings_created_for_tax_doc(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        findings = _agent_findings(db, test_deal)
        # FakeLLMProvider returns 3 findings; the doc text contains
        # "avviso di accertamento" but the LLM covers tax_assessment,
        # so no heuristic floor row is added for it.
        assert len(findings) == 3

    def test_finding_agent_name(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.agent_name == AGENT_NAME

    def test_finding_deal_id_and_document_id(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.deal_id == test_deal.id
            assert f.document_id == doc.id

    def test_finding_categories_are_finding_types(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        categories = {f.category for f in _agent_findings(db, test_deal)}
        # FakeLLMProvider returns tax_assessment, tax_debt, tax_regime
        assert categories == {"tax_assessment", "tax_debt", "tax_regime"}

    def test_finding_severities(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        severities = {f.severity for f in _agent_findings(db, test_deal)}
        assert Severity.low in severities
        assert Severity.medium in severities
        assert Severity.high in severities

    def test_finding_titles_and_descriptions_populated(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.title
            assert f.description

    def test_structured_payload_json_shape(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            payload = f.structured_payload_json
            assert payload["finding_type"] in _VALID_FINDING_TYPES
            assert payload["document_id"] == doc.id
            assert payload["filename"] == doc.filename
            assert payload["source"] == "llm"

    def test_finding_category_matches_payload_finding_type(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.category == f.structured_payload_json["finding_type"]

    def test_finding_title_truncated_to_100_chars(self, db: Session, test_deal: Deal):
        class _LongTitleLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "ANALYZE TAX MATTERS" in prompt.upper():
                    return json.dumps([{
                        "finding_type": "tax_regime",
                        "title": "X" * 200,
                        "description": "desc",
                        "severity": "low",
                        "confidence": 0.5,
                    }])
                return json.dumps([])

        doc = _make_doc(db, test_deal, raw_text=_NON_TAX_DOC)
        TaxAgent(provider=_LongTitleLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        for f in _agent_findings(db, test_deal):
            assert len(f.title) <= 100


class TestFindingTypeCoercion:
    """Invalid finding_type values are coerced to 'other_tax'."""

    def test_unknown_finding_type_coerced(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal, raw_text=_NON_TAX_DOC)
        TaxAgent(provider=_UnknownFindingTypeLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].category == "other_tax"

    def test_critical_severity_normalized_to_high(self, db: Session, test_deal: Deal):
        class _CriticalSeverityLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "ANALYZE TAX MATTERS" in prompt.upper():
                    return json.dumps([{
                        "finding_type": "tax_assessment",
                        "title": "Assessment",
                        "description": "desc",
                        "severity": "critical",
                        "confidence": 0.5,
                    }])
                return json.dumps([])

        doc = _make_doc(db, test_deal, raw_text=_NON_TAX_DOC)
        TaxAgent(provider=_CriticalSeverityLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].severity == Severity.high

    def test_unknown_severity_coerced_to_medium(self, db: Session, test_deal: Deal):
        class _BadSeverityLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "ANALYZE TAX MATTERS" in prompt.upper():
                    return json.dumps([{
                        "finding_type": "tax_regime",
                        "title": "Some finding",
                        "description": "desc",
                        "severity": "banana",
                        "confidence": 0.5,
                    }])
                return json.dumps([])

        doc = _make_doc(db, test_deal, raw_text=_NON_TAX_DOC)
        TaxAgent(provider=_BadSeverityLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].severity == Severity.medium


class TestHeuristicFloor:
    """Deterministic keyword heuristics backstop the LLM."""

    def test_floor_finding_written_when_llm_returns_nothing(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)  # contains "avviso di accertamento"
        TaxAgent(provider=_ZeroFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        f = findings[0]
        assert f.category == "tax_assessment"
        assert f.severity == Severity.high
        assert f.confidence == _HEURISTIC_CONFIDENCE
        assert f.structured_payload_json["source"] == "heuristic"

    def test_floor_skipped_when_llm_covers_the_type(
        self, db: Session, test_deal: Deal
    ):
        """FakeLLMProvider already returns a tax_assessment finding — the
        heuristic for 'avviso di accertamento' must not duplicate it."""
        doc = _make_doc(db, test_deal)
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["heuristic_findings_count"] == 0
        categories = [f.category for f in _agent_findings(db, test_deal)]
        assert categories.count("tax_assessment") == 1

    def test_instalment_plan_keywords_produce_two_floors(
        self, db: Session, test_deal: Deal
    ):
        """'cartella di pagamento' (tax_debt) + 'rateizzazione' (tax_debt):
        only ONE floor per finding_type is written."""
        doc = _make_doc(
            db, test_deal,
            filename="piano.txt",
            raw_text=_INSTALMENT_PLAN_DOC,
        )
        TaxAgent(provider=_ZeroFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].category == "tax_debt"
        assert findings[0].severity == Severity.high  # cartella wins (listed first)

    def test_no_floor_for_non_tax_text(self, db: Session, test_deal: Deal):
        doc = _make_doc(
            db, test_deal, filename="service.txt", raw_text=_NON_TAX_DOC
        )
        result = TaxAgent(provider=_ZeroFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert result["agent_findings_count"] == 0
        assert result["heuristic_findings_count"] == 0

    def test_heuristic_count_in_result(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = TaxAgent(provider=_ZeroFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert result["heuristic_findings_count"] == 1
        assert result["agent_findings_count"] == 1


class TestReturnValue:
    """The dict returned by TaxAgent.run() has the correct shape."""

    def test_return_value_keys(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        expected_keys = {
            "deal_id",
            "documents_analyzed",
            "agent_findings_count",
            "heuristic_findings_count",
            "findings_by_severity",
            "findings_by_defensibility",
            "findings_by_finding_type",
            "quantified_findings_count",
            "fiscal_years_covered",
            "findings_by_document",
        }
        assert set(result.keys()) == expected_keys

    def test_counts_one_doc(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["deal_id"] == test_deal.id
        assert result["documents_analyzed"] == 1
        assert result["agent_findings_count"] == 3

    def test_findings_by_severity_counts(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        by_sev = result["findings_by_severity"]
        assert by_sev == {"low": 1, "medium": 1, "high": 1}

    def test_findings_by_finding_type_counts(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        by_type = result["findings_by_finding_type"]
        assert set(by_type.keys()) == _VALID_FINDING_TYPES
        assert by_type["tax_assessment"] == 1
        assert by_type["tax_debt"] == 1
        assert by_type["tax_regime"] == 1
        assert by_type["transfer_pricing"] == 0

    def test_findings_by_document_shape(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        assert len(result["findings_by_document"]) == 1
        entry = result["findings_by_document"][0]
        assert entry["document_id"] == doc.id
        assert entry["filename"] == doc.filename
        assert entry["finding_count"] == 3

    def test_empty_doc_list_returns_zero_counts(self, db: Session, test_deal: Deal):
        result = TaxAgent().run(test_deal.id, db, document_ids=set())
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0
        assert result["findings_by_document"] == []


class TestAutoDetection:
    """The agent auto-detects tax documents when document_ids=None."""

    def test_detected_by_filename(self, db: Session, test_deal: Deal):
        doc = _make_doc(
            db, test_deal,
            filename="avviso_di_accertamento_2022.pdf",
            raw_text="Some content without keywords.",
        )
        result = TaxAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1
        assert doc.id in {e["document_id"] for e in result["findings_by_document"]}

    def test_detected_by_text(self, db: Session, test_deal: Deal):
        doc = _make_doc(
            db, test_deal,
            filename="documento.txt",           # no keyword in filename
            raw_text=_INSTALMENT_PLAN_DOC,      # keywords in first 1500 chars
        )
        result = TaxAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1

    def test_english_keyword_detected(self, db: Session, test_deal: Deal):
        doc = _make_doc(
            db, test_deal,
            filename="fy2023_tax_return.pdf",
            raw_text="Annual corporate income figures.",
        )
        result = TaxAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1

    def test_keyword_only_after_1500_chars_not_detected(
        self, db: Session, test_deal: Deal
    ):
        raw_text = "x" * 1501 + " avviso di accertamento"
        _make_doc(db, test_deal, filename="misc.txt", raw_text=raw_text)
        result = TaxAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 0

    def test_non_tax_doc_excluded(self, db: Session, test_deal: Deal):
        _make_doc(
            db, test_deal, filename="service_agreement.txt", raw_text=_NON_TAX_DOC
        )
        result = TaxAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0

    def test_routed_ids_unioned_with_auto_detection(
        self, db: Session, test_deal: Deal
    ):
        """A doc routing classified as tax is analysed even without keywords."""
        tax_doc = _make_doc(db, test_deal)  # detected by keywords
        routed_doc = _make_doc(
            db, test_deal,
            filename="allegato_3.txt",
            raw_text="Prospetto riepilogativo importi dovuti.",  # no keyword
        )
        result = TaxAgent().run(
            test_deal.id, db, routed_document_ids={routed_doc.id}
        )
        analysed = {e["document_id"] for e in result["findings_by_document"]}
        assert analysed == {tax_doc.id, routed_doc.id}

    def test_explicit_ids_bypass_auto_detection(self, db: Session, test_deal: Deal):
        non_tax = _make_doc(
            db, test_deal, filename="service.txt", raw_text=_NON_TAX_DOC
        )
        result = TaxAgent().run(test_deal.id, db, document_ids={non_tax.id})
        assert result["documents_analyzed"] == 1

    def test_pending_doc_excluded(self, db: Session, test_deal: Deal):
        _make_doc(db, test_deal, status=DocumentStatus.pending)
        result = TaxAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 0


class TestIdempotency:
    """Re-running the agent produces clean results with no row accumulation."""

    def test_no_accumulation_on_rerun(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        agent = TaxAgent()
        agent.run(test_deal.id, db, document_ids={doc.id})
        agent.run(test_deal.id, db, document_ids={doc.id})
        assert len(_agent_findings(db, test_deal)) == 3  # not 6

    def test_previous_agent_findings_cleared(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal, raw_text=_NON_TAX_DOC)
        TaxAgent(provider=_SingleFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert len(_agent_findings(db, test_deal)) == 1
        TaxAgent(provider=FakeLLMProvider()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert len(_agent_findings(db, test_deal)) == 3  # exactly 3, not 1 + 3

    def test_previous_agent_run_deleted(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        assert len(_agent_runs(db, test_deal)) == 1

    def test_other_agents_findings_not_touched(self, db: Session, test_deal: Deal):
        other_finding = AgentFinding(
            deal_id=test_deal.id,
            agent_name="some_other_agent",
            category="classification",
            title="Other agent finding",
            description="This is from another agent.",
            severity=Severity.low,
        )
        db.add(other_finding)
        db.commit()

        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        surviving = (
            db.query(AgentFinding)
            .filter(AgentFinding.agent_name == "some_other_agent")
            .all()
        )
        assert len(surviving) == 1


class TestAgentRunLifecycle:
    """AgentRun records are created and tracked correctly."""

    def test_agent_run_created_and_completed(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        runs = _agent_runs(db, test_deal)
        assert len(runs) == 1
        run = runs[0]
        assert run.agent_name == AGENT_NAME
        assert run.status == AgentRunStatus.completed
        assert run.started_at is not None
        assert run.completed_at is not None
        assert run.completed_at >= run.started_at

    def test_agent_run_failed_on_llm_error(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        with pytest.raises(RuntimeError, match="LLM unavailable"):
            TaxAgent(provider=_RaisingLLM()).run(
                test_deal.id, db, document_ids={doc.id}
            )
        run = _agent_runs(db, test_deal)[0]
        assert run.status == AgentRunStatus.failed
        assert "LLM unavailable" in run.error_message

    def test_failed_run_creates_no_findings(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        with pytest.raises(RuntimeError):
            TaxAgent(provider=_RaisingLLM()).run(
                test_deal.id, db, document_ids={doc.id}
            )
        assert len(_agent_findings(db, test_deal)) == 0


class TestEdgeCases:
    """Boundary conditions and convenience wrapper."""

    def test_deal_not_found_raises_value_error(self, db: Session):
        with pytest.raises(ValueError, match="99999"):
            TaxAgent().run(99999, db)

    def test_doc_with_no_text_skipped(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal, raw_text="")
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0

    def test_llm_returns_non_list_handled_gracefully(
        self, db: Session, test_deal: Deal
    ):
        class _BadJsonLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                return '{"not": "an array"}'

        doc = _make_doc(db, test_deal, raw_text=_NON_TAX_DOC)
        result = TaxAgent(provider=_BadJsonLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert result["agent_findings_count"] == 0

    def test_llm_returns_invalid_json_handled_gracefully(
        self, db: Session, test_deal: Deal
    ):
        class _GarbageLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                return "this is not json at all"

        doc = _make_doc(db, test_deal, raw_text=_NON_TAX_DOC)
        result = TaxAgent(provider=_GarbageLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert result["agent_findings_count"] == 0

    def test_run_tax_analysis_convenience_wrapper(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        result = run_tax_analysis(test_deal.id, db, document_ids={doc.id})
        assert result["deal_id"] == test_deal.id
        assert result["agent_findings_count"] == 3

    def test_run_tax_analysis_uses_supplied_provider(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal, raw_text=_NON_TAX_DOC)
        result = run_tax_analysis(
            test_deal.id, db, document_ids={doc.id}, provider=_ZeroFindingLLM()
        )
        assert result["agent_findings_count"] == 0

    def test_agent_name_constant(self):
        assert AGENT_NAME == "tax_analysis"
        assert TaxAgent.AGENT_NAME == "tax_analysis"

    def test_tax_doc_keywords_not_empty(self):
        assert len(_TAX_DOC_KEYWORDS) > 0


class TestPipelineIntegration:
    """TaxAgent runs as stage 4c of the orchestrated pipeline."""

    def test_pipeline_includes_tax_stage(self, db: Session, test_deal: Deal):
        from packages.agents.orchestrator import run_deal_analysis_pipeline

        _make_doc(db, test_deal)
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert "tax_analysis" in result["stages"]
        stage = result["stages"]["tax_analysis"]
        assert "error" not in stage
        # The tax doc is auto-detected by keywords even though the fake
        # router classifies everything as "contract".
        assert stage["documents_analyzed"] == 1
        assert stage["agent_findings_count"] == 3

    def test_tax_findings_reach_the_aggregator_context(
        self, db: Session, test_deal: Deal
    ):
        """Tax AgentFindings are gathered by the red-flag aggregator."""
        from packages.agents.red_flag_aggregator import RedFlagAggregationAgent

        doc = _make_doc(db, test_deal)
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        agg = RedFlagAggregationAgent(provider=_ZeroFindingLLM())
        doc_map = agg._get_documents(db, test_deal.id)
        agent_findings = agg._gather_agent_findings(db, test_deal.id)
        assert any(f.agent_name == AGENT_NAME for f in agent_findings)

        context = agg._build_context_text([], agent_findings, doc_map)
        assert "tax_assessment" in context


# ── Defensibility, amounts and the rules registry ──────────────────────────


def _single_finding_provider(**overrides) -> LLMProvider:
    """A stub returning exactly one tax finding, with fields overridden."""
    item = {
        "finding_type": "tax_assessment",
        "tax_kind": "ires",
        "title": "Assessment",
        "description": "An assessment was notified.",
        "confidence": 0.9,
    }
    item.update(overrides)

    class _Stub(LLMProvider):
        def complete(self, prompt: str, max_tokens: int = 4096) -> str:
            if "ANALYZE TAX MATTERS" in prompt.upper():
                return json.dumps([item])
            return "[]"

    return _Stub()


class TestDefensibility:
    """`defensibility` grades the position; severity is derived from it."""

    @pytest.mark.parametrize(
        "grade,expected",
        [
            ("actual", Severity.high),
            ("high", Severity.high),
            ("medium", Severity.medium),
            ("low", Severity.low),
        ],
    )
    def test_grade_drives_severity(
        self, db: Session, test_deal: Deal, grade: str, expected: Severity
    ):
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider(defensibility=grade))
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        finding = _agent_findings(db, test_deal)[0]
        assert finding.severity == expected
        assert finding.structured_payload_json["defensibility"] == grade

    def test_actual_is_recorded_distinctly_from_high(
        self, db: Session, test_deal: Deal
    ):
        """`actual` and `high` share a severity but must stay tellable apart."""
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider(defensibility="actual"))
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        assert result["findings_by_defensibility"]["actual"] == 1
        assert result["findings_by_defensibility"]["high"] == 0
        assert result["findings_by_severity"]["high"] == 1

    def test_legacy_severity_used_when_grade_absent(
        self, db: Session, test_deal: Deal
    ):
        """Providers predating the field keep working via `severity`."""
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider(severity="high"))
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        finding = _agent_findings(db, test_deal)[0]
        assert finding.structured_payload_json["defensibility"] == "high"
        assert finding.severity == Severity.high

    def test_unknown_grade_falls_back_to_medium(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider(defensibility="catastrophic"))
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        finding = _agent_findings(db, test_deal)[0]
        assert finding.structured_payload_json["defensibility"] == "medium"
        assert finding.severity == Severity.medium

    def test_every_grade_is_counted(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        assert set(result["findings_by_defensibility"]) == set(_VALID_DEFENSIBILITY)


class TestAmounts:
    """Amounts come from the document or not at all."""

    def test_amount_stated_by_document_is_kept(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider(amount_eur=240000))
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload["amount_eur"] == 240000
        assert payload["amount_source"] == "document"
        assert result["quantified_findings_count"] == 1

    def test_missing_amount_is_marked_not_stated(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider())
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload["amount_eur"] is None
        assert payload["amount_source"] == "not_stated"
        assert result["quantified_findings_count"] == 0

    @pytest.mark.parametrize("bad", ["circa 240k", -5, True, None, {}])
    def test_unusable_amount_becomes_no_amount(
        self, db: Session, test_deal: Deal, bad
    ):
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider(amount_eur=bad))
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload["amount_eur"] is None


class TestFiscalYearsAndAssessmentPeriods:
    """Fiscal years are validated; the registry resolves when they close."""

    def test_years_normalized_and_deduplicated(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        set_llm_provider(
            _single_finding_provider(fiscal_years=[2022, "2021", 2022, 99, "x"])
        )
        result = TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload["fiscal_years"] == [2021, 2022]
        assert result["fiscal_years_covered"] == [2021, 2022]

    def test_assessment_period_resolved_per_year(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider(fiscal_years=[2022]))
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        periods = _agent_findings(db, test_deal)[0].structured_payload_json[
            "assessment_periods"
        ]
        assert len(periods) == 1
        assert periods[0]["fiscal_year"] == 2022
        assert periods[0]["expiry"] == "2028-12-31"
        assert periods[0]["time_barred"] is False
        assert "L. 208/2015" in periods[0]["citation"]

    def test_time_barred_year_adds_a_mitigation(
        self, db: Session, test_deal: Deal
    ):
        """A closed year is a mitigation the model cannot work out itself."""
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider(fiscal_years=[2004]))
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload["assessment_periods"][0]["time_barred"] is True
        assert "time_barred" in payload["mitigating_factors"]

    def test_open_year_adds_no_mitigation(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider(fiscal_years=[2022]))
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload["mitigating_factors"] == []


class TestPayloadFields:
    """The remaining structured fields."""

    def test_tax_kind_kept_and_unknown_coerced(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        set_llm_provider(_single_finding_provider(tax_kind="iva"))
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        assert _agent_findings(db, test_deal)[0].structured_payload_json[
            "tax_kind"
        ] == "iva"

        set_llm_provider(_single_finding_provider(tax_kind="patrimoniale"))
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        assert _agent_findings(db, test_deal)[0].structured_payload_json[
            "tax_kind"
        ] == "altro"

    def test_legal_basis_kept_or_null(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        set_llm_provider(
            _single_finding_provider(legal_basis="art. 39 D.P.R. 600/1973")
        )
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        assert (
            _agent_findings(db, test_deal)[0].structured_payload_json[
                "legal_basis"
            ]
            == "art. 39 D.P.R. 600/1973"
        )

        set_llm_provider(_single_finding_provider(legal_basis=""))
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})
        assert (
            _agent_findings(db, test_deal)[0].structured_payload_json[
                "legal_basis"
            ]
            is None
        )

    def test_mitigations_normalized(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        set_llm_provider(
            _single_finding_provider(
                fiscal_years=[2022],
                mitigating_factors=["Already Paid", "already_paid", 42],
            )
        )
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload["mitigating_factors"] == ["already_paid", "42"]

    def test_non_dict_items_are_skipped(self, db: Session, test_deal: Deal):
        class _Stub(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 4096) -> str:
                if "ANALYZE TAX MATTERS" in prompt.upper():
                    return json.dumps(["nonsense", 7, {"finding_type": "tax_debt"}])
                return "[]"

        # A document with no heuristic keyword, so nothing but the parsed
        # item can reach the findings list.
        doc = _make_doc(db, test_deal, raw_text=_NON_TAX_DOC)
        set_llm_provider(_Stub())
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        findings = _agent_findings(db, test_deal)
        assert [f.category for f in findings] == ["tax_debt"]

    def test_heuristic_floor_carries_the_new_fields(
        self, db: Session, test_deal: Deal
    ):
        """Floor findings share the payload shape, with nothing invented."""
        class _Silent(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 4096) -> str:
                return "[]"

        doc = _make_doc(db, test_deal)
        set_llm_provider(_Silent())
        TaxAgent().run(test_deal.id, db, document_ids={doc.id})

        payload = _agent_findings(db, test_deal)[0].structured_payload_json
        assert payload["source"] == "heuristic"
        assert payload["defensibility"] in _VALID_DEFENSIBILITY
        assert payload["amount_eur"] is None
        assert payload["amount_source"] == "not_stated"
        assert payload["fiscal_years"] == []
        assert payload["assessment_periods"] == []
