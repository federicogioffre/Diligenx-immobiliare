"""Corporate governance analysis agent.

Analyses corporate governance documents (articles of association, bylaws,
shareholder agreements, board minutes/resolutions, etc.) and extracts
governance insights that are persisted as ``AgentFinding`` rows.

Auto-detection
--------------
When ``document_ids`` is *None*, the agent inspects every *processed*
document in the deal and selects those whose normalised filename or first
1 000 characters of body text contain at least one of the recognised
corporate-governance keywords (see ``_CORPORATE_DOC_KEYWORDS``).

Insight types
-------------
``insight_type`` is stored in ``AgentFinding.category`` and must be one of:

* ``governance_structure``  — board composition, decision-making authority, quorum
* ``voting_threshold``       — supermajority requirements, special voting classes
* ``transfer_restriction``   — ROFR, lock-up, drag-along/tag-along
* ``veto_right``             — provisions blocking decisions for one party
* ``unusual_clause``         — non-standard or contentious provisions

Severity mapping
----------------
* ``low``    → informational, standard provision worth noting
* ``medium`` → governance complexity, requires ongoing monitoring
* ``high``   → potential blocker: deadlock / restricted operations

Idempotency
-----------
Re-running for the same deal deletes this agent's previous ``AgentRun`` and
``AgentFinding`` rows before writing fresh results.  An ``AgentRun`` record
tracks every execution.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import (
    LLMProvider,
    get_llm_provider,
    _safe_json,
    _normalize_severity,
)

logger = logging.getLogger(__name__)

# ── Public constants ─────────────────────────────────────────────────────────

AGENT_NAME = "corporate_governance"

# ── Internal constants ───────────────────────────────────────────────────────

_VALID_INSIGHT_TYPES = frozenset({
    "governance_structure",
    "voting_threshold",
    "transfer_restriction",
    "veto_right",
    "unusual_clause",
})

# Keywords used to recognise corporate-governance documents automatically.
# Matching is case-insensitive against the normalised filename (underscores /
# hyphens replaced with spaces) and the first 1 000 chars of raw_text.
_CORPORATE_DOC_KEYWORDS = [
    "articles of association",
    "articles of incorporation",
    "memorandum of association",
    "bylaws",
    "by-laws",
    "operating agreement",
    "shareholder agreement",
    "shareholders agreement",
    "shareholders' agreement",
    "board minutes",
    "board resolution",
    "board resolutions",
    "minutes of board",
    "minutes of meeting",
    "shareholder resolution",
    "annual general meeting",
    "extraordinary general meeting",
    "corporate governance",
]


# ── Agent ────────────────────────────────────────────────────────────────────


class CorporateAgent:
    """LLM-powered corporate-governance insight extractor.

    Usage::

        agent = CorporateAgent()
        result = agent.run(deal_id, db)

        # Or supply explicit document IDs to analyse:
        result = agent.run(deal_id, db, document_ids={10, 11})

    Or use the module-level convenience wrapper :func:`run_corporate_analysis`.
    """

    AGENT_NAME = AGENT_NAME

    def __init__(self, provider: LLMProvider | None = None):
        self._llm = provider or get_llm_provider()

    # ── Public entry point ──────────────────────────────────────────────

    def run(
        self,
        deal_id: int,
        db: Session,
        *,
        document_ids: set[int] | None = None,
    ) -> dict:
        """Extract corporate-governance insights from documents in *deal_id*.

        Parameters
        ----------
        deal_id:
            ID of the deal whose documents should be analysed.
        db:
            Active SQLAlchemy session.
        document_ids:
            Optional set of document IDs to analyse.  When *None*, the agent
            auto-detects corporate-governance documents by keyword matching.
            Pass an empty set to produce a zero-finding result without
            querying the LLM.

        Returns::

            {
                "deal_id": int,
                "documents_analyzed": int,       # docs actually processed
                "agent_findings_count": int,      # total AgentFinding rows written
                "findings_by_severity": {         # count per severity level
                    "low": int,
                    "medium": int,
                    "high": int,
                },
                "findings_by_insight_type": {     # count per insight_type
                    "governance_structure": int,
                    ...
                },
                "findings_by_document": [
                    {"document_id": int, "filename": str, "finding_count": int},
                    ...
                ],
            }

        Raises ``ValueError`` if *deal_id* does not exist.
        """
        from app.models.deal import Deal
        from app.models.agent_finding import AgentFinding
        from app.models.agent_run import AgentRun, AgentRunStatus
        from app.models.red_flag import Severity

        # ── 0. Validate deal ──────────────────────────────────────────── #
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        logger.info(
            "[%s] deal=%d ('%s') — starting corporate governance analysis",
            self.AGENT_NAME, deal_id, deal.title,
        )

        # ── 1. Idempotency: wipe previous outputs ─────────────────────── #
        db.query(AgentRun).filter(
            AgentRun.deal_id == deal_id,
            AgentRun.agent_name == self.AGENT_NAME,
        ).delete(synchronize_session=False)

        db.query(AgentFinding).filter(
            AgentFinding.deal_id == deal_id,
            AgentFinding.agent_name == self.AGENT_NAME,
        ).delete(synchronize_session=False)

        db.flush()

        # ── 2. Open AgentRun ──────────────────────────────────────────── #
        run = AgentRun(
            deal_id=deal_id,
            agent_name=self.AGENT_NAME,
            status=AgentRunStatus.running,
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()

        try:
            # ── 3. Resolve documents to analyse ──────────────────────── #
            documents = self._resolve_documents(db, deal_id, document_ids)

            logger.info(
                "[%s] deal=%d — %d document(s) to analyse",
                self.AGENT_NAME, deal_id, len(documents),
            )

            all_findings: list = []
            findings_by_document: list[dict] = []

            # LLM+parse per document is pure → fan out on a bounded pool;
            # ORM persistence happens below on this thread, in input order.
            to_analyse = []
            for doc in documents:
                text = (doc.raw_text or "").strip()
                if text:
                    to_analyse.append((doc, text))
                else:
                    logger.warning(
                        "[%s] deal=%d doc=%d — no text, skipping",
                        self.AGENT_NAME, deal_id, doc.id,
                    )

            from packages.agents.concurrency import run_llm_tasks

            payload_lists = run_llm_tasks(
                to_analyse,
                lambda pair: self._governance_payloads(pair[0].filename, pair[1], pair[0].id),
            )

            for (doc, _), payloads in zip(to_analyse, payload_lists):
                # ── 4. Persist one AgentFinding per insight ───────────── #
                doc_findings = self._persist_insights(doc, payloads, deal_id, db)
                all_findings.extend(doc_findings)

                logger.info(
                    "[%s] deal=%d doc=%d — extracted %d insight(s)",
                    self.AGENT_NAME, deal_id, doc.id, len(doc_findings),
                )

                findings_by_document.append({
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "finding_count": len(doc_findings),
                })

            db.flush()

            # ── 5. Mark AgentRun completed ────────────────────────────── #
            run.completed_at = datetime.now(timezone.utc)
            run.status = AgentRunStatus.completed
            _started = run.started_at
            if _started is not None and _started.tzinfo is None:
                _started = _started.replace(tzinfo=timezone.utc)
            _duration = (run.completed_at - _started).total_seconds() if _started is not None else 0.0
            db.flush()

            result = self._build_result(deal_id, all_findings, findings_by_document)
            logger.info(
                "[%s] deal=%d — completed in %.2fs: %s",
                self.AGENT_NAME, deal_id, _duration, result,
            )
            return result

        except Exception as exc:
            logger.exception(
                "[%s] deal=%d — analysis failed", self.AGENT_NAME, deal_id
            )
            run.completed_at = datetime.now(timezone.utc)
            run.status = AgentRunStatus.failed
            run.error_message = str(exc)[:2000]
            _started = run.started_at
            if _started is not None and _started.tzinfo is None:
                _started = _started.replace(tzinfo=timezone.utc)
            _duration = (run.completed_at - _started).total_seconds() if _started is not None else 0.0
            logger.warning(
                "[%s] deal=%d — FAILED in %.2fs: %s",
                self.AGENT_NAME, deal_id, _duration, str(exc)[:200],
            )
            db.flush()
            raise

    # ── Document resolution ─────────────────────────────────────────────

    def _resolve_documents(
        self, db: Session, deal_id: int, document_ids: set[int] | None
    ) -> list:
        """Return the documents that should be analysed.

        * ``document_ids=None``   → auto-detect by keyword matching.
        * ``document_ids=set()``  → empty list (caller wants zero docs).
        * ``document_ids={…}``    → filter processed docs to given IDs.
        """
        from app.models.document import Document, DocumentStatus

        if document_ids is not None and not document_ids:
            return []

        query = db.query(Document).filter(
            Document.deal_id == deal_id,
            Document.status == DocumentStatus.processed,
        )
        if document_ids is not None:
            query = query.filter(Document.id.in_(document_ids))

        docs = query.all()

        if document_ids is None:
            # Auto-detection: keep only corporate-governance documents.
            docs = [d for d in docs if self._is_corporate_document(d)]
            logger.info(
                "[%s] deal=%d — auto-detected %d corporate-governance doc(s)",
                self.AGENT_NAME, deal_id, len(docs),
            )

        return docs

    def _is_corporate_document(self, doc) -> bool:
        """Return True if *doc* looks like a corporate-governance document.

        Matching is performed against:
        * the normalised filename (lower-case, underscores/hyphens → spaces)
        * the first 1 000 characters of ``raw_text`` (lower-case)
        """
        normalised_filename = (
            doc.filename.lower()
            .replace("_", " ")
            .replace("-", " ")
        )
        snippet = (doc.raw_text or "")[:1000].lower()
        haystack = normalised_filename + " " + snippet
        return any(kw in haystack for kw in _CORPORATE_DOC_KEYWORDS)

    # ── Insight extraction ──────────────────────────────────────────────

    def _governance_payloads(
        self,
        filename: str,
        text: str,
        document_id: int,
    ) -> list[dict]:
        """Call the LLM and return normalized insight payload dicts.

        PURE with respect to the database — safe to run on a worker thread
        (see packages.agents.concurrency). Persistence happens separately in
        :meth:`_persist_insights`.
        """
        from packages.prompts.deal_prompts import CORPORATE_GOVERNANCE_PROMPT

        prompt = CORPORATE_GOVERNANCE_PROMPT.format(
            filename=filename,
            text=text[:8000],
        )
        raw = self._llm.complete(prompt, max_tokens=2048)

        try:
            items = _safe_json(raw)
        except Exception:
            logger.warning(
                "[%s] doc=%d — governance parse error: %r",
                self.AGENT_NAME, document_id, raw,
            )
            items = []

        payloads: list[dict] = []
        for item in items if isinstance(items, list) else []:
            insight_type = item.get("insight_type", "unusual_clause")
            if insight_type not in _VALID_INSIGHT_TYPES:
                insight_type = "unusual_clause"

            # Normalize the LLM severity onto the 3-level scale. Crucially this
            # maps "critical" → "high" (a critical governance risk must not be
            # silently downgraded to "low"); anything unrecognised → "medium".
            severity_str = _normalize_severity(str(item.get("severity", "")).lower())

            payloads.append({
                "insight_type": insight_type,
                "title": str(item.get("title", ""))[:100],
                "description": str(item.get("description", ""))[:400],
                "severity": severity_str,
                "confidence": item.get("confidence"),
            })
        return payloads

    def _persist_insights(self, doc, payloads: list[dict], deal_id: int, db: Session) -> list:
        """Create one ``AgentFinding`` per payload. Main-thread only."""
        from app.models.agent_finding import AgentFinding
        from app.models.red_flag import Severity

        findings: list = []
        for p in payloads:
            finding = AgentFinding(
                deal_id=deal_id,
                document_id=doc.id,
                agent_name=self.AGENT_NAME,
                category=p["insight_type"],
                title=p["title"],
                description=p["description"],
                severity=Severity(p["severity"]),
                confidence=p["confidence"],
                structured_payload_json={
                    "insight_type": p["insight_type"],
                    "document_id": doc.id,
                    "filename": doc.filename,
                },
            )
            db.add(finding)
            findings.append(finding)

        db.flush()
        return findings

    # ── Result builder ──────────────────────────────────────────────────

    def _build_result(
        self,
        deal_id: int,
        all_findings: list,
        findings_by_document: list[dict],
    ) -> dict:
        findings_by_severity: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
        findings_by_insight_type: dict[str, int] = {t: 0 for t in _VALID_INSIGHT_TYPES}

        for f in all_findings:
            sev = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
            if sev in findings_by_severity:
                findings_by_severity[sev] += 1
            cat = f.category
            if cat in findings_by_insight_type:
                findings_by_insight_type[cat] += 1

        return {
            "deal_id": deal_id,
            "documents_analyzed": len(findings_by_document),
            "agent_findings_count": len(all_findings),
            "findings_by_severity": findings_by_severity,
            "findings_by_insight_type": findings_by_insight_type,
            "findings_by_document": findings_by_document,
        }


# ── Module-level convenience function ────────────────────────────────────────


def run_corporate_analysis(
    deal_id: int,
    db: Session,
    *,
    document_ids: set[int] | None = None,
    provider: LLMProvider | None = None,
) -> dict:
    """Create a :class:`CorporateAgent` and run the governance analysis pipeline."""
    return CorporateAgent(provider=provider).run(
        deal_id, db, document_ids=document_ids
    )
