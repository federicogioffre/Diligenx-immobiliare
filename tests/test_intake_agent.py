"""Tests for DataRoomIntakeAgent.

Covers:
- Empty document detection (None raw_text, empty string, whitespace-only)
- Small document detection (below / at / above threshold)
- Duplicate document detection (2-way, 3-way, empty docs not grouped)
- Missing-category detection for all four standard categories
- Category recognition via filename and raw-text keywords
- AgentFinding field correctness (severity, category, document_id, payload)
- MissingDocument field correctness (category, priority, reason)
- Return-value structure and counts
- Idempotency (re-running produces identical row counts, no accumulation)
- AgentRun tracking (created, status=completed, timestamps)
- Edge cases: deal not found, no documents, mixed issues
"""
import pytest
from sqlalchemy.orm import Session

from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.agent_finding import AgentFinding
from app.models.missing_document import MissingDocument
from app.models.red_flag import Severity
from app.models.open_question import Priority
from packages.agents.intake_agent import (
    DataRoomIntakeAgent,
    run_intake,
    AGENT_NAME,
    SMALL_DOC_THRESHOLD,
)

# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def agent() -> DataRoomIntakeAgent:
    return DataRoomIntakeAgent()


def _make_doc(
    db: Session,
    deal: Deal,
    *,
    filename: str = "document.txt",
    raw_text: str | None = "Default document text for testing.",
    status: DocumentStatus = DocumentStatus.processed,
    file_size: int = 512,
) -> Document:
    """Helper: create and persist a Document."""
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


def _findings(db: Session, deal: Deal, *, category: str | None = None) -> list[AgentFinding]:
    """Return AgentFindings for the deal (optionally filtered by category)."""
    q = db.query(AgentFinding).filter(
        AgentFinding.deal_id == deal.id,
        AgentFinding.agent_name == AGENT_NAME,
    )
    if category:
        q = q.filter(AgentFinding.category == category)
    return q.all()


# ── 1. Empty document detection ────────────────────────────────────────────

class TestEmptyDocumentDetection:

    def test_none_raw_text_flagged(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="empty.txt", raw_text=None)
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="empty_document")) == 1

    def test_empty_string_raw_text_flagged(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="empty.txt", raw_text="")
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="empty_document")) == 1

    def test_whitespace_only_raw_text_flagged(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="ws.txt", raw_text="   \n\t  ")
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="empty_document")) == 1

    def test_document_with_content_not_flagged(self, db, test_deal, agent):
        _make_doc(db, test_deal, raw_text="This document has real content.")
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="empty_document")) == 0

    def test_multiple_empty_docs_all_flagged(self, db, test_deal, agent):
        for i in range(3):
            _make_doc(db, test_deal, filename=f"empty_{i}.txt", raw_text=None)
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="empty_document")) == 3

    def test_empty_finding_severity_is_high(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="empty.pdf", raw_text=None)
        agent.run(test_deal.id, db)
        f = _findings(db, test_deal, category="empty_document")[0]
        assert f.severity == Severity.high

    def test_empty_finding_linked_to_document(self, db, test_deal, agent):
        doc = _make_doc(db, test_deal, filename="empty.pdf", raw_text=None)
        agent.run(test_deal.id, db)
        f = _findings(db, test_deal, category="empty_document")[0]
        assert f.document_id == doc.id

    def test_empty_finding_confidence_is_one(self, db, test_deal, agent):
        _make_doc(db, test_deal, raw_text=None)
        agent.run(test_deal.id, db)
        f = _findings(db, test_deal, category="empty_document")[0]
        assert f.confidence == 1.0

    def test_empty_finding_payload_has_filename(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="missing.pdf", raw_text=None)
        agent.run(test_deal.id, db)
        f = _findings(db, test_deal, category="empty_document")[0]
        assert f.structured_payload_json["filename"] == "missing.pdf"
        assert f.structured_payload_json["reason"] == "no_text"

    def test_result_empty_count_matches(self, db, test_deal, agent):
        for i in range(2):
            _make_doc(db, test_deal, filename=f"e_{i}.txt", raw_text=None)
        result = agent.run(test_deal.id, db)
        assert result["issues"]["empty_documents"] == 2


