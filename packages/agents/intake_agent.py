"""Data-room intake agent.

Performs **deterministic** (LLM-free) data-quality checks on every document
attached to a deal and identifies gaps in the standard due-diligence
document set.

Checks performed
----------------
* **Empty documents** — ``raw_text`` is absent or blank after stripping.
  Severity: ``high``  (document is functionally useless).
* **Small documents** — text is present but shorter than
  ``SMALL_DOC_THRESHOLD`` characters.
  Severity: ``low``  (document may be a cover page or stub).
* **Duplicate documents** — two or more documents share the same MD5 hash
  of their stripped text content.
  Severity: ``medium``  (redundant uploads create confusion).

Category gaps
-------------
The agent checks whether the data room covers four standard categories.
Any category that is absent gets a ``MissingDocument`` record with
``priority = high``.

Expected categories
~~~~~~~~~~~~~~~~~~~
* ``corporate_documents``  — incorporation, bylaws, board resolutions, …
* ``commercial_contracts`` — service/purchase/license agreements, …
* ``financing_documents``  — loans, notes, term sheets, warrants, …
* ``litigation_documents`` — complaints, court orders, settlements, …

Idempotency
-----------
Re-running the agent for the same deal deletes its previous
``AgentFinding`` rows and all ``MissingDocument`` rows for the deal before
writing fresh results.  An ``AgentRun`` record tracks every execution.
"""
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Public constants ──────────────────────────────────────────────────────

AGENT_NAME = "data_room_intake"

#: Documents whose stripped text is shorter than this are flagged as *small*.
SMALL_DOC_THRESHOLD = 200

# ── Category keyword index ────────────────────────────────────────────────
# Keys are the exact ``document_category`` values stored in MissingDocument.
# Each keyword list contains lower-case fragments that are searched inside a
# normalised needle composed of the document filename (underscores/hyphens
# replaced with spaces) plus the first 1 000 characters of raw text.

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "corporate_documents": [
        "certificate of incorporation",
        "articles of incorporation",
        "articles of association",
        "bylaws",
        "by-laws",
        "shareholders agreement",
        "shareholder agreement",
        "cap table",
        "capitalization table",
        "board minutes",
        "board resolution",
        "operating agreement",
        "memorandum of association",
        "company registration",
    ],
    "commercial_contracts": [
        "service agreement",
        "services agreement",
        "purchase agreement",
        "sales agreement",
        "customer agreement",
        "vendor agreement",
        "supplier agreement",
        "distribution agreement",
        "license agreement",
        "licensing agreement",
        "master service",
        "statement of work",
        "partnership agreement",
        "commercial contract",
    ],
    "financing_documents": [
        "loan agreement",
        "credit agreement",
        "credit facility",
        "promissory note",
        "convertible note",
        "term loan",
        "revolving credit",
        "security agreement",
        "pledge agreement",
        "warrant agreement",
        "subscription agreement",
        "investment agreement",
        "term sheet",
    ],
    "litigation_documents": [
        "litigation",
        "complaint",
        "lawsuit",
        "court order",
        "judgment",
        "arbitration",
        "settlement agreement",
        "cease and desist",
        "demand letter",
        "subpoena",
        "deposition",
        "mediation",
        "legal proceedings",
    ],
}

# Human-readable description for each category (used in MissingDocument).
_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "corporate_documents": (
        "Incorporation certificate, bylaws, shareholder agreements, "
        "board resolutions, or cap table"
    ),
    "commercial_contracts": (
        "Service agreements, purchase agreements, license agreements, "
        "or other commercial contracts"
    ),
    "financing_documents": (
        "Loan agreements, promissory notes, term sheets, warrant agreements, "
        "or other financing instruments"
    ),
    "litigation_documents": (
        "Court filings, arbitration records, settlement agreements, "
        "or other litigation-related documents"
    ),
}


# ── Agent ─────────────────────────────────────────────────────────────────


