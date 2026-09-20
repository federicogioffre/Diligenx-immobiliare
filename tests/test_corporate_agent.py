"""Tests for CorporateAgent — corporate governance insight extraction.

Covers:
- Insight extraction: AgentFinding rows created with correct fields
  (category=insight_type, severity, confidence, title, description,
   structured_payload_json)
- Invalid insight_type values coerced to 'unusual_clause'
- Return value shape and aggregation counts
- Auto-detection of corporate-governance documents via keyword matching
  (filename, raw_text[:1000])
- Document filtering via document_ids (None/set()/explicit set)
- Idempotency: no accumulation on re-run
- AgentRun lifecycle: created, timestamped, completed/failed
- Edge cases: deal not found, empty text, no matching docs, convenience wrapper
"""
import json
import pytest

from packages.agents.deal_analysis_agent import LLMResponseError
from sqlalchemy.orm import Session

from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from app.models.agent_finding import AgentFinding
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.red_flag import Severity
from packages.agents.corporate_agent import (
    CorporateAgent,
    run_corporate_analysis,
    AGENT_NAME,
    _CORPORATE_DOC_KEYWORDS,
    _VALID_INSIGHT_TYPES,
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

_ARTICLES_OF_ASSOCIATION = """\
ARTICLES OF ASSOCIATION
Acme Technologies Ltd — Incorporated 2023

1. Name: The company name is "Acme Technologies Ltd."
2. Purpose: General commercial activities.
3. Board Composition: The board shall consist of 3 to 7 directors.
4. Quorum: A quorum for board meetings shall be a majority of directors.
5. Shareholder Meetings: Annual general meetings shall be held within six months
   of each financial year end.
6. Voting: Each ordinary share carries one vote. Preference shares carry no
   voting rights except on resolutions affecting their class rights.
7. Transfer of Shares: No transfer of shares shall be registered without prior
   approval of the board.
"""

_SHAREHOLDER_AGREEMENT = """\
SHAREHOLDER AGREEMENT
This Shareholder Agreement ("Agreement") is entered into among the parties listed
below (collectively, the "Shareholders") and Acme Technologies Ltd (the "Company").

1. Share Capital: The Company has issued 10,000 ordinary shares and 2,000
   preference shares.
2. Voting Threshold: Decisions on major transactions require a 75% supermajority
   of all voting shares.
3. Right of First Refusal: Before any transfer of shares, the selling shareholder
   must offer the shares to the other shareholders pro rata.
4. Drag-Along Rights: If holders of 80% of shares approve a sale, all other
   shareholders are required to participate in the sale on the same terms.
5. Tag-Along Rights: Any shareholder may join a sale approved by the majority.
6. Veto Rights: The lead investor holds veto rights over capital expenditure
   exceeding $500,000 and any acquisition of a business unit.
"""

_BOARD_MINUTES = """\
MINUTES OF BOARD MEETING
Acme Technologies Ltd — Board of Directors
Date: 15 November 2024 | Location: Head Office

Attendees: Alice Smith (Chair), Bob Jones (CEO), Carol White (CFO),
           David Brown (NED), Eve Wilson (Investor Representative)

1. Quorum confirmed: 5 of 5 directors present.
2. Approved Q3 financial statements.
3. Resolved (4-1): To extend the CEO service agreement by 24 months.
4. Investor Representative exercised veto on acquisition proposal (item 5(b)).
5. Next meeting: 15 February 2025.
"""

_BYLAWS = """\
BYLAWS OF ACME TECHNOLOGIES INC.
Adopted by the Board of Directors on 1 January 2023.

ARTICLE I — OFFICES
The principal office of the Corporation shall be in the State of Delaware.

ARTICLE II — SHAREHOLDERS
Section 2.1 Annual Meeting: An annual meeting of shareholders shall be held in
March of each year.
Section 2.2 Special Meetings: Special meetings may be called by the Board or
holders of not less than 10% of outstanding shares.
Section 2.3 Quorum: Holders of a majority of shares entitled to vote shall
constitute a quorum.

ARTICLE III — BOARD OF DIRECTORS
Section 3.1 Powers: The business and affairs of the Corporation shall be managed
by the Board.
Section 3.2 Number: The Board shall consist of not fewer than 3 and not more
than 9 directors.
"""

_NON_CORPORATE_DOC = """\
SERVICE AGREEMENT
This Service Agreement is entered into between Alpha Corp ("Client") and Beta
Services Ltd ("Provider").

1. Services: Provider agrees to deliver software development services.
2. Term: This agreement begins on 1 January 2025 and runs for 12 months.
3. Payment: Client shall pay monthly invoices within 30 days of receipt.
4. Termination: Either party may terminate with 30 days written notice.
5. Liability: Total liability shall not exceed the fees paid in the prior 3 months.
"""


# ── Test helpers ────────────────────────────────────────────────────────────


def _make_doc(
    db: Session,
    deal: Deal,
    *,
    filename: str = "articles_of_association.txt",
    raw_text: str = _ARTICLES_OF_ASSOCIATION,
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


class _ZeroInsightLLM(LLMProvider):
    """Always returns an empty insight array — used in idempotency tests."""

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        return json.dumps([])


class _SingleInsightLLM(LLMProvider):
    """Returns exactly one governance insight — used in idempotency tests."""

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        if "CORPORATE GOVERNANCE" in prompt.upper():
            return json.dumps([{
                "insight_type": "governance_structure",
                "title": "Single Insight",
                "description": "Board composition requires 3 directors minimum.",
                "severity": "low",
                "confidence": 0.75,
            }])
        return json.dumps([])


class _UnknownInsightTypeLLM(LLMProvider):
    """Returns an insight with an invalid insight_type — coercion test."""

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        if "CORPORATE GOVERNANCE" in prompt.upper():
            return json.dumps([{
                "insight_type": "totally_invalid_type",
                "title": "Some Provision",
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


class TestGovernanceInsightExtraction:
    """AgentFinding rows are created with correct field values."""

    def test_agent_findings_created_for_corporate_doc(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        agent = CorporateAgent()
        agent.run(test_deal.id, db, document_ids={doc.id})
        findings = _agent_findings(db, test_deal)
        # FakeLLMProvider returns 3 insights
        assert len(findings) == 3

    def test_finding_agent_name(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.agent_name == AGENT_NAME

    def test_finding_deal_id_and_document_id(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.deal_id == test_deal.id
            assert f.document_id == doc.id

    def test_finding_categories_are_insight_types(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        categories = {f.category for f in _agent_findings(db, test_deal)}
        # FakeLLMProvider returns voting_threshold, transfer_restriction, veto_right
        assert categories == {"voting_threshold", "transfer_restriction", "veto_right"}

    def test_finding_severities(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        severities = {f.severity for f in _agent_findings(db, test_deal)}
        assert Severity.low in severities
        assert Severity.medium in severities
        assert Severity.high in severities

    def test_finding_confidence_values(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        confidences = {f.confidence for f in _agent_findings(db, test_deal)}
        # FakeLLMProvider provides 0.88, 0.92, 0.85
        assert confidences == {0.88, 0.92, 0.85}

    def test_finding_titles_populated(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.title  # not empty

    def test_finding_description_populated(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.description  # not empty

    def test_finding_title_truncated_to_100_chars(self, db: Session, test_deal: Deal):
        """title must not exceed 100 characters (CorporateAgent enforces this)."""
        class _LongTitleLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "CORPORATE GOVERNANCE" in prompt.upper():
                    return json.dumps([{
                        "insight_type": "governance_structure",
                        "title": "X" * 200,
                        "description": "desc",
                        "severity": "low",
                        "confidence": 0.5,
                    }])
                return json.dumps([])

        doc = _make_doc(db, test_deal)
        CorporateAgent(provider=_LongTitleLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        for f in _agent_findings(db, test_deal):
            assert len(f.title) <= 100

    def test_structured_payload_json_shape(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal, filename="articles_of_association.txt")
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            payload = f.structured_payload_json
            assert "insight_type" in payload
            assert payload["document_id"] == doc.id
            assert payload["filename"] == doc.filename
            assert payload["insight_type"] in _VALID_INSIGHT_TYPES

    def test_finding_category_matches_payload_insight_type(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.category == f.structured_payload_json["insight_type"]


class TestInsightTypeCoercion:
    """Invalid insight_type values are coerced to 'unusual_clause'."""

    def test_unknown_insight_type_coerced(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent(provider=_UnknownInsightTypeLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].category == "unusual_clause"

    def test_valid_insight_types_preserved(self, db: Session, test_deal: Deal):
        """FakeLLMProvider returns only valid types — none should be coerced."""
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        for f in _agent_findings(db, test_deal):
            assert f.category in _VALID_INSIGHT_TYPES

    def test_critical_severity_normalized_to_high(self, db: Session, test_deal: Deal):
        """'critical' maps onto the 3-level scale as 'high' — a critical
        governance risk must never be silently downgraded to 'low'."""
        class _CriticalSeverityLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "CORPORATE GOVERNANCE" in prompt.upper():
                    return json.dumps([{
                        "insight_type": "governance_structure",
                        "title": "Some clause",
                        "description": "desc",
                        "severity": "critical",
                        "confidence": 0.5,
                    }])
                return json.dumps([])

        doc = _make_doc(db, test_deal)
        CorporateAgent(provider=_CriticalSeverityLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].severity == Severity.high

    def test_unknown_severity_coerced_to_medium(self, db: Session, test_deal: Deal):
        """An unrecognised severity string falls back to 'medium', not 'low'."""
        class _BadSeverityLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "CORPORATE GOVERNANCE" in prompt.upper():
                    return json.dumps([{
                        "insight_type": "governance_structure",
                        "title": "Some clause",
                        "description": "desc",
                        "severity": "banana",
                        "confidence": 0.5,
                    }])
                return json.dumps([])

        doc = _make_doc(db, test_deal)
        CorporateAgent(provider=_BadSeverityLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 1
        assert findings[0].severity == Severity.medium


class TestReturnValue:
    """The dict returned by CorporateAgent.run() has the correct shape."""

    def test_return_value_keys(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        expected_keys = {
            "failed_documents",
            "deal_id",
            "documents_analyzed",
            "agent_findings_count",
            "findings_by_severity",
            "findings_by_insight_type",
            "findings_by_document",
        }
        assert set(result.keys()) == expected_keys

    def test_deal_id_in_result(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["deal_id"] == test_deal.id

    def test_documents_analyzed_one_doc(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["documents_analyzed"] == 1

    def test_documents_analyzed_two_docs(self, db: Session, test_deal: Deal):
        _make_doc(db, test_deal, filename="bylaws.txt", raw_text=_BYLAWS)
        _make_doc(
            db, test_deal,
            filename="shareholder_agreement.txt",
            raw_text=_SHAREHOLDER_AGREEMENT,
        )
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 2

    def test_agent_findings_count_one_doc(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        # FakeLLMProvider returns 3 insights per doc
        assert result["agent_findings_count"] == 3

    def test_agent_findings_count_two_docs(self, db: Session, test_deal: Deal):
        _make_doc(db, test_deal, filename="bylaws.txt", raw_text=_BYLAWS)
        _make_doc(
            db, test_deal,
            filename="shareholder_agreement.txt",
            raw_text=_SHAREHOLDER_AGREEMENT,
        )
        result = CorporateAgent().run(test_deal.id, db)
        assert result["agent_findings_count"] == 6  # 2 docs × 3 insights

    def test_findings_by_severity_structure(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        by_sev = result["findings_by_severity"]
        assert set(by_sev.keys()) == {"low", "medium", "high"}

    def test_findings_by_severity_counts(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        # FakeLLMProvider: 1 medium, 1 low, 1 high
        by_sev = result["findings_by_severity"]
        assert by_sev["medium"] == 1
        assert by_sev["low"] == 1
        assert by_sev["high"] == 1

    def test_findings_by_insight_type_structure(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        by_type = result["findings_by_insight_type"]
        assert set(by_type.keys()) == _VALID_INSIGHT_TYPES

    def test_findings_by_insight_type_counts(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        # FakeLLMProvider: voting_threshold=1, transfer_restriction=1, veto_right=1
        by_type = result["findings_by_insight_type"]
        assert by_type["voting_threshold"] == 1
        assert by_type["transfer_restriction"] == 1
        assert by_type["veto_right"] == 1
        # Other types not returned → 0
        assert by_type["governance_structure"] == 0
        assert by_type["unusual_clause"] == 0

    def test_findings_by_document_shape(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal, filename="bylaws.txt", raw_text=_BYLAWS)
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        assert len(result["findings_by_document"]) == 1
        entry = result["findings_by_document"][0]
        assert entry["document_id"] == doc.id
        assert entry["filename"] == doc.filename
        assert entry["finding_count"] == 3

    def test_empty_doc_list_returns_zero_counts(self, db: Session, test_deal: Deal):
        result = CorporateAgent().run(test_deal.id, db, document_ids=set())
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0
        assert result["findings_by_document"] == []
        for v in result["findings_by_severity"].values():
            assert v == 0
        for v in result["findings_by_insight_type"].values():
            assert v == 0


class TestAutoDetection:
    """The agent auto-detects corporate-governance documents when document_ids=None."""

    def test_articles_of_association_detected_by_filename(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(
            db, test_deal,
            filename="articles_of_association.txt",
            raw_text="Some content.",  # no keyword in text
        )
        result = CorporateAgent().run(test_deal.id, db)  # document_ids=None
        assert result["documents_analyzed"] == 1
        assert doc.id in {e["document_id"] for e in result["findings_by_document"]}

    def test_bylaws_detected_by_filename(self, db: Session, test_deal: Deal):
        doc = _make_doc(
            db, test_deal,
            filename="bylaws_final.txt",
            raw_text="Content without any governance keyword.",
        )
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1
        assert doc.id in {e["document_id"] for e in result["findings_by_document"]}

    def test_board_minutes_detected_by_filename(self, db: Session, test_deal: Deal):
        doc = _make_doc(
            db, test_deal,
            filename="board_minutes_nov24.txt",
            raw_text="Board meeting agenda.",
        )
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1
        assert doc.id in {e["document_id"] for e in result["findings_by_document"]}

    def test_shareholder_agreement_detected_by_text(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(
            db, test_deal,
            filename="agreement.txt",          # no keyword in filename
            raw_text=_SHAREHOLDER_AGREEMENT,   # keyword in first 1000 chars
        )
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1
        assert doc.id in {e["document_id"] for e in result["findings_by_document"]}

    def test_keyword_in_first_1000_chars_detected(
        self, db: Session, test_deal: Deal
    ):
        # Put keyword near the start
        raw_text = "This is a bylaws document. " + "x" * 900
        doc = _make_doc(db, test_deal, filename="misc.txt", raw_text=raw_text)
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1

    def test_keyword_only_after_1000_chars_not_detected(
        self, db: Session, test_deal: Deal
    ):
        # Keyword appears after the 1000-char boundary
        raw_text = "x" * 1001 + " bylaws document"
        doc = _make_doc(db, test_deal, filename="misc.txt", raw_text=raw_text)
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 0

    def test_non_corporate_doc_excluded(self, db: Session, test_deal: Deal):
        _make_doc(
            db, test_deal,
            filename="service_agreement.txt",
            raw_text=_NON_CORPORATE_DOC,
        )
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0

    def test_mixed_docs_only_corporate_analysed(
        self, db: Session, test_deal: Deal
    ):
        corp_doc = _make_doc(
            db, test_deal,
            filename="articles_of_association.txt",
            raw_text=_ARTICLES_OF_ASSOCIATION,
        )
        _make_doc(
            db, test_deal,
            filename="invoice_q4.txt",
            raw_text=_NON_CORPORATE_DOC,
        )
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1
        assert result["findings_by_document"][0]["document_id"] == corp_doc.id

    def test_pending_doc_excluded_from_auto_detection(
        self, db: Session, test_deal: Deal
    ):
        _make_doc(
            db, test_deal,
            filename="bylaws.txt",
            raw_text=_BYLAWS,
            status=DocumentStatus.pending,
        )
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 0

    def test_underscore_filename_normalised_for_matching(
        self, db: Session, test_deal: Deal
    ):
        """Underscores in filenames are treated as spaces for keyword matching."""
        doc = _make_doc(
            db, test_deal,
            filename="board_resolution_2024.txt",
            raw_text="Some board content.",
        )
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 1


class TestDocumentIdFiltering:
    """Behaviour of the document_ids parameter."""

    def test_none_triggers_auto_detection(self, db: Session, test_deal: Deal):
        corp = _make_doc(
            db, test_deal,
            filename="shareholder_agreement.txt",
            raw_text=_SHAREHOLDER_AGREEMENT,
        )
        non_corp = _make_doc(
            db, test_deal,
            filename="service.txt",
            raw_text=_NON_CORPORATE_DOC,
        )
        result = CorporateAgent().run(test_deal.id, db, document_ids=None)
        assert result["documents_analyzed"] == 1
        assert result["findings_by_document"][0]["document_id"] == corp.id

    def test_empty_set_produces_zero_findings(self, db: Session, test_deal: Deal):
        _make_doc(db, test_deal)
        result = CorporateAgent().run(test_deal.id, db, document_ids=set())
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0

    def test_explicit_ids_bypass_auto_detection(self, db: Session, test_deal: Deal):
        """A non-corporate doc can still be analysed when its ID is passed explicitly."""
        non_corp = _make_doc(
            db, test_deal,
            filename="service_agreement.txt",
            raw_text=_NON_CORPORATE_DOC,
        )
        result = CorporateAgent().run(
            test_deal.id, db, document_ids={non_corp.id}
        )
        # Should process the doc (LLM returns 3 insights regardless)
        assert result["documents_analyzed"] == 1

    def test_explicit_ids_restricts_to_given_docs(self, db: Session, test_deal: Deal):
        doc1 = _make_doc(
            db, test_deal,
            filename="bylaws.txt",
            raw_text=_BYLAWS,
        )
        doc2 = _make_doc(
            db, test_deal,
            filename="board_minutes.txt",
            raw_text=_BOARD_MINUTES,
        )
        # Only analyse doc1
        result = CorporateAgent().run(
            test_deal.id, db, document_ids={doc1.id}
        )
        assert result["documents_analyzed"] == 1
        assert result["findings_by_document"][0]["document_id"] == doc1.id

    def test_nonexistent_id_in_explicit_set_ignored(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        result = CorporateAgent().run(
            test_deal.id, db, document_ids={doc.id, 999999}
        )
        # 999999 doesn't exist — only doc is processed
        assert result["documents_analyzed"] == 1


class TestIdempotency:
    """Re-running the agent produces clean results with no row accumulation."""

    def test_no_accumulation_on_rerun(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        agent = CorporateAgent()
        agent.run(test_deal.id, db, document_ids={doc.id})
        agent.run(test_deal.id, db, document_ids={doc.id})
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 3  # not 6

    def test_previous_agent_findings_cleared(self, db: Session, test_deal: Deal):
        """After re-run with a different LLM, old findings are gone."""
        doc = _make_doc(db, test_deal)

        # Run 1: SingleInsightLLM → 1 finding
        CorporateAgent(provider=_SingleInsightLLM()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        assert len(_agent_findings(db, test_deal)) == 1

        # Run 2: FakeLLMProvider → 3 findings (old 1 must be deleted)
        CorporateAgent(provider=FakeLLMProvider()).run(
            test_deal.id, db, document_ids={doc.id}
        )
        findings = _agent_findings(db, test_deal)
        assert len(findings) == 3  # exactly 3, not 1 + 3

    def test_previous_agent_run_deleted(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        runs = _agent_runs(db, test_deal)
        assert len(runs) == 1

    def test_other_agents_findings_not_touched(self, db: Session, test_deal: Deal):
        """Idempotency cleanup must not remove other agents' findings."""
        from app.models.red_flag import Severity as Sev

        # Insert a finding from a different agent
        other_finding = AgentFinding(
            deal_id=test_deal.id,
            agent_name="some_other_agent",
            category="classification",
            title="Other agent finding",
            description="This is from another agent.",
            severity=Sev.low,
        )
        db.add(other_finding)
        db.commit()

        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})

        surviving = (
            db.query(AgentFinding)
            .filter(AgentFinding.agent_name == "some_other_agent")
            .all()
        )
        assert len(surviving) == 1


class TestAgentRunLifecycle:
    """AgentRun records are created and tracked correctly."""

    def test_agent_run_created(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        runs = _agent_runs(db, test_deal)
        assert len(runs) == 1

    def test_agent_run_agent_name(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        run = _agent_runs(db, test_deal)[0]
        assert run.agent_name == AGENT_NAME

    def test_agent_run_completed_status(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        run = _agent_runs(db, test_deal)[0]
        assert run.status == AgentRunStatus.completed

    def test_agent_run_timestamps_set(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        run = _agent_runs(db, test_deal)[0]
        assert run.started_at is not None
        assert run.completed_at is not None
        assert run.completed_at >= run.started_at

    def test_agent_run_failed_on_llm_error(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        with pytest.raises(RuntimeError, match="LLM unavailable"):
            CorporateAgent(provider=_RaisingLLM()).run(
                test_deal.id, db, document_ids={doc.id}
            )
        run = _agent_runs(db, test_deal)[0]
        assert run.status == AgentRunStatus.failed

    def test_agent_run_error_message_on_failure(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        with pytest.raises(RuntimeError):
            CorporateAgent(provider=_RaisingLLM()).run(
                test_deal.id, db, document_ids={doc.id}
            )
        run = _agent_runs(db, test_deal)[0]
        assert "LLM unavailable" in run.error_message

    def test_failed_run_creates_no_findings(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal)
        with pytest.raises(RuntimeError):
            CorporateAgent(provider=_RaisingLLM()).run(
                test_deal.id, db, document_ids={doc.id}
            )
        assert len(_agent_findings(db, test_deal)) == 0


class TestEdgeCases:
    """Boundary conditions and convenience wrapper."""

    def test_deal_not_found_raises_value_error(self, db: Session):
        with pytest.raises(ValueError, match="99999"):
            CorporateAgent().run(99999, db)

    def test_doc_with_no_text_skipped(self, db: Session, test_deal: Deal):
        doc = _make_doc(db, test_deal, raw_text="")
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        # The doc is skipped entirely (no text) — it is NOT counted in documents_analyzed
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0
        assert result["findings_by_document"] == []

    def test_doc_with_whitespace_only_text_skipped(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal, raw_text="   \n\t  ")
        result = CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["agent_findings_count"] == 0

    def test_no_processed_docs_returns_zero(self, db: Session, test_deal: Deal):
        # No documents at all
        result = CorporateAgent().run(test_deal.id, db)
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0

    def test_llm_returns_non_list_fails_stage(
        self, db: Session, test_deal: Deal
    ):
        class _BadJsonLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                return '{"not": "an array"}'

        doc = _make_doc(db, test_deal)
        with pytest.raises(LLMResponseError):
            CorporateAgent(provider=_BadJsonLLM()).run(
                test_deal.id, db, document_ids={doc.id}
            )

    def test_llm_returns_invalid_json_fails_stage(
        self, db: Session, test_deal: Deal
    ):
        class _GarbageLLM(LLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                return "this is not json at all"

        doc = _make_doc(db, test_deal)
        with pytest.raises(LLMResponseError):
            CorporateAgent(provider=_GarbageLLM()).run(
                test_deal.id, db, document_ids={doc.id}
            )

    def test_run_corporate_analysis_convenience_wrapper(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal, filename="bylaws.txt", raw_text=_BYLAWS)
        result = run_corporate_analysis(
            test_deal.id, db, document_ids={doc.id}
        )
        assert result["deal_id"] == test_deal.id
        assert result["agent_findings_count"] == 3

    def test_run_corporate_analysis_uses_supplied_provider(
        self, db: Session, test_deal: Deal
    ):
        doc = _make_doc(db, test_deal)
        result = run_corporate_analysis(
            test_deal.id, db, document_ids={doc.id}, provider=_ZeroInsightLLM()
        )
        assert result["agent_findings_count"] == 0

    def test_agent_name_constant(self):
        assert AGENT_NAME == "corporate_governance"
        assert CorporateAgent.AGENT_NAME == "corporate_governance"

    def test_valid_insight_types_set(self):
        assert _VALID_INSIGHT_TYPES == {
            "governance_structure",
            "voting_threshold",
            "transfer_restriction",
            "veto_right",
            "unusual_clause",
        }

    def test_corporate_doc_keywords_not_empty(self):
        assert len(_CORPORATE_DOC_KEYWORDS) > 0

    def test_multiple_insights_from_one_doc_all_persisted(
        self, db: Session, test_deal: Deal
    ):
        """All 3 fake insights are written as separate AgentFinding rows."""
        doc = _make_doc(db, test_deal)
        CorporateAgent().run(test_deal.id, db, document_ids={doc.id})
        findings = _agent_findings(db, test_deal)
        categories = [f.category for f in findings]
        assert "voting_threshold" in categories
        assert "transfer_restriction" in categories
        assert "veto_right" in categories


class TestIsCorpDocHelper:
    """Unit tests for CorporateAgent._is_corporate_document()."""

    def _doc_stub(self, filename: str, raw_text: str = ""):
        class _Stub:
            pass
        d = _Stub()
        d.filename = filename
        d.raw_text = raw_text
        return d

    def test_articles_of_association_filename(self):
        agent = CorporateAgent(provider=_ZeroInsightLLM())
        assert agent._is_corporate_document(
            self._doc_stub("articles_of_association.pdf")
        )

    def test_bylaws_filename(self):
        agent = CorporateAgent(provider=_ZeroInsightLLM())
        assert agent._is_corporate_document(self._doc_stub("bylaws.docx"))

    def test_board_minutes_filename(self):
        agent = CorporateAgent(provider=_ZeroInsightLLM())
        assert agent._is_corporate_document(self._doc_stub("board_minutes.txt"))

    def test_shareholder_agreement_in_text(self):
        agent = CorporateAgent(provider=_ZeroInsightLLM())
        assert agent._is_corporate_document(
            self._doc_stub("doc.txt", "This shareholder agreement is dated 2024.")
        )

    def test_keyword_case_insensitive(self):
        agent = CorporateAgent(provider=_ZeroInsightLLM())
        assert agent._is_corporate_document(
            self._doc_stub("DOC.TXT", "ANNUAL GENERAL MEETING of shareholders.")
        )

    def test_non_corporate_doc_returns_false(self):
        agent = CorporateAgent(provider=_ZeroInsightLLM())
        assert not agent._is_corporate_document(
            self._doc_stub("service_agreement.txt", _NON_CORPORATE_DOC)
        )

    def test_text_snippet_capped_at_1000_chars(self):
        """Keyword at char 1001 must NOT trigger detection."""
        agent = CorporateAgent(provider=_ZeroInsightLLM())
        text = "a" * 1001 + " bylaws document"
        assert not agent._is_corporate_document(self._doc_stub("misc.txt", text))