# ── 2. Small document detection ────────────────────────────────────────────

class TestSmallDocumentDetection:

    def test_short_document_flagged(self, db, test_deal, agent):
        _make_doc(db, test_deal, raw_text="Short." * 10)   # 60 chars
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="small_document")) == 1

    def test_document_at_threshold_not_flagged(self, db, test_deal, agent):
        # Exactly SMALL_DOC_THRESHOLD characters → NOT flagged (condition is strict <)
        text = "x" * SMALL_DOC_THRESHOLD
        _make_doc(db, test_deal, raw_text=text)
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="small_document")) == 0

    def test_document_above_threshold_not_flagged(self, db, test_deal, agent):
        text = "a" * (SMALL_DOC_THRESHOLD + 50)
        _make_doc(db, test_deal, raw_text=text)
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="small_document")) == 0

    def test_document_one_below_threshold_flagged(self, db, test_deal, agent):
        text = "b" * (SMALL_DOC_THRESHOLD - 1)
        _make_doc(db, test_deal, raw_text=text)
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="small_document")) == 1

    def test_empty_document_not_also_flagged_as_small(self, db, test_deal, agent):
        """An empty document must appear only under empty_document, not small_document."""
        _make_doc(db, test_deal, raw_text=None)
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="small_document")) == 0
        assert len(_findings(db, test_deal, category="empty_document")) == 1

    def test_small_finding_severity_is_low(self, db, test_deal, agent):
        _make_doc(db, test_deal, raw_text="Tiny." * 5)   # 25 chars
        agent.run(test_deal.id, db)
        f = _findings(db, test_deal, category="small_document")[0]
        assert f.severity == Severity.low

    def test_small_finding_payload_includes_char_count(self, db, test_deal, agent):
        text = "Small text here!" * 5  # 80 chars
        _make_doc(db, test_deal, raw_text=text)
        agent.run(test_deal.id, db)
        f = _findings(db, test_deal, category="small_document")[0]
        payload = f.structured_payload_json
        assert payload["char_count"] == len(text.strip())
        assert payload["threshold"] == SMALL_DOC_THRESHOLD
        assert payload["reason"] == "below_threshold"

    def test_small_finding_linked_to_document(self, db, test_deal, agent):
        doc = _make_doc(db, test_deal, raw_text="Short text." * 5)
        agent.run(test_deal.id, db)
        f = _findings(db, test_deal, category="small_document")[0]
        assert f.document_id == doc.id

    def test_result_small_count_matches(self, db, test_deal, agent):
        for i in range(3):
            _make_doc(db, test_deal, filename=f"small_{i}.txt", raw_text="s" * 50)
        result = agent.run(test_deal.id, db)
        assert result["issues"]["small_documents"] == 3


# ── 3. Duplicate document detection ────────────────────────────────────────