class DataRoomIntakeAgent:
    """LLM-free data-quality and completeness checker for deal data rooms.

    Usage::

        agent = DataRoomIntakeAgent()
        result = agent.run(deal_id, db)

    Or use the module-level convenience wrapper :func:`run_intake`.
    """

    AGENT_NAME = AGENT_NAME
    SMALL_DOC_THRESHOLD = SMALL_DOC_THRESHOLD

    # ── Public entry point ─────────────────────────────────────────────

    def run(self, deal_id: int, db: Session) -> dict:
        """Analyse the data room for *deal_id* and persist findings.

        Returns::

            {
                "deal_id": int,
                "documents_analyzed": int,
                "issues": {
                    "empty_documents":  int,
                    "small_documents":  int,
                    "duplicate_groups": int,
                },
                "agent_findings_count":  int,
                "missing_categories":    list[str],
                "missing_documents_count": int,
            }

        Raises ``ValueError`` if *deal_id* does not exist.
        """
        from app.models.deal import Deal
        from app.models.document import Document
        from app.models.agent_run import AgentRun, AgentRunStatus
        from app.models.agent_finding import AgentFinding
        from app.models.missing_document import MissingDocument
        from app.models.red_flag import Severity
        from app.models.open_question import Priority

        # ── 0. Validate deal ──────────────────────────────────────── #
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        logger.info(
            "[%s] deal=%d ('%s') — starting data-room intake",
            self.AGENT_NAME, deal_id, deal.title,
        )

        # ── 1. Idempotency: wipe previous outputs ─────────────────── #
        db.query(AgentRun).filter(
            AgentRun.deal_id == deal_id,
            AgentRun.agent_name == self.AGENT_NAME,
        ).delete(synchronize_session=False)

        db.query(AgentFinding).filter(
            AgentFinding.deal_id == deal_id,
            AgentFinding.agent_name == self.AGENT_NAME,
        ).delete(synchronize_session=False)

        # MissingDocument has no agent_name column; this agent owns the table
        # for its deal scope.
        db.query(MissingDocument).filter(
            MissingDocument.deal_id == deal_id,
        ).delete(synchronize_session=False)

        db.flush()

        # ── 2. Open AgentRun ──────────────────────────────────────── #
        run = AgentRun(
            deal_id=deal_id,
            agent_name=self.AGENT_NAME,
            status=AgentRunStatus.running,
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()

        try:
            # ── 3. Fetch all documents (regardless of status) ──────── #
            documents = (
                db.query(Document)
                .filter(Document.deal_id == deal_id)
                .all()
            )
            logger.info(
                "[%s] deal=%d — %d documents found",
                self.AGENT_NAME, deal_id, len(documents),
            )

            all_findings: list[AgentFinding] = []

            # ── 4a. Empty documents ────────────────────────────────── #
            empty_docs = self._detect_empty(documents)
            for doc in empty_docs:
                f = AgentFinding(
                    deal_id=deal_id,
                    document_id=doc.id,
                    agent_name=self.AGENT_NAME,
                    category="empty_document",
                    title=f"Empty document: {doc.filename}",
                    description=(
                        f"Document '{doc.filename}' contains no extractable text. "
                        "It may be a corrupt file, a scanned image without OCR, "
                        "or a document that failed processing."
                    ),
                    severity=Severity.high,
                    confidence=1.0,
                    structured_payload_json={
                        "reason": "no_text",
                        "filename": doc.filename,
                        "file_size_bytes": doc.file_size,
                        "status": doc.status.value if doc.status else None,
                    },
                )
                db.add(f)
                all_findings.append(f)

            logger.info(
                "[%s] deal=%d — %d empty documents",
                self.AGENT_NAME, deal_id, len(empty_docs),
            )

            # ── 4b. Small documents ────────────────────────────────── #
            small_docs = self._detect_small(documents)
            for doc in small_docs:
                char_count = len((doc.raw_text or "").strip())
                f = AgentFinding(
                    deal_id=deal_id,
                    document_id=doc.id,
                    agent_name=self.AGENT_NAME,
                    category="small_document",
                    title=f"Very small document: {doc.filename}",
                    description=(
                        f"Document '{doc.filename}' contains only {char_count} "
                        f"characters (minimum expected: {self.SMALL_DOC_THRESHOLD}). "
                        "The file may be incomplete, a cover page, or a placeholder."
                    ),
                    severity=Severity.low,
                    confidence=1.0,
                    structured_payload_json={
                        "reason": "below_threshold",
                        "filename": doc.filename,
                        "char_count": char_count,
                        "threshold": self.SMALL_DOC_THRESHOLD,
                    },
                )
                db.add(f)
                all_findings.append(f)

            logger.info(
                "[%s] deal=%d — %d small documents",
                self.AGENT_NAME, deal_id, len(small_docs),
            )

            # ── 4c. Duplicate documents ────────────────────────────── #
            duplicate_groups = self._detect_duplicates(documents)
            for content_hash, dup_docs in duplicate_groups.items():
                dup_ids = [d.id for d in dup_docs]
                dup_names = [d.filename for d in dup_docs]

                for doc in dup_docs:
                    others = [n for n in dup_names if n != doc.filename]
                    f = AgentFinding(
                        deal_id=deal_id,
                        document_id=doc.id,
                        agent_name=self.AGENT_NAME,
                        category="duplicate_document",
                        title=f"Duplicate document: {doc.filename}",
                        description=(
                            f"Document '{doc.filename}' has identical content to "
                            f"{len(dup_docs) - 1} other document(s): "
                            f"{', '.join(others)}."
                        ),
                        severity=Severity.medium,
                        confidence=1.0,
                        structured_payload_json={
                            "reason": "identical_content",
                            "filename": doc.filename,
                            "content_hash": content_hash,
                            "duplicate_document_ids": dup_ids,
                        },
                    )
                    db.add(f)
                    all_findings.append(f)

            logger.info(
                "[%s] deal=%d — %d duplicate group(s) (%d documents total)",
                self.AGENT_NAME, deal_id,
                len(duplicate_groups),
                sum(len(g) for g in duplicate_groups.values()),
            )

            # ── 5. Missing categories ──────────────────────────────── #
            missing_category_names = self._detect_missing_categories(documents)
            missing_records: list[MissingDocument] = []

            for category in missing_category_names:
                md = MissingDocument(
                    deal_id=deal_id,
                    document_category=category,
                    expected_item=_CATEGORY_DESCRIPTIONS.get(category, category),
                    reason=(
                        f"No documents matching the '{category.replace('_', ' ')}' "
                        "category were identified in the data room. This document "
                        "set is typically required for comprehensive due diligence."
                    ),
                    priority=Priority.high,
                )
                db.add(md)
                missing_records.append(md)

            logger.info(
                "[%s] deal=%d — %d missing categories: %s",
                self.AGENT_NAME, deal_id,
                len(missing_category_names), missing_category_names,
            )

            db.flush()

            # ── 6. Mark AgentRun completed ─────────────────────────── #
            run.completed_at = datetime.now(timezone.utc)
            run.status = AgentRunStatus.completed
            db.flush()

            result = {
                "deal_id": deal_id,
                "documents_analyzed": len(documents),
                "issues": {
                    "empty_documents": len(empty_docs),
                    "small_documents": len(small_docs),
                    "duplicate_groups": len(duplicate_groups),
                },
                "agent_findings_count": len(all_findings),
                "missing_categories": missing_category_names,
                "missing_documents_count": len(missing_records),
            }
            logger.info(
                "[%s] deal=%d — intake complete: %s",
                self.AGENT_NAME, deal_id, result,
            )
            return result

        except Exception as exc:
            logger.exception("[%s] deal=%d — intake failed", self.AGENT_NAME, deal_id)
            run.completed_at = datetime.now(timezone.utc)
            run.status = AgentRunStatus.failed
            run.error_message = str(exc)[:2000]
            db.flush()
            raise

    # ── Detection helpers ──────────────────────────────────────────────

    @staticmethod
    def _compute_content_hash(text: str) -> str:
        """Return the MD5 hex digest of the stripped text content."""
        return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()

    def _detect_empty(self, documents: list) -> list:
        """Return documents whose text is absent or blank after stripping."""
        return [d for d in documents if not (d.raw_text or "").strip()]

    def _detect_small(self, documents: list) -> list:
        """Return documents whose text is present but below the threshold.

        Documents that are *empty* are excluded — they are handled separately
        by :meth:`_detect_empty`.
        """
        return [
            d for d in documents
            if (d.raw_text or "").strip()                           # has content
            and len((d.raw_text or "").strip()) < self.SMALL_DOC_THRESHOLD
        ]

    def _detect_duplicates(self, documents: list) -> dict[str, list]:
        """Return groups of documents that share identical text content.

        Returns a mapping ``{content_hash: [doc, ...]}`` where every group
        contains **at least two** documents.  Documents with no text are
        excluded because their shared hash would produce false positives.
        """
        hash_map: dict[str, list] = {}
        for doc in documents:
            text = (doc.raw_text or "").strip()
            if not text:
                continue  # empty docs flagged separately; skip to avoid false duplicates
            h = self._compute_content_hash(text)
            hash_map.setdefault(h, []).append(doc)

        return {h: docs for h, docs in hash_map.items() if len(docs) > 1}

    def _classify_document(self, doc) -> set[str]:
        """Return the set of due-diligence categories this document covers.

        The search needle combines a normalised filename (underscores and
        hyphens replaced with spaces) with the first 1 000 characters of
        extracted text, both lower-cased.
        """
        filename_normalised = (
            (doc.filename or "")
            .lower()
            .replace("_", " ")
            .replace("-", " ")
        )
        needle = filename_normalised + " " + (doc.raw_text or "")[:1000].lower()

        matched: set[str] = set()
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in needle for kw in keywords):
                matched.add(category)
        return matched

    def _detect_missing_categories(self, documents: list) -> list[str]:
        """Return the list of standard categories not covered by any document."""
        present: set[str] = set()
        for doc in documents:
            present.update(self._classify_document(doc))
        return [cat for cat in _CATEGORY_KEYWORDS if cat not in present]


# ── Module-level convenience function ─────────────────────────────────────


def run_intake(deal_id: int, db: Session) -> dict:
    """Create a :class:`DataRoomIntakeAgent` and run the intake pipeline."""
    return DataRoomIntakeAgent().run(deal_id, db)
