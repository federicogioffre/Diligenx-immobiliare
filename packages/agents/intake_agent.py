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

Checklist gaps
--------------
The agent matches every uploaded document against the standard DD checklist
(see :mod:`packages.agents.dd_checklist`). Any checklist item that no
uploaded document covers gets a ``MissingDocument`` row with the item's
ready-to-render Italian question stored in ``reason`` — the report agent
renders those rows verbatim in the "Information Requests" section.

Idempotency
-----------
Re-running the agent for the same deal deletes its previous
``AgentFinding`` rows and all ``MissingDocument`` rows for the deal before
writing fresh results. An ``AgentRun`` record tracks every execution.
"""
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.agents.dd_checklist import CHECKLIST, matched_keys

logger = logging.getLogger(__name__)

# ── Public constants ──────────────────────────────────────────────────────

AGENT_NAME = "data_room_intake"

#: Documents whose stripped text is shorter than this are flagged as *small*.
SMALL_DOC_THRESHOLD = 200


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

            # ── 5. Missing checklist items ─────────────────────────── #
            missing_item_keys = self._detect_missing_checklist_items(documents)
            missing_records: list[MissingDocument] = []

            items_by_key = {item["key"]: item for item in CHECKLIST}
            for key in missing_item_keys:
                item = items_by_key[key]
                # expected_item is String(500); keep a short label there
                # (firm code + section name), full request goes in reason.
                expected = f"{item['key']} — {item['section_name_it']}"
                md = MissingDocument(
                    deal_id=deal_id,
                    document_category=key,
                    expected_item=expected[:480],
                    reason=item["request_it"],
                    priority=item["priority"],
                )
                db.add(md)
                missing_records.append(md)

            logger.info(
                "[%s] deal=%d — %d missing checklist items: %s",
                self.AGENT_NAME, deal_id,
                len(missing_item_keys), missing_item_keys[:10],
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
                "missing_checklist_items": missing_item_keys,
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
        """Return the set of checklist item keys this document covers."""
        return matched_keys(doc.filename, doc.raw_text)

    def _detect_missing_checklist_items(self, documents: list) -> list[str]:
        """Return the list of checklist item keys not covered by any document.

        Order follows :data:`packages.agents.dd_checklist.CHECKLIST` so the
        rendered Information Requests section groups items by DD area in
        the same sequence used elsewhere in the report.
        """
        present: set[str] = set()
        for doc in documents:
            present.update(self._classify_document(doc))
        return [item["key"] for item in CHECKLIST if item["key"] not in present]


# ── Module-level convenience function ─────────────────────────────────────


def run_intake(deal_id: int, db: Session) -> dict:
    """Create a :class:`DataRoomIntakeAgent` and run the intake pipeline."""
    return DataRoomIntakeAgent().run(deal_id, db)