class TestDuplicateDocumentDetection:

    _DUPLICATE_TEXT = (
        "This is the canonical contract text used to test duplicate detection. "
        "It must be long enough to exceed the small-document threshold."
    )

    def test_two_identical_docs_both_flagged(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="a.txt", raw_text=self._DUPLICATE_TEXT)
        _make_doc(db, test_deal, filename="b.txt", raw_text=self._DUPLICATE_TEXT)
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="duplicate_document")) == 2

    def test_three_identical_docs_all_flagged(self, db, test_deal, agent):
        for name in ("x.txt", "y.txt", "z.txt"):
            _make_doc(db, test_deal, filename=name, raw_text=self._DUPLICATE_TEXT)
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="duplicate_document")) == 3

    def test_result_duplicate_groups_count(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="a.txt", raw_text=self._DUPLICATE_TEXT)
        _make_doc(db, test_deal, filename="b.txt", raw_text=self._DUPLICATE_TEXT)
        result = agent.run(test_deal.id, db)
        assert result["issues"]["duplicate_groups"] == 1

    def test_two_groups_of_duplicates(self, db, test_deal, agent):
        # Group 1
        for name in ("g1a.txt", "g1b.txt"):
            _make_doc(db, test_deal, filename=name, raw_text="Group one content " * 20)
        # Group 2
        for name in ("g2a.txt", "g2b.txt"):
            _make_doc(db, test_deal, filename=name, raw_text="Group two content " * 20)
        result = agent.run(test_deal.id, db)
        assert result["issues"]["duplicate_groups"] == 2
        assert len(_findings(db, test_deal, category="duplicate_document")) == 4

    def test_unique_docs_no_duplicates(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="a.txt", raw_text="Unique content A " * 20)
        _make_doc(db, test_deal, filename="b.txt", raw_text="Unique content B " * 20)
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="duplicate_document")) == 0

    def test_empty_docs_not_grouped_as_duplicates(self, db, test_deal, agent):
        """Two empty documents must NOT form a duplicate group — they are each
        independently flagged as *empty*, not as duplicates of each other."""
        _make_doc(db, test_deal, filename="e1.txt", raw_text=None)
        _make_doc(db, test_deal, filename="e2.txt", raw_text=None)
        agent.run(test_deal.id, db)
        assert len(_findings(db, test_deal, category="duplicate_document")) == 0
        assert len(_findings(db, test_deal, category="empty_document")) == 2

    def test_duplicate_finding_severity_is_medium(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="a.txt", raw_text=self._DUPLICATE_TEXT)
        _make_doc(db, test_deal, filename="b.txt", raw_text=self._DUPLICATE_TEXT)
        agent.run(test_deal.id, db)
        for f in _findings(db, test_deal, category="duplicate_document"):
            assert f.severity == Severity.medium

    def test_duplicate_finding_payload_contains_hash_and_ids(self, db, test_deal, agent):
        doc_a = _make_doc(db, test_deal, filename="a.txt", raw_text=self._DUPLICATE_TEXT)
        doc_b = _make_doc(db, test_deal, filename="b.txt", raw_text=self._DUPLICATE_TEXT)
        agent.run(test_deal.id, db)
        findings = _findings(db, test_deal, category="duplicate_document")
        for f in findings:
            payload = f.structured_payload_json
            assert "content_hash" in payload
            assert "duplicate_document_ids" in payload
            assert set(payload["duplicate_document_ids"]) == {doc_a.id, doc_b.id}

    def test_duplicate_finding_linked_to_correct_document(self, db, test_deal, agent):
        doc_a = _make_doc(db, test_deal, filename="a.txt", raw_text=self._DUPLICATE_TEXT)
        doc_b = _make_doc(db, test_deal, filename="b.txt", raw_text=self._DUPLICATE_TEXT)
        agent.run(test_deal.id, db)
        finding_doc_ids = {
            f.document_id for f in _findings(db, test_deal, category="duplicate_document")
        }
        assert finding_doc_ids == {doc_a.id, doc_b.id}

    def test_duplicate_finding_mentions_other_file_in_description(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="original.txt", raw_text=self._DUPLICATE_TEXT)
        _make_doc(db, test_deal, filename="copy.txt", raw_text=self._DUPLICATE_TEXT)
        agent.run(test_deal.id, db)
        descriptions = [
            f.description
            for f in _findings(db, test_deal, category="duplicate_document")
        ]
        # Each finding's description must mention the *other* file
        assert any("copy.txt" in d for d in descriptions)
        assert any("original.txt" in d for d in descriptions)


# ── 4. Missing checklist-item detection ────────────────────────────────────

