"""Tests for FinancialAgent — financial documentary review.

Covers:
- Finding extraction: AgentFinding rows created with correct fields
  (category=finding_type, severity, confidence, title, description,
   structured_payload_json)
- Invalid finding_type values coerced to 'other_financial'
- Return value shape and aggregation counts
- Auto-detection of financial documents via keyword matching
  (filename, raw_text[:1500]) and union with routed_document_ids
- Deterministic heuristics: floor findings written when the LLM misses a
  high-signal keyword; skipped when the LLM already covered the type;
  article numbers only match with an "art." prefix or "c.c." suffix
- Document filtering via document_ids (None/set()/explicit set)
- Idempotency: no accumulation on re-run
- AgentRun lifecycle: created, timestamped, completed/failed
- Edge cases: deal not found, empty text, no matching docs, wrapper
- Pipeline integration: stage 4d and hand-off to the red-flag aggregator
"""
import json
import pytest
from sqlalchemy.orm import Session

from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from app.models.agent_finding import AgentFinding
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.red_flag import Severity
from packages.agents.financial_agent import (
    FinancialAgent,
    run_financial_analysis,
    AGENT_NAME,
    _FINANCIAL_DOC_KEYWORDS,
    _VALID_FINDING_TYPES,
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

# Deliberately contains detection keywords but NO heuristic keywords, so
# the floor logic contributes nothing and counts stay predictable.
_FINANCIAL_STATEMENTS_DOC = """\
BILANCIO D'ESERCIZIO AL 31 DICEMBRE 2024
TargetCo S.p.A. — P.IVA 01234567890

STATO PATRIMONIALE
Attivo circolante: Euro 4.120.000
Immobilizzazioni: Euro 2.350.000
Patrimonio netto: Euro 1.880.000

CONTO ECONOMICO
Valore della produzione: Euro 8.400.000
Risultato d'esercizio: Euro 210.000

NOTA INTEGRATIVA
I crediti verso clienti sono iscritti al presumibile valore di realizzo.
Le riserve comprendono un versamento in conto capitale di Euro 150.000.
"""

_GOING_CONCERN_DOC = """\
RELAZIONE DELLA SOCIETÀ DI REVISIONE
TargetCo S.p.A. — Esercizio chiuso al 31 dicembre 2024

Segnaliamo che la società presenta perdite ricorrenti che possono far
sorgere dubbi significativi sulla continuità aziendale. Gli amministratori
hanno predisposto un piano di risanamento supportato da una lettera di
patronage del socio di maggioranza.
"""

_CAPITAL_LOSS_DOC = """\
VERBALE DI ASSEMBLEA — TargetCo S.r.l.
Approvazione della situazione patrimoniale ex art. 2482-bis c.c.

L'assemblea prende atto che le perdite risultanti dalla situazione
patrimoniale al 30 giugno 2025 superano un terzo del capitale sociale.
L'assemblea delibera il rinvio a nuovo esercizio.
"""

_NON_FINANCIAL_DOC = """\
SERVICE AGREEMENT
This Service Agreement is entered into between Alpha Corp ("Client") and Beta
Services Ltd ("Provider").

1. Services: Provider agrees to deliver software development services.
2. Term: This agreement begins on 1 January 2025 and runs for 12 months.
3. Termination: Either party may terminate with 30 days written notice.
"""


# ── Test helpers ────────────────────────────────────────────────────────────


def _make_doc(
    db: Session,
    deal: Deal,
    *,
    filename: str = "bilancio_2024.txt",
    raw_text: str = _FINANCIAL_STATEMENTS_DOC,
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
    """Returns exactly one financial finding — used in idempotency tests."""

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        if "ANALYZE FINANCIAL STATEMENTS" in prompt.upper():
            return json.dumps([{
                "finding_type": "equity_position",
                "title": "Single Finding",
                "description": "Share capital fully paid at Euro 1.000.000.",
                "severity": "low",
                "confidence": 0.75,
            }])
        return json.dumps([])


class _UnknownFindingTypeLLM(LLMProvider):
    """Returns a finding with an invalid finding_type — coercion test."""

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        if "ANALYZE FINANCIAL STATEMENTS" in prompt.upper():
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


class TestFinancialFindingExtraction:
    """AgentFinding rows are created with correct field values."""

    def test_agent_findings_created_for_financial_doc(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        # FakeLLMProvider returns 3 findings; the sample statements contain
        # no heuristic keyword, so no floor row is added.
        assert len(_agent_findings(db, test_deal)) == 4

    def test_finding_agent_name(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.agent_name == AGENT_NAME

    def test_finding_deal_id_and_document_id(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.deal_id == test_deal.id
            assert f.document_id == doc.id

    def test_finding_categories_are_finding_types(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        categories = {f.category for f in _agent_findings(db, test_deal)}
        assert categories == {
            "auditor_opinion",
            "covenant",
            "debt_like_item",
            "equity_position",
        }

    def test_finding_severities(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        severities = {f.severity for f in _agent_findings(db, test_deal)}
        assert severities == {Severity.low, Severity.medium, Severity.high}

    def test_finding_titles_and_descriptions_populated(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.title
            assert f.description

    def test_structured_payload_json_shape(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
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
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.category == f.structured_payload_json["finding_type"]

    def test_finding_title_truncated_to_100_chars(self, db: Session, test_deal: Deal):
        class _LongTitleLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "ANALYZE FINANCIAL STATEMENTS" in prompt.upper():
                    return json.dumps([{
                        "finding_type": "equity_position",
                        "title": "X" * 200,
                        "description": "desc",
                        "severity": "low",
                        "confidence": 0.5,
                    }])
                return json.dumps([])

        doc = _make_doc(db, test_deal, raw_text=_NON_FINANCIAL_DOC)
        FinancialAgent(provider=_LongTitleLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        for f in _agent_findings(db, test_deal):
            assert len(f.title) <= 100


class TestFindingTypeCoercion:
    """Invalid finding_type values are coerced to 'other_financial'."""

    def test_unknown_finding_type_coerced(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal, raw_text=_NON_FINANCIAL_DOC)
        FinancialAgent(provider=_UnknownFindingTypeLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].category == "other_financial"

    def test_critical_severity_normalized_to_high(self, db: Session, test_deal: Deal):
        class _CriticalSeverityLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "ANALYZE FINANCIAL STATEMENTS" in prompt.upper():
                    return json.dumps([{
                        "finding_type": "going_concern",
                        "title": "Going concern",
                        "description": "desc",
                        "severity": "critical",
                        "confidence": 0.5,
                    }])
                return json.dumps([])

        doc = _make_doc(db, test_deal, raw_text=_NON_FINANCIAL_DOC)
        FinancialAgent(provider=_CriticalSeverityLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].severity == Severity.high

    def test_unknown_severity_coerced_to_medium(self, db: Session, test_deal: Deal):
        class _BadSeverityLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "ANALYZE FINANCIAL STATEMENTS" in prompt.upper():
                    return json.dumps([{
                        "finding_type": "equity_position",
                        "title": "Some finding",
                        "description": "desc",
                        "severity": "banana",
                        "confidence": 0.5,
                    }])
                return json.dumps([])

        doc = _make_doc(db, test_deal, raw_text=_NON_FINANCIAL_DOC)
        FinancialAgent(provider=_BadSeverityLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].severity == Severity.medium


class TestHeuristicFloor:
    """Deterministic keyword heuristics backstop the LLM."""

    def test_going_concern_floor_written_when_llm_returns_nothing(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(
            db, test_deal,
            filename="relazione_revisione.txt",
            raw_text=_GOING_CONCERN_DOC,
        )
        FinancialAgent(provider=_ZeroFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        f = findings[0]
        assert f.category == "going_concern"
        assert f.severity == Severity.high
        assert f.confidence == _HEURISTIC_CONFIDENCE
        assert f.structured_payload_json["source"] == "heuristic"

    def test_capital_loss_floor_from_article_reference(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(
            db, test_deal,
            filename="verbale_assemblea.txt",
            raw_text=_CAPITAL_LOSS_DOC,
        )
        FinancialAgent(provider=_ZeroFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].category == "capital_loss"
        assert findings[0].severity == Severity.high

    def test_bare_article_number_does_not_trigger_floor(
        self, db: Session, test_deal: Deal
    ):
        """A figure such as 2446 in the accounts must not be read as art. 2446."""
        doc = _make_doc(
            db, test_deal,
            filename="bilancio_2024.txt",
            raw_text=(
                "BILANCIO D'ESERCIZIO\n"
                "STATO PATRIMONIALE\n"
                "Crediti verso clienti: Euro 2446\n"
                "Debiti verso fornitori: Euro 2447\n"
            ),
        )
        result = FinancialAgent(provider=_ZeroFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert result["heuristic_findings_count"] == 0

    def test_floor_skipped_when_llm_covers_the_type(
        self, db: Session, test_deal: Deal
    ):
        """FakeLLMProvider returns an auditor_opinion finding — the
        'giudizio con rilievi' heuristic must not duplicate it."""
        doc = _make_doc(
            db, test_deal,
            filename="relazione.txt",
            raw_text=(
                "RELAZIONE DI REVISIONE\n"
                "Abbiamo espresso un giudizio con rilievi sul bilancio.\n"
            ),
        )
        result = FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        categories = [f.category for f in _agent_findings(db, test_deal)]
        assert categories.count("auditor_opinion") == 1
        assert result["heuristic_findings_count"] == 0

    def test_one_floor_per_finding_type(self, db: Session, test_deal: Deal):
        """Several keywords mapping to capital_loss produce a single floor."""
        doc = _make_doc(
            db, test_deal,
            filename="verbale.txt",
            raw_text=(
                "SITUAZIONE PATRIMONIALE\n"
                "Perdite rilevanti ai sensi dell'art. 2446 c.c. e, ove non "
                "ripianate, dell'art. 2447 c.c.\n"
            ),
        )
        FinancialAgent(provider=_ZeroFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].category == "capital_loss"

    def test_llm_and_floor_combine_on_same_document(
        self, db: Session, test_deal: Deal
    ):
        """FakeLLM's 3 findings plus a going_concern floor = 4."""
        doc = _make_doc(
            db, test_deal,
            filename="relazione_revisione.txt",
            raw_text=_GOING_CONCERN_DOC,
        )
        result = FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["agent_findings_count"] == 5
        assert result["heuristic_findings_count"] == 1
        categories = {f.category for f in _agent_findings(db, test_deal)}
        assert "going_concern" in categories

    def test_no_floor_for_non_financial_text(self, db: Session, test_deal: Deal):
        doc = _make_doc(
            db, test_deal, filename="service.txt", raw_text=_NON_FINANCIAL_DOC
        )
        result = FinancialAgent(provider=_ZeroFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert result["agent_findings_count"] == 0
        assert result["heuristic_findings_count"] == 0


class TestReturnValue:
    """The dict returned by FinancialAgent.run() has the correct shape."""

    def test_return_value_keys(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        expected_keys = {
            "deal_id",
            "documents_analyzed",
            "agent_findings_count",
            "heuristic_findings_count",
            "findings_by_severity",
            "findings_by_finding_type",
            "findings_by_document",
        }
        assert set(result.keys()) == expected_keys

    def test_counts_one_doc(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["deal_id"] == test_deal.id
        assert result["documents_analyzed"] == 1
        assert result["agent_findings_count"] == 4

    def test_findings_by_severity_counts(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["findings_by_severity"] == {"low": 1, "medium": 1, "high": 2}

    def test_findings_by_finding_type_counts(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        by_type = result["findings_by_finding_type"]
        assert set(by_type.keys()) == _VALID_FINDING_TYPES
        assert by_type["auditor_opinion"] == 1
        assert by_type["covenant"] == 1
        assert by_type["equity_position"] == 1
        assert by_type["going_concern"] == 0

    def test_findings_by_document_shape(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        assert len(result["findings_by_document"]) == 1
        entry = result["findings_by_document"][0]
        assert entry["document_id"] == doc.id
        assert entry["filename"] == doc.filename
        assert entry["finding_count"] == 4

    def test_empty_doc_list_returns_zero_counts(self, db: Session, test_deal: Deal):
        result = FinancialAgent().run(test_deal.id, db, document_ids=set())
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0
        assert result["findings_by_document"] == []


class TestAutoDetection:
    """The agent auto-detects financial documents when document_ids=None."""

    def test_detected_by_filename(self, db: Session, test_deal: Deal):
        doc = _make_doc(
            db, test_deal,
            filename="bilancio-consolidato-2024.pdf",
            raw_text="Contenuto senza parole chiave.",
        )
        result = FinancialAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1
        assert doc.id in {e["document_id"] for e in result["findings_by_document"]}

    def test_detected_by_text(self, db: Session, test_deal: Deal):
        _make_doc(
            db, test_deal,
            filename="allegato.txt",              # no keyword in filename
            raw_text=_FINANCIAL_STATEMENTS_DOC,   # keywords in first 1500 chars
        )
        result = FinancialAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1

    def test_english_keyword_detected(self, db: Session, test_deal: Deal):
        _make_doc(
            db, test_deal,
            filename="fy2024_financial_statements.pdf",
            raw_text="Consolidated figures for the year.",
        )
        result = FinancialAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1

    def test_keyword_only_after_1500_chars_not_detected(
        self, db: Session, test_deal: Deal
    ):
        raw_text = "x" * 1501 + " nota integrativa"
        _make_doc(db, test_deal, filename="misc.txt", raw_text=raw_text)
        result = FinancialAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 0

    def test_non_financial_doc_excluded(self, db: Session, test_deal: Deal):
        _make_doc(
            db, test_deal, filename="service_agreement.txt",
            raw_text=_NON_FINANCIAL_DOC,
        )
        result = FinancialAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0

    def test_routed_ids_unioned_with_auto_detection(
        self, db: Session, test_deal: Deal
    ):
        """A doc routing classified as a financial statement is analysed
        even without keywords."""
        fin_doc = _make_doc(db, test_deal)  # detected by keywords
        routed_doc = _make_doc(
            db, test_deal,
            filename="allegato_5.txt",
            raw_text="Prospetto riepilogativo delle voci principali.",
        )
        result = FinancialAgent().run(
            test_deal.id, db, routed_document_ids={routed_doc.id}
        )
        analysed = {e["document_id"] for e in result["findings_by_document"]}
        assert analysed == {fin_doc.id, routed_doc.id}

    def test_explicit_ids_bypass_auto_detection(self, db: Session, test_deal: Deal):
        non_fin = _make_doc(
            db, test_deal, filename="service.txt", raw_text=_NON_FINANCIAL_DOC
        )
        result = FinancialAgent().run(test_deal.id, db, document_ids={non_fin.id})
        assert result["documents_analyzed"] == 1

    def test_pending_doc_excluded(self, db: Session, test_deal: Deal):
        _make_doc(db, test_deal, status=DocumentStatus.pending)
        result = FinancialAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 0


class TestIdempotency:
    """Re-running the agent produces clean results with no row accumulation."""

    def test_no_accumulation_on_rerun(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        agent = FinancialAgent()
        agent.run(test_deal.id, db, document_ids={doc.id})
        agent.run(test_deal.id, db, document_ids={doc.id})
        assert len(_agent_findings(db, test_deal)) == 4  # not 8

    def test_previous_agent_findings_cleared(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal, raw_text=_NON_FINANCIAL_DOC)
        FinancialAgent(provider=_SingleFindingLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert len(_agent_findings(db, test_deal)) == 1
        FinancialAgent(provider=FakeLLMProvider()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert len(_agent_findings(db, test_deal)) == 4  # exactly 4, not 1 + 4

    def test_previous_agent_run_deleted(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
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
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})

        surviving = (
            db.query(AgentFinding)
            .filter(AgentFinding.agent_name == "some_other_agent")
            .all()
        )
        assert len(surviving) == 1

    def test_tax_findings_not_touched(self, db: Session, test_deal: Deal):
        """The sibling documentary-review agent's rows must survive."""
        from packages.agents.tax_agent import TaxAgent, AGENT_NAME as TAX_AGENT

        tax_doc = _make_doc(
            db, test_deal,
            filename="avviso_accertamento.txt",
            raw_text=(
                "AVVISO DI ACCERTAMENTO\n"
                "Agenzia delle Entrate — maggiore IRES dovuta Euro 240.000.\n"
            ),
        )
        TaxAgent().run(test_deal.id, db, document_ids={tax_doc.id})

        fin_doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={fin_doc.id})

        tax_rows = (
            db.query(AgentFinding)
            .filter(
                AgentFinding.deal_id == test_deal.id,
                AgentFinding.agent_name == TAX_AGENT,
            )
            .all()
        )
        assert len(tax_rows) == 3


class TestAgentRunLifecycle:
    """AgentRun records are created and tracked correctly."""

    def test_agent_run_created_and_completed(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
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
            FinancialAgent(provider=_RaisingLLM()).run(
                test_deal.id, db, document_ids={doc.id}
            )
        run = _agent_runs(db, test_deal)[0]
        assert run.status == AgentRunStatus.failed
        assert "LLM unavailable" in run.error_message

    def test_failed_run_creates_no_findings(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        with pytest.raises(RuntimeError):
            FinancialAgent(provider=_RaisingLLM()).run(
                test_deal.id, db, document_ids={doc.id}
            )
        assert len(_agent_findings(db, test_deal)) == 0


class TestEdgeCases:
    """Boundary conditions and convenience wrapper."""

    def test_deal_not_found_raises_value_error(self, db: Session):
        with pytest.raises(ValueError, match="99999"):
            FinancialAgent().run(99999, db)

    def test_doc_with_no_text_skipped(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal, raw_text="")
        result = FinancialAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0

    def test_llm_returns_non_list_handled_gracefully(
        self, db: Session, test_deal: Deal
    ):
        class _BadJsonLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                return '{"not": "an array"}'

        doc = _make_doc(db, test_deal, raw_text=_NON_FINANCIAL_DOC)
        result = FinancialAgent(provider=_BadJsonLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert result["agent_findings_count"] == 0

    def test_llm_returns_invalid_json_handled_gracefully(
        self, db: Session, test_deal: Deal
    ):
        class _GarbageLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                return "this is not json at all"

        doc = _make_doc(db, test_deal, raw_text=_NON_FINANCIAL_DOC)
        result = FinancialAgent(provider=_GarbageLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert result["agent_findings_count"] == 0

    def test_run_financial_analysis_convenience_wrapper(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        result = run_financial_analysis(test_deal.id, db, document_ids={doc.id})
        assert result["deal_id"] == test_deal.id
        assert result["agent_findings_count"] == 4

    def test_run_financial_analysis_uses_supplied_provider(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal, raw_text=_NON_FINANCIAL_DOC)
        result = run_financial_analysis(
            test_deal.id, db, document_ids={doc.id}, provider=_ZeroFindingLLM()
        )
        assert result["agent_findings_count"] == 0

    def test_agent_name_constant(self):
        assert AGENT_NAME == "financial_analysis"
        assert FinancialAgent.AGENT_NAME == "financial_analysis"

    def test_financial_doc_keywords_not_empty(self):
        assert len(_FINANCIAL_DOC_KEYWORDS) > 0


class TestPipelineIntegration:
    """FinancialAgent runs as stage 4d of the orchestrated pipeline."""

    def test_pipeline_includes_financial_stage(self, db: Session, test_deal: Deal):
        from packages.agents.orchestrator import run_deal_analysis_pipeline

        _make_doc(db, test_deal)
        result = run_deal_analysis_pipeline(test_deal.id, db)
        assert "financial_analysis" in result["stages"]
        stage = result["stages"]["financial_analysis"]
        assert "error" not in stage
        # The bilancio is auto-detected by keywords even though the fake
        # router classifies everything as "contract".
        assert stage["documents_analyzed"] == 1
        assert stage["agent_findings_count"] == 4

    def test_financial_findings_reach_the_aggregator_context(
        self, db: Session, test_deal: Deal
    ):
        """Financial AgentFindings are gathered by the red-flag aggregator."""
        from packages.agents.red_flag_aggregator import RedFlagAggregationAgent

        doc = _make_doc(db, test_deal)
        FinancialAgent().run(test_deal.id, db, document_ids={doc.id})

        agg = RedFlagAggregationAgent(provider=_ZeroFindingLLM())
        doc_map = agg._get_documents(db, test_deal.id)
        agent_findings = agg._gather_agent_findings(db, test_deal.id)
        assert any(f.agent_name == AGENT_NAME for f in agent_findings)

        context = agg._build_context_text([], agent_findings, doc_map)
        assert "auditor_opinion" in context


# ── Findings that a purely accounting reading would lose ───────────────────


class _SilentFinancialLLM(LLMProvider):
    """Produces nothing, so only the deterministic floor can fire."""

    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        return "[]"


def _fin_floor(db: Session, deal: Deal, text: str) -> list[AgentFinding]:
    doc = _make_doc(db, deal, raw_text=text)
    set_llm_provider(_SilentFinancialLLM())
    FinancialAgent().run(deal.id, db, document_ids={doc.id})
    return _agent_findings(db, deal)


def _fin_single(db: Session, deal: Deal, **overrides) -> AgentFinding:
    """Run the agent against a stub returning exactly one finding."""
    item = {
        "finding_type": "covenant",
        "title": "Covenant",
        "description": "A covenant is disclosed.",
        "severity": "medium",
        "confidence": 0.8,
    }
    item.update(overrides)

    class _Stub(LLMProvider):
        def complete(self, prompt: str, max_tokens: int = 4096) -> str:
            if "ANALYZE FINANCIAL STATEMENTS" in prompt.upper():
                return json.dumps([item])
            return "[]"

    doc = _make_doc(db, deal, raw_text="Bilancio d'esercizio al 31 dicembre.")
    set_llm_provider(_Stub())
    FinancialAgent().run(deal.id, db, document_ids={doc.id})
    return _agent_findings(db, deal)[0]


class TestNewFindingTypes:
    """The shapes every real financial due-diligence report produces."""

    @pytest.mark.parametrize(
        "text,finding_type",
        [
            ("Debiti tributari scaduti per Euro 300.000", "debt_like_item"),
            ("Debiti previdenziali scaduti verso l'INPS", "debt_like_item"),
            ("Ferie non godute maturate e non liquidate", "debt_like_item"),
            ("Cessione di crediti in factoring pro solvendo", "debt_like_item"),
            ("Fatture da emettere per Euro 450.000", "receivables_at_risk"),
            ("Crediti scaduti da oltre dodici mesi", "receivables_at_risk"),
            ("Ricevuto un contributo a fondo perduto", "public_funding"),
            ("Acceso un finanziamento agevolato regionale", "public_funding"),
        ],
    )
    def test_floor_covers_the_new_types(
        self, db: Session, test_deal: Deal, text: str, finding_type: str
    ):
        findings = _fin_floor(db, test_deal, text)
        assert [f.category for f in findings] == [finding_type]

    def test_new_types_survive_validation(self, db: Session, test_deal: Deal):
        """A model emitting one of the new types must not be coerced away."""
        for finding_type in (
            "debt_like_item",
            "receivables_at_risk",
            "accounting_irregularity",
            "concentration",
            "public_funding",
            "prior_deal_claim",
            "information_limitation",
        ):
            finding = _fin_single(db, test_deal, finding_type=finding_type)
            assert finding.category == finding_type

    def test_unknown_type_still_coerced(self, db: Session, test_deal: Deal):
        finding = _fin_single(db, test_deal, finding_type="vibes")
        assert finding.category == "other_financial"


class TestPublicDebtBridgeToCrisisCode:
    """Overdue public debts are a crisis signal, not only a price item."""

    def test_overdue_tax_debt_flags_the_reporting_duty(
        self, db: Session, test_deal: Deal
    ):
        findings = _fin_floor(
            db, test_deal, "Risultano debiti tributari scaduti per Euro 500.000"
        )
        assert findings[0].severity == Severity.high
        assert "25-novies" in findings[0].description

    def test_ordinary_grant_carries_no_such_note(
        self, db: Session, test_deal: Deal
    ):
        findings = _fin_floor(db, test_deal, "Ricevuti contributi pubblici")
        assert "25-novies" not in findings[0].description


class TestLegallyRelevantHeuristics:
    """Facts a legal reader must catch even when the accounts pass over them."""

    def test_negative_equity_is_raised_as_a_legal_event(
        self, db: Session, test_deal: Deal
    ):
        findings = _fin_floor(
            db, test_deal, "La società presenta un patrimonio netto negativo"
        )
        assert findings[0].category == "going_concern"
        assert findings[0].severity == Severity.high
        assert "2484" in findings[0].description

    def test_deferred_pandemic_losses_are_raised(
        self, db: Session, test_deal: Deal
    ):
        findings = _fin_floor(
            db, test_deal, "Le perdite sospese sono rinviate a nuovo"
        )
        assert findings[0].category == "capital_loss"
        assert findings[0].severity == Severity.high

    def test_change_of_control_clause_is_high(self, db: Session, test_deal: Deal):
        findings = _fin_floor(
            db,
            test_deal,
            "Il contratto di finanziamento prevede una clausola di change of "
            "control",
        )
        assert findings[0].category == "covenant"
        assert findings[0].severity == Severity.high

    def test_unaudited_is_only_informational(self, db: Session, test_deal: Deal):
        """Below the statutory thresholds no audit was required."""
        findings = _fin_floor(
            db, test_deal, "Il bilancio non è sottoposto a revisione legale"
        )
        assert findings[0].category == "auditor_opinion"
        assert findings[0].severity == Severity.low
        assert "2477" in findings[0].description

    def test_dissolution_cause_matches_only_with_the_article_prefix(
        self, db: Session, test_deal: Deal
    ):
        """A bare number in the accounts must not read as an article."""
        findings = _fin_floor(
            db, test_deal, "Ricavi delle vendite per Euro 2484 migliaia"
        )
        assert findings == []


class TestFinancialPayload:
    """Amounts, counterparties and the two covenant booleans."""

    def test_amount_stated_by_document_is_kept(self, db: Session, test_deal: Deal):
        finding = _fin_single(db, test_deal, amount_eur=120000)
        payload = finding.structured_payload_json
        assert payload["amount_eur"] == 120000
        assert payload["amount_source"] == "document"

    def test_missing_amount_is_marked_not_stated(
        self, db: Session, test_deal: Deal
    ):
        finding = _fin_single(db, test_deal)
        payload = finding.structured_payload_json
        assert payload["amount_eur"] is None
        assert payload["amount_source"] == "not_stated"

    @pytest.mark.parametrize("bad", ["circa 120k", -1, True, {}])
    def test_unusable_amount_becomes_no_amount(
        self, db: Session, test_deal: Deal, bad
    ):
        finding = _fin_single(db, test_deal, amount_eur=bad)
        assert finding.structured_payload_json["amount_eur"] is None

    def test_counterparty_is_kept(self, db: Session, test_deal: Deal):
        finding = _fin_single(db, test_deal, counterparty="Banca Alfa")
        assert finding.structured_payload_json["counterparty"] == "Banca Alfa"

    @pytest.mark.parametrize(
        "raw,expected",
        [(True, True), (False, False), ("yes", True), ("no", False), ("", None), (None, None)],
    )
    def test_covenant_flags_are_tri_state(
        self, db: Session, test_deal: Deal, raw, expected
    ):
        """"Not stated" must stay distinct from "stated as false"."""
        finding = _fin_single(db, test_deal, change_of_control_clause=raw)
        payload = finding.structured_payload_json
        assert payload["change_of_control_clause"] is expected

    def test_floor_findings_carry_no_figures(self, db: Session, test_deal: Deal):
        findings = _fin_floor(
            db, test_deal, "Fideiussione rilasciata per Euro 1.000.000"
        )
        payload = findings[0].structured_payload_json
        assert payload["amount_eur"] is None
        assert payload["amount_source"] == "not_stated"
        assert payload["change_of_control_clause"] is None
