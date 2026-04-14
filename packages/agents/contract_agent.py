"""Contract analysis agent.

Extracts clauses from contract-type documents using the LLM and persists
them as ``ClauseFinding`` rows.  Also creates one ``AgentFinding`` summary
record per analysed document so that the broader multi-agent system can
reference the extraction result without querying ``ClauseFinding`` directly.

Clause extraction
-----------------
* Sends up to 8 000 characters of document text to the LLM via
  ``CLAUSE_EXTRACTION_PROMPT`` and parses a JSON array of clause objects.
* Clause-type values not in ``_VALID_CLAUSE_TYPES`` are coerced to
  ``"other"`` rather than raising an error.

AgentFinding summaries
----------------------
One ``AgentFinding`` per document (``category = "clause_extraction_summary"``)
is written after extraction.  Its ``structured_payload_json`` contains::

    {
        "clause_count": int,
        "clause_types": list[str],   # distinct types found, sorted
        "document_id": int,
        "filename": str,
    }

Idempotency
-----------
Re-running the agent for the same deal deletes its previous ``AgentFinding``
rows and all ``ClauseFinding`` rows for documents in the deal before writing
fresh results.  An ``AgentRun`` record tracks every execution.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import (
    LLMProvider,
    get_llm_provider,
    _safe_json,
    _VALID_CLAUSE_TYPES,
    DealAnalysisAgent,
    is_grounded,
    _MIN_CONFIDENCE,
)

logger = logging.getLogger(__name__)

# ── Public constants ────────────────────────────────────────────────────────

AGENT_NAME = "contract_analysis"


# ── Agent ───────────────────────────────────────────────────────────────────


class ContractAgent:
    """LLM-powered clause extractor for contract documents.

    Usage::

        agent = ContractAgent()
        result = agent.run(deal_id, db)

        # Or restrict to specific document IDs:
        result = agent.run(deal_id, db, contract_document_ids={42, 55})

    Or use the module-level convenience wrapper :func:`run_contract_analysis`.
    """

    AGENT_NAME = AGENT_NAME

    # Keywords that identify a clause as being about CCNL / collective bargaining
    # content rather than M&A-relevant obligations.
    _CCNL_CLAUSE_KEYWORDS: tuple[str, ...] = (
        "contratto collettivo nazionale",
        "contratto collettivo di lavoro",
        "accordo collettivo nazionale",
        "accordo collettivo",
        "ccnl",
        "contratto nazionale di lavoro",
        "national collective bargaining",
        "collective bargaining agreement",
    )

    # Clause types that CAN be M&A-relevant even inside a CCNL document.
    # All other types extracted from a CCNL document are discarded without an
    # LLM call, since they are virtually never relevant for a share acquisition.
    _CCNL_RELEVANT_CLAUSE_TYPES: frozenset[str] = frozenset({
        "non_compete",
        "indemnification",
        "change_of_control",
        "termination",
        "warranty",
    })

    def __init__(self, provider: LLMProvider | None = None):
        self._llm = provider or get_llm_provider()

    # ── Public entry point ──────────────────────────────────────────────

    def run(
        self,
        deal_id: int,
        db: Session,
        *,
        contract_document_ids: set[int] | None = None,
    ) -> dict:
        """Extract clauses from contract documents in *deal_id*.

        Parameters
        ----------
        deal_id:
            ID of the deal whose documents should be analysed.
        db:
            Active SQLAlchemy session.
        contract_document_ids:
            Optional set of document IDs to analyse.  When *None*, every
            processed document in the deal is analysed.  Pass an empty set
            to produce a zero-clause result without querying the LLM.

        Returns::

            {
                "deal_id": int,
                "contract_documents": int,        # documents actually processed
                "clause_findings_count": int,     # total ClauseFinding rows written
                "agent_findings_count": int,      # one AgentFinding per document
                "clauses_by_document": [
                    {"document_id": int, "filename": str, "clause_count": int},
                    ...
                ],
            }

        Raises ``ValueError`` if *deal_id* does not exist.
        """
        from app.models.deal import Deal
        from app.models.document import Document, DocumentStatus
        from app.models.clause_finding import ClauseFinding
        from app.models.agent_finding import AgentFinding
        from app.models.agent_run import AgentRun, AgentRunStatus
        from app.models.red_flag import Severity

        # ── 0. Validate deal ──────────────────────────────────────── #
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        logger.info(
            "[%s] deal=%d ('%s') — starting contract analysis",
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

        # Clear ClauseFinding rows for all documents in this deal.
        doc_ids_in_deal = [
            row.id
            for row in db.query(Document.id)
            .filter(Document.deal_id == deal_id)
            .all()
        ]
        if doc_ids_in_deal:
            db.query(ClauseFinding).filter(
                ClauseFinding.document_id.in_(doc_ids_in_deal)
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
            # ── 3. Determine documents to analyse ──────────────────── #
            if contract_document_ids is not None and not contract_document_ids:
                # Caller explicitly requested zero documents.
                documents = []
            else:
                query = db.query(Document).filter(
                    Document.deal_id == deal_id,
                    Document.status == DocumentStatus.processed,
                )
                if contract_document_ids is not None:
                    query = query.filter(Document.id.in_(contract_document_ids))
                documents = query.all()

            logger.info(
                "[%s] deal=%d — %d document(s) to analyse",
                self.AGENT_NAME, deal_id, len(documents),
            )

            all_clause_findings: list = []
            all_agent_findings: list = []
            clauses_by_document: list[dict] = []

            for doc in documents:
                text = (doc.raw_text or "").strip()
                if not text:
                    logger.warning(
                        "[%s] deal=%d doc=%d — no text, skipping",
                        self.AGENT_NAME, deal_id, doc.id,
                    )
                    continue

                # ── 4. CCNL detection ─────────────────────────────── #
                is_ccnl = self._is_ccnl(doc.filename, text)

                # ── 5. Extract clauses via LLM ─────────────────────── #
                doc_clauses = self._extract_clauses(doc.id, text, db)

                logger.info(
                    "[%s] deal=%d doc=%d — extracted %d clause(s) (pre-filter)",
                    self.AGENT_NAME, deal_id, doc.id, len(doc_clauses),
                )

                # ── 6. CCNL filtering + compliance analysis ────────── #
                if is_ccnl:
                    # CCNL documents: keep only the clause types that can
                    # occasionally be M&A-relevant (non-compete, indemnification,
                    # change-of-control, unusual termination, warranty).
                    # Everything else (working hours, pay scales, leave, union
                    # procedures, CCNL recitals) is discarded without an LLM call.
                    doc_clauses = self._filter_ccnl_document_clauses(doc_clauses, db)
                    # Run the dedicated CCNL compliance check for the 6 risk
                    # categories (wrong CCNL, classification, compensation,
                    # contributions, working time, termination procedures).
                    compliance_findings = self._analyze_ccnl_compliance(
                        doc.id, doc.filename, text, deal_id, db
                    )
                    all_agent_findings.extend(compliance_findings)
                else:
                    # Non-CCNL documents: remove individual clauses that merely
                    # cite CCNL provisions (boilerplate applicability recitals).
                    doc_clauses = self._remove_ccnl_clauses(doc_clauses, db)

                # ── 7. Relevance filtering (LLM) ─────────────────────── #
                doc_clauses = self._classify_and_filter_clauses(
                    doc_clauses, doc.filename, is_ccnl, db
                )
                all_clause_findings.extend(doc_clauses)

                logger.info(
                    "[%s] deal=%d doc=%d — %d relevant clause(s) kept after filtering",
                    self.AGENT_NAME, deal_id, doc.id, len(doc_clauses),
                )

                # ── 6. AgentFinding summary for this document ────────── #
                clause_types = sorted({cf.clause_type.value for cf in doc_clauses})
                confidences = [
                    cf.confidence
                    for cf in doc_clauses
                    if cf.confidence is not None
                ]
                avg_confidence = (
                    sum(confidences) / len(confidences) if confidences else None
                )

                summary = AgentFinding(
                    deal_id=deal_id,
                    document_id=doc.id,
                    agent_name=self.AGENT_NAME,
                    category="clause_extraction_summary",
                    title=(
                        f"Extracted {len(doc_clauses)} clause(s) from '{doc.filename}'"
                    ),
                    description=(
                        f"Contract analysis of '{doc.filename}' found "
                        f"{len(doc_clauses)} clause(s). "
                        + (
                            f"Types: {', '.join(clause_types)}."
                            if clause_types
                            else "No clauses identified."
                        )
                    ),
                    severity=Severity.low,
                    confidence=avg_confidence,
                    structured_payload_json={
                        "clause_count": len(doc_clauses),
                        "clause_types": clause_types,
                        "document_id": doc.id,
                        "filename": doc.filename,
                    },
                )
                db.add(summary)
                all_agent_findings.append(summary)

                clauses_by_document.append({
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "clause_count": len(doc_clauses),
                })

            db.flush()

            # ── 7. Mark AgentRun completed ─────────────────────────── #
            run.completed_at = datetime.now(timezone.utc)
            run.status = AgentRunStatus.completed
            _started = run.started_at
            if _started is not None and _started.tzinfo is None:
                _started = _started.replace(tzinfo=timezone.utc)
            _duration = (run.completed_at - _started).total_seconds() if _started is not None else 0.0
            db.flush()

            result = {
                "deal_id": deal_id,
                "contract_documents": len(clauses_by_document),
                "clause_findings_count": len(all_clause_findings),
                "agent_findings_count": len(all_agent_findings),
                "clauses_by_document": clauses_by_document,
            }
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

    # ── CCNL detection ──────────────────────────────────────────────────

    @staticmethod
    def _is_ccnl(filename: str, raw_text: str) -> bool:
        """Return True if the document looks like a national collective bargaining agreement."""
        haystack = filename.lower() + " " + raw_text[:2000].lower()
        indicators = [
            "contratto collettivo nazionale",
            "contratto collettivo di lavoro",
            "accordo collettivo nazionale",
            "ccnl",
            "contratto nazionale di lavoro",
            "national collective bargaining",
        ]
        return any(kw in haystack for kw in indicators)

    # ── CCNL clause-level filter ────────────────────────────────────────

    def _remove_ccnl_clauses(self, findings: list, db) -> list:
        """Deterministically remove clauses whose content references CCNL.

        This handles non-CCNL documents (employment agreements, service
        agreements, etc.) that contain individual clauses about CCNL
        applicability or standard collective-bargaining provisions — all of
        which are irrelevant for an M&A share acquisition.

        No LLM call is made; removal is keyword-based.
        """
        from app.models.clause_finding import ClauseFinding as CF

        if not findings:
            return findings

        to_keep: list = []
        ids_to_delete: list[int] = []

        for cf in findings:
            haystack = (cf.title + " " + cf.content[:500]).lower()
            if any(kw in haystack for kw in self._CCNL_CLAUSE_KEYWORDS):
                if cf.id is not None:
                    ids_to_delete.append(cf.id)
            else:
                to_keep.append(cf)

        if ids_to_delete:
            db.query(CF).filter(CF.id.in_(ids_to_delete)).delete(
                synchronize_session=False
            )
            db.flush()
            logger.info(
                "[%s] — removed %d CCNL-referencing clause(s)",
                self.AGENT_NAME, len(ids_to_delete),
            )

        return to_keep

    def _analyze_ccnl_compliance(
        self,
        document_id: int,
        filename: str,
        text: str,
        deal_id: int,
        db,
    ) -> list:
        """Run the CCNL compliance check on a CCNL document.

        Checks for six specific risk categories that ARE relevant for M&A
        due diligence even in CCNL documents:
          1. ccnl_application  — wrong/expired/inconsistently applied CCNL
          2. classification    — job levels vs. actual duties
          3. compensation      — unpaid overtime, below-minimum salary
          4. contributions     — missing health/pension/bilateral funds
          5. working_time      — overtime limits, irregular shifts
          6. termination       — disciplinary procedures, notice periods

        Creates ``AgentFinding`` rows (category = "ccnl_compliance") for any
        issues found.  Returns the new finding objects (may be empty list).
        """
        from app.models.agent_finding import AgentFinding
        from app.models.red_flag import Severity
        from packages.prompts.deal_prompts import CCNL_COMPLIANCE_PROMPT

        _SEVERITY_MAP = {
            "low": Severity.low,
            "medium": Severity.medium,
            "high": Severity.high,
            "critical": Severity.critical,
        }

        prompt = CCNL_COMPLIANCE_PROMPT.format(
            filename=filename,
            text=text[:8000],
        )

        try:
            raw = self._llm.complete(prompt, max_tokens=4096)
            items = _safe_json(raw)
        except Exception as exc:
            logger.warning(
                "[%s] doc=%d '%s' — CCNL compliance check failed (%s); skipping",
                self.AGENT_NAME, document_id, filename, exc,
            )
            return []

        findings: list = []
        if not isinstance(items, list):
            return []

        for item in items:
            category = str(item.get("category", "ccnl_compliance"))[:100]
            title = str(item.get("title", "CCNL compliance issue"))[:500]
            description = str(item.get("description", ""))[:1000]
            severity_raw = item.get("severity", "low")
            severity = _SEVERITY_MAP.get(str(severity_raw).lower(), Severity.low)
            confidence = item.get("confidence")

            af = AgentFinding(
                deal_id=deal_id,
                document_id=document_id,
                agent_name=self.AGENT_NAME,
                category="ccnl_compliance",
                title=title,
                description=description,
                severity=severity,
                confidence=confidence,
                structured_payload_json={"ccnl_category": category},
            )
            db.add(af)
            findings.append(af)

        if findings:
            db.flush()
            logger.info(
                "[%s] deal=%d doc=%d '%s' — %d CCNL compliance finding(s)",
                self.AGENT_NAME, deal_id, document_id, filename, len(findings),
            )

        return findings

    def _filter_ccnl_document_clauses(self, findings: list, db) -> list:
        """For a CCNL document, discard clause types that are never M&A-relevant.

        Keeps only the types listed in ``_CCNL_RELEVANT_CLAUSE_TYPES``
        (non_compete, indemnification, change_of_control, termination, warranty).
        All other types (pay scales, working hours, leave, union procedures,
        etc.) are deleted immediately without an LLM call.
        """
        from app.models.clause_finding import ClauseFinding as CF

        if not findings:
            return findings

        to_keep: list = []
        ids_to_delete: list[int] = []

        for cf in findings:
            if cf.clause_type.value in self._CCNL_RELEVANT_CLAUSE_TYPES:
                to_keep.append(cf)
            else:
                if cf.id is not None:
                    ids_to_delete.append(cf.id)

        if ids_to_delete:
            db.query(CF).filter(CF.id.in_(ids_to_delete)).delete(
                synchronize_session=False
            )
            db.flush()
            logger.info(
                "[%s] — removed %d irrelevant clause(s) from CCNL document "
                "(kept %d for LLM review)",
                self.AGENT_NAME, len(ids_to_delete), len(to_keep),
            )

        return to_keep

    # ── Relevance classification & filtering ────────────────────────────

    def _classify_and_filter_clauses(
        self,
        findings: list,
        filename: str,
        is_ccnl: bool,
        db,
    ) -> list:
        """Classify each ClauseFinding for M&A relevance; keep only high/medium.

        The LLM is called once per document with all clauses in a single batch.
        Low-relevance findings are deleted from the DB. High/medium findings have
        their ``relevance_score`` and ``relevance_reason`` fields set.

        If classification fails for any reason, all clauses are retained (fail-open).
        """
        from app.models.clause_finding import ClauseFinding as CF
        from packages.prompts.deal_prompts import CLAUSE_RELEVANCE_PROMPT

        if not findings:
            return findings

        # Build compact input — use a content preview to save tokens.
        clauses_input = [
            {
                "clause_index": i,
                "clause_type": cf.clause_type.value,
                "title": cf.title,
                "content_preview": cf.content[:300],
            }
            for i, cf in enumerate(findings)
        ]

        prompt = CLAUSE_RELEVANCE_PROMPT.format(
            filename=filename,
            is_ccnl="YES — apply CCNL special rules" if is_ccnl else "NO",
            clauses_json=json.dumps(clauses_input, ensure_ascii=False, indent=2),
        )

        try:
            raw = self._llm.complete(prompt, max_tokens=4096)
            items = _safe_json(raw)
        except Exception as exc:
            logger.warning(
                "[%s] doc='%s' — relevance classification failed (%s); keeping all clauses",
                self.AGENT_NAME, filename, exc,
            )
            for cf in findings:
                cf.relevance_score = "high"
                cf.relevance_reason = "Relevance classification unavailable (kept by default)"
            db.flush()
            return findings

        # Build index → (relevance, reason) map from LLM response.
        relevance_map: dict[int, tuple[str, str]] = {}
        if isinstance(items, list):
            for item in items:
                idx = item.get("clause_index")
                if isinstance(idx, int):
                    rel = item.get("relevance", "medium")
                    if rel not in ("high", "medium", "low"):
                        rel = "medium"
                    relevance_map[idx] = (rel, str(item.get("reason", ""))[:500])

        to_keep: list = []
        ids_to_delete: list[int] = []

        for i, cf in enumerate(findings):
            relevance, reason = relevance_map.get(i, ("low", ""))
            if relevance in ("high", "medium"):
                # Set attributes ONLY on rows we keep to avoid StaleDataError
                # when SQLAlchemy tries to flush attribute changes on deleted rows.
                cf.relevance_score = relevance
                cf.relevance_reason = reason
                to_keep.append(cf)
            else:
                if cf.id is not None:
                    ids_to_delete.append(cf.id)

        if ids_to_delete:
            db.query(CF).filter(CF.id.in_(ids_to_delete)).delete(synchronize_session=False)
            logger.info(
                "[%s] doc='%s' — removed %d low-relevance clause(s), kept %d",
                self.AGENT_NAME, filename, len(ids_to_delete), len(to_keep),
            )

        db.flush()
        return to_keep

    # ── Extraction helper ───────────────────────────────────────────────

    def _extract_clauses(
        self,
        document_id: int,
        text: str,
        db: Session,
    ) -> list:
        """Send full document text to the LLM in batches and persist ClauseFinding rows.

        Uses the same batch-splitting logic as ``DealAnalysisAgent`` so that
        long contracts are fully analysed rather than silently truncated at
        8 000 characters.

        Returns the list of newly created (flushed) ``ClauseFinding`` objects.
        """
        from app.models.clause_finding import ClauseFinding, ClauseType
        from packages.prompts.deal_prompts import CLAUSE_EXTRACTION_PROMPT

        batches = DealAnalysisAgent._split_into_batches(text, DealAnalysisAgent._BATCH_CHARS)
        findings: list = []

        for batch_idx, batch_text in enumerate(batches):
            prompt = CLAUSE_EXTRACTION_PROMPT.format(
                text=batch_text,
                batch_info=(
                    f"(Part {batch_idx + 1} of {len(batches)})"
                    if len(batches) > 1
                    else ""
                ),
            )
            raw = self._llm.complete(prompt, max_tokens=8192)

            try:
                items = _safe_json(raw)
            except Exception as exc:
                logger.warning(
                    "[%s] doc=%d batch=%d — clause parse error (%s); "
                    "last 300 chars of response: %r",
                    self.AGENT_NAME, document_id, batch_idx, exc, raw[-300:],
                )
                items = []

            for item in items if isinstance(items, list) else []:
                content = item.get("content", "")
                confidence = item.get("confidence")

                # ── Grounding check ──────────────────────────────────── #
                if confidence is not None and confidence < _MIN_CONFIDENCE:
                    logger.debug(
                        "[%s] doc=%d batch=%d — dropped low-confidence clause "
                        "(%.2f): %r", self.AGENT_NAME, document_id, batch_idx,
                        confidence, item.get("title", ""),
                    )
                    continue

                if not is_grounded(content, batch_text):
                    logger.warning(
                        "[%s] doc=%d batch=%d — dropped hallucinated clause "
                        "(not found in source): %r | content: %r",
                        self.AGENT_NAME, document_id, batch_idx,
                        item.get("title", ""), content[:120],
                    )
                    continue

                clause_type_str = item.get("clause_type", "other")
                if clause_type_str not in _VALID_CLAUSE_TYPES:
                    clause_type_str = "other"
                finding = ClauseFinding(
                    document_id=document_id,
                    clause_type=ClauseType(clause_type_str),
                    title=str(item.get("title", ""))[:500],
                    content=content,
                    page_number=item.get("page_number"),
                    confidence=confidence,
                )
                db.add(finding)
                findings.append(finding)

        db.flush()
        return findings


# ── Module-level convenience function ──────────────────────────────────────


def run_contract_analysis(
    deal_id: int,
    db: Session,
    *,
    contract_document_ids: set[int] | None = None,
    provider: LLMProvider | None = None,
) -> dict:
    """Create a :class:`ContractAgent` and run the contract analysis pipeline."""
    return ContractAgent(provider=provider).run(
        deal_id, db, contract_document_ids=contract_document_ids
    )