class TestMissingChecklistDetection:
    """Verifies that the NM Standard Legal Checklist drives missing-document
    creation.

    The checklist defines ~80 items across 17 firm sections (A-Q). With
    an empty data room every item must be flagged; uploading a document
    that covers a given checklist key must remove THAT key from the
    missing list (without spuriously removing unrelated items).
    """

    def test_all_items_missing_when_no_documents(self, db, test_deal, agent):
        from packages.agents.dd_checklist import CHECKLIST
        agent.run(test_deal.id, db)
        keys = {
            m.document_category
            for m in db.query(MissingDocument)
            .filter(MissingDocument.deal_id == test_deal.id)
            .all()
        }
        assert keys == {item["key"] for item in CHECKLIST}

    def test_bylaws_detected_via_filename(self, db, test_deal, agent):
        # A.2 — Atto costitutivo e statuto sociale vigente
        _make_doc(db, test_deal, filename="statuto_aggiornato.pdf",
                  raw_text="Statuto della società" * 20)
        agent.run(test_deal.id, db)
        missing = {
            m.document_category
            for m in db.query(MissingDocument)
            .filter(MissingDocument.deal_id == test_deal.id)
            .all()
        }
        assert "A.2" not in missing

    def test_visura_detected_via_raw_text(self, db, test_deal, agent):
        # A.1 — Visure estratte dal Registro Imprese
        _make_doc(db, test_deal, filename="company_overview.pdf",
                  raw_text="VISURA CAMERALE Registro Imprese di Milano" * 20)
        agent.run(test_deal.id, db)
        missing = {
            m.document_category
            for m in db.query(MissingDocument)
            .filter(MissingDocument.deal_id == test_deal.id)
            .all()
        }
        assert "A.1" not in missing

    def test_loan_agreement_detected_via_raw_text(self, db, test_deal, agent):
        # C.2 — Contratti di mutuo, finanziamento e leasing finanziario
        _make_doc(db, test_deal, filename="financing.pdf",
                  raw_text="LOAN AGREEMENT dated 1 January between Lender and Borrower." * 5)
        agent.run(test_deal.id, db)
        missing = {
            m.document_category
            for m in db.query(MissingDocument)
            .filter(MissingDocument.deal_id == test_deal.id)
            .all()
        }
        assert "C.2" not in missing

    def test_litigation_list_detected_via_italian_keyword(self, db, test_deal, agent):
        # I.1 — Elenco contenziosi pendenti
        _make_doc(db, test_deal, filename="elenco_contenziosi.pdf",
                  raw_text="Elenco contenziosi pendenti alla data odierna." * 10)
        agent.run(test_deal.id, db)
        missing = {
            m.document_category
            for m in db.query(MissingDocument)
            .filter(MissingDocument.deal_id == test_deal.id)
            .all()
        }
        assert "I.1" not in missing

    def test_missing_doc_reason_holds_full_request(self, db, test_deal, agent):
        """The intake stores the verbatim request text in `reason`."""
        agent.run(test_deal.id, db)
        # Pick a known item to assert the exact text persisted.
        md = (
            db.query(MissingDocument)
            .filter(
                MissingDocument.deal_id == test_deal.id,
                MissingDocument.document_category == "A.1",
            )
            .first()
        )
        assert md is not None
        assert "Registro Imprese" in md.reason

    def test_missing_doc_expected_item_carries_section_label(self, db, test_deal, agent):
        agent.run(test_deal.id, db)
        md = (
            db.query(MissingDocument)
            .filter(
                MissingDocument.deal_id == test_deal.id,
                MissingDocument.document_category == "A.1",
            )
            .first()
        )
        assert md is not None
        assert md.expected_item.startswith("A.1")
        assert "societari" in md.expected_item.lower()

    def test_missing_doc_priority_comes_from_checklist(self, db, test_deal, agent):
        """High-priority items keep high; medium/low items follow the checklist."""
        from packages.agents.dd_checklist import CHECKLIST
        agent.run(test_deal.id, db)
        by_key = {
            m.document_category: m
            for m in db.query(MissingDocument)
            .filter(MissingDocument.deal_id == test_deal.id)
            .all()
        }
        for item in CHECKLIST:
            assert by_key[item["key"]].priority == item["priority"]

    def test_result_missing_checklist_items_list(self, db, test_deal, agent):
        from packages.agents.dd_checklist import CHECKLIST
        result = agent.run(test_deal.id, db)
        assert set(result["missing_checklist_items"]) == {
            item["key"] for item in CHECKLIST
        }


# ── 5. Return-value structure ──────────────────────────────────────────────

class TestReturnValue:

    def test_has_all_required_keys(self, db, test_deal, agent):
        result = agent.run(test_deal.id, db)
        assert "deal_id" in result
        assert "documents_analyzed" in result
        assert "issues" in result
        assert "agent_findings_count" in result
        assert "missing_checklist_items" in result
        assert "missing_documents_count" in result

    def test_issues_dict_has_all_keys(self, db, test_deal, agent):
        result = agent.run(test_deal.id, db)
        issues = result["issues"]
        assert "empty_documents" in issues
        assert "small_documents" in issues
        assert "duplicate_groups" in issues

    def test_deal_id_matches(self, db, test_deal, agent):
        result = agent.run(test_deal.id, db)
        assert result["deal_id"] == test_deal.id

    def test_documents_analyzed_counts_all_docs(self, db, test_deal, agent):
        for i in range(4):
            _make_doc(db, test_deal, filename=f"doc_{i}.txt")
        result = agent.run(test_deal.id, db)
        assert result["documents_analyzed"] == 4

    def test_agent_findings_count_matches_db(self, db, test_deal, agent):
        _make_doc(db, test_deal, raw_text=None)              # empty
        _make_doc(db, test_deal, raw_text="tiny" * 5)        # small
        result = agent.run(test_deal.id, db)
        db_count = (
            db.query(AgentFinding)
            .filter(
                AgentFinding.deal_id == test_deal.id,
                AgentFinding.agent_name == AGENT_NAME,
            )
            .count()
        )
        assert result["agent_findings_count"] == db_count


# ── 6. AgentRun tracking ───────────────────────────────────────────────────

class TestAgentRunTracking:

    def test_agent_run_created(self, db, test_deal, agent):
        agent.run(test_deal.id, db)
        run = (
            db.query(AgentRun)
            .filter(
                AgentRun.deal_id == test_deal.id,
                AgentRun.agent_name == AGENT_NAME,
            )
            .first()
        )
        assert run is not None

    def test_agent_run_status_completed(self, db, test_deal, agent):
        agent.run(test_deal.id, db)
        run = (
            db.query(AgentRun)
            .filter(
                AgentRun.deal_id == test_deal.id,
                AgentRun.agent_name == AGENT_NAME,
            )
            .first()
        )
        assert run.status == AgentRunStatus.completed

    def test_agent_run_has_started_at(self, db, test_deal, agent):
        agent.run(test_deal.id, db)
        run = (
            db.query(AgentRun)
            .filter(AgentRun.deal_id == test_deal.id, AgentRun.agent_name == AGENT_NAME)
            .first()
        )
        assert run.started_at is not None

    def test_agent_run_has_completed_at(self, db, test_deal, agent):
        agent.run(test_deal.id, db)
        run = (
            db.query(AgentRun)
            .filter(AgentRun.deal_id == test_deal.id, AgentRun.agent_name == AGENT_NAME)
            .first()
        )
        assert run.completed_at is not None

    def test_agent_run_completed_after_started(self, db, test_deal, agent):
        agent.run(test_deal.id, db)
        run = (
            db.query(AgentRun)
            .filter(AgentRun.deal_id == test_deal.id, AgentRun.agent_name == AGENT_NAME)
            .first()
        )
        assert run.completed_at >= run.started_at


# ── 7. Idempotency ────────────────────────────────────────────────────────

class TestIdempotency:

    def test_findings_count_stable(self, db, test_deal, agent):
        _make_doc(db, test_deal, raw_text=None)          # empty
        _make_doc(db, test_deal, raw_text="x" * 50)      # small

        agent.run(test_deal.id, db)
        c1 = (
            db.query(AgentFinding)
            .filter(AgentFinding.deal_id == test_deal.id, AgentFinding.agent_name == AGENT_NAME)
            .count()
        )
        agent.run(test_deal.id, db)
        c2 = (
            db.query(AgentFinding)
            .filter(AgentFinding.deal_id == test_deal.id, AgentFinding.agent_name == AGENT_NAME)
            .count()
        )
        assert c1 == c2

    def test_missing_documents_not_duplicated(self, db, test_deal, agent):
        agent.run(test_deal.id, db)
        c1 = db.query(MissingDocument).filter(MissingDocument.deal_id == test_deal.id).count()
        agent.run(test_deal.id, db)
        c2 = db.query(MissingDocument).filter(MissingDocument.deal_id == test_deal.id).count()
        assert c1 == c2

    def test_agent_run_not_accumulated(self, db, test_deal, agent):
        """Each re-run should replace the previous AgentRun, not add another."""
        agent.run(test_deal.id, db)
        agent.run(test_deal.id, db)
        count = (
            db.query(AgentRun)
            .filter(AgentRun.deal_id == test_deal.id, AgentRun.agent_name == AGENT_NAME)
            .count()
        )
        assert count == 1

    def test_duplicate_groups_stable(self, db, test_deal, agent):
        text = "Same content repeated for duplicate test. " * 10
        _make_doc(db, test_deal, filename="a.txt", raw_text=text)
        _make_doc(db, test_deal, filename="b.txt", raw_text=text)
        r1 = agent.run(test_deal.id, db)
        r2 = agent.run(test_deal.id, db)
        assert r1["issues"]["duplicate_groups"] == r2["issues"]["duplicate_groups"]


# ── 8. Edge cases ─────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_deal_not_found_raises_value_error(self, db, agent):
        with pytest.raises(ValueError, match="Deal 99999 not found"):
            agent.run(99999, db)

    def test_no_documents_no_findings(self, db, test_deal, agent):
        result = agent.run(test_deal.id, db)
        assert result["documents_analyzed"] == 0
        assert result["agent_findings_count"] == 0
        assert result["issues"] == {
            "empty_documents": 0,
            "small_documents": 0,
            "duplicate_groups": 0,
        }

    def test_no_documents_all_checklist_items_missing(self, db, test_deal, agent):
        from packages.agents.dd_checklist import CHECKLIST
        result = agent.run(test_deal.id, db)
        assert result["missing_documents_count"] == len(CHECKLIST)

    def test_pending_documents_also_checked(self, db, test_deal, agent):
        """Documents with status=pending (not yet processed) must still be audited."""
        _make_doc(db, test_deal, filename="pending.pdf", raw_text=None,
                  status=DocumentStatus.pending)
        result = agent.run(test_deal.id, db)
        assert result["documents_analyzed"] == 1
        assert result["issues"]["empty_documents"] == 1

    def test_mixed_issues_all_detected(self, db, test_deal, agent):
        text = "Duplicate content for the mixed-issue test. " * 10
        _make_doc(db, test_deal, filename="empty.pdf", raw_text=None)
        _make_doc(db, test_deal, filename="small.pdf", raw_text="Stub text." * 3)
        _make_doc(db, test_deal, filename="dup_a.pdf", raw_text=text)
        _make_doc(db, test_deal, filename="dup_b.pdf", raw_text=text)
        result = agent.run(test_deal.id, db)
        assert result["issues"]["empty_documents"] == 1
        assert result["issues"]["small_documents"] == 1
        assert result["issues"]["duplicate_groups"] == 1

    def test_module_level_run_intake_function(self, db, test_deal):
        result = run_intake(test_deal.id, db)
        assert result["deal_id"] == test_deal.id
        assert "issues" in result

    def test_finding_title_contains_filename(self, db, test_deal, agent):
        _make_doc(db, test_deal, filename="important_contract.pdf", raw_text=None)
        agent.run(test_deal.id, db)
        f = _findings(db, test_deal, category="empty_document")[0]
        assert "important_contract.pdf" in f.title
