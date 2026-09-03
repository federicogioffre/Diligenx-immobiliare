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

            # ── 4. Analyse documents (LLM) — fanned out ───────────── #
            # The whole per-document analysis (extraction, CCNL filters,
            # compliance check, relevance classification) is pure — LLM
            # calls plus in-memory filtering — so documents fan out on a
            # bounded pool. Only the surviving payloads are persisted below,
            # on this thread, in input order (Sessions aren't thread-safe;
            # this also removes the old insert-then-delete churn).
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

            analyses = run_llm_tasks(
                to_analyse,
                lambda pair: self._analyze_document_payloads(
                    pair[0].id, pair[0].filename, pair[1]
                ),
            )

            # ── 5. Persist results (main thread, input order) ──────── #
            from app.models.clause_finding import ClauseFinding, ClauseType

            for (doc, _), analysis in zip(to_analyse, analyses):
                doc_clauses: list = []
                for p in analysis["clauses"]:
                    finding = ClauseFinding(
                        document_id=doc.id,
                        clause_type=ClauseType(p["clause_type"]),
                        title=p["title"],
                        content=p["content"],
                        page_number=p["page_number"],
                        confidence=p["confidence"],
                        relevance_score=p["relevance_score"],
                        relevance_reason=p["relevance_reason"],
                    )
                    db.add(finding)
                    doc_clauses.append(finding)

                all_clause_findings.extend(doc_clauses)

                compliance_findings = self._persist_compliance_findings(
                    doc, analysis["compliance"], deal_id, db
                )
                all_agent_findings.extend(compliance_findings)

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

    # ── Per-document analysis (pure, thread-safe) ───────────────────────

    def _analyze_document_payloads(
        self,
        document_id: int,
        filename: str,
        text: str,
    ) -> dict:
        """Full per-document analysis as pure LLM + in-memory filtering.

        PURE with respect to the database — safe to run on a worker thread
        (see packages.agents.concurrency). Returns::

            {
                "is_ccnl": bool,
                "clauses": [payload dicts with relevance fields set],
                "compliance": [CCNL compliance payload dicts],
            }
        """
        is_ccnl = self._is_ccnl(filename, text)

        clauses = self._extract_clause_payloads(document_id, text)
        logger.info(
            "[%s] doc=%d — extracted %d clause(s) (pre-filter)",
            self.AGENT_NAME, document_id, len(clauses),
        )

        compliance: list[dict] = []
        if is_ccnl:
            # CCNL documents: keep only the clause types that can
            # occasionally be M&A-relevant (non-compete, indemnification,
            # change-of-control, unusual termination, warranty). Everything
            # else (working hours, pay scales, leave, union procedures,
            # CCNL recitals) is discarded without an LLM call.
            kept = [
                p for p in clauses
                if p["clause_type"] in self._CCNL_RELEVANT_CLAUSE_TYPES
            ]
            if len(kept) != len(clauses):
                logger.info(
                    "[%s] — removed %d irrelevant clause(s) from CCNL document "
                    "(kept %d for LLM review)",
                    self.AGENT_NAME, len(clauses) - len(kept), len(kept),
                )
            clauses = kept
            # Run the dedicated CCNL compliance check for the 6 risk
            # categories (wrong CCNL, classification, compensation,
            # contributions, working time, termination procedures).
            compliance = self._ccnl_compliance_payloads(document_id, filename, text)
        else:
            # Non-CCNL documents: remove individual clauses that merely
            # cite CCNL provisions (boilerplate applicability recitals).
            clauses = self._remove_ccnl_payloads(clauses)

        clauses = self._classify_relevance_payloads(clauses, filename, is_ccnl)

        return {"is_ccnl": is_ccnl, "clauses": clauses, "compliance": compliance}

    # ── CCNL clause-level filter ────────────────────────────────────────

    def _remove_ccnl_payloads(self, payloads: list[dict]) -> list[dict]:
        """Deterministically remove clause payloads that reference CCNL.

        This handles non-CCNL documents (employment agreements, service
        agreements, etc.) that contain individual clauses about CCNL
        applicability or standard collective-bargaining provisions — all of
        which are irrelevant for an M&A share acquisition.

        No LLM call is made; removal is keyword-based. Pure.
        """
        if not payloads:
            return payloads

        to_keep: list[dict] = []
        removed = 0
        for p in payloads:
            haystack = (p["title"] + " " + p["content"][:500]).lower()
            if any(kw in haystack for kw in self._CCNL_CLAUSE_KEYWORDS):
                removed += 1
            else:
                to_keep.append(p)

        if removed:
            logger.info(
                "[%s] — removed %d CCNL-referencing clause(s)",
                self.AGENT_NAME, removed,
            )
        return to_keep

    def _ccnl_compliance_payloads(
        self,
        document_id: int,
        filename: str,
        text: str,
    ) -> list[dict]:
        """Run the CCNL compliance check on a CCNL document. Pure.

        Checks for six specific risk categories that ARE relevant for M&A
        due diligence even in CCNL documents:
          1. ccnl_application  — wrong/expired/inconsistently applied CCNL
          2. classification    — job levels vs. actual duties
          3. compensation      — unpaid overtime, below-minimum salary
          4. contributions     — missing health/pension/bilateral funds
          5. working_time      — overtime limits, irregular shifts
          6. termination       — disciplinary procedures, notice periods

        PURE with respect to the database — safe to run on a worker thread.
        Returns payload dicts; persistence happens separately in
        :meth:`_persist_compliance_findings`.
        """
        from app.models.red_flag import Severity
        from packages.prompts.deal_prompts import CCNL_COMPLIANCE_PROMPT

        # "critical" from raw LLM output is normalized to high — the
        # Severity enum uses the 3-level scale of practitioner DD reports.
        _SEVERITY_MAP = {
            "low": Severity.low,
            "medium": Severity.medium,
            "high": Severity.high,
            "critical": Severity.high,
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

        if not isinstance(items, list):
            return []

        payloads: list[dict] = []
        for item in items:
            payloads.append({
                "category": str(item.get("category", "ccnl_compliance"))[:100],
                "title": str(item.get("title", "CCNL compliance issue"))[:500],
                "description": str(item.get("description", ""))[:1000],
                "severity": _SEVERITY_MAP.get(
                    str(item.get("severity", "low")).lower(), Severity.low
                ),
                "confidence": item.get("confidence"),
            })
        return payloads

    def _persist_compliance_findings(
        self, doc, payloads: list[dict], deal_id: int, db: Session
    ) -> list:
        """Create one ``AgentFinding`` per compliance payload. Main-thread only."""
        from app.models.agent_finding import AgentFinding

        findings: list = []
        for p in payloads:
            af = AgentFinding(
                deal_id=deal_id,
                document_id=doc.id,
                agent_name=self.AGENT_NAME,
                category="ccnl_compliance",
                title=p["title"],
                description=p["description"],
                severity=p["severity"],
                confidence=p["confidence"],
                structured_payload_json={"ccnl_category": p["category"]},
            )
            db.add(af)
            findings.append(af)

        if findings:
            db.flush()
            logger.info(
                "[%s] deal=%d doc=%d '%s' — %d CCNL compliance finding(s)",
                self.AGENT_NAME, deal_id, doc.id, doc.filename, len(findings),
            )

        return findings

    # ── Relevance classification & filtering ────────────────────────────

    def _classify_relevance_payloads(
        self,
        payloads: list[dict],
        filename: str,
        is_ccnl: bool,
    ) -> list[dict]:
        """Classify each clause payload for M&A relevance; keep only high/medium.

        The LLM is called once per document with all clauses in a single batch.
        Kept payloads get ``relevance_score`` and ``relevance_reason`` keys;
        low-relevance payloads are dropped.

        If classification fails for any reason, all clauses are retained
        (fail-open). PURE — safe to run on a worker thread.
        """
        from packages.prompts.deal_prompts import CLAUSE_RELEVANCE_PROMPT

        if not payloads:
            return payloads

        # Build compact input — use a content preview to save tokens.
        clauses_input = [
            {
                "clause_index": i,
                "clause_type": p["clause_type"],
                "title": p["title"],
                "content_preview": p["content"][:300],
            }
            for i, p in enumerate(payloads)
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
            for p in payloads:
                p["relevance_score"] = "high"
                p["relevance_reason"] = "Relevance classification unavailable (kept by default)"
            return payloads

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

        to_keep: list[dict] = []
        removed = 0
        for i, p in enumerate(payloads):
            relevance, reason = relevance_map.get(i, ("low", ""))
            if relevance in ("high", "medium"):
                p["relevance_score"] = relevance
                p["relevance_reason"] = reason
                to_keep.append(p)
            else:
                removed += 1

        if removed:
            logger.info(
                "[%s] doc='%s' — removed %d low-relevance clause(s), kept %d",
                self.AGENT_NAME, filename, removed, len(to_keep),
            )
        return to_keep

    # ── Extraction helper ───────────────────────────────────────────────

    def _extract_clause_payloads(
        self,
        document_id: int,
        text: str,
    ) -> list[dict]:
        """Send full document text to the LLM in batches; return clause payloads.

        Uses the same batch-splitting logic as ``DealAnalysisAgent`` so that
        long contracts are fully analysed rather than silently truncated at
        8 000 characters.

        PURE with respect to the database — safe to run on a worker thread.
        Returns dicts with keys ``clause_type``/``title``/``content``/
        ``page_number``/``confidence``; ``ClauseFinding`` rows are created
        later, on the main thread, only for payloads that survive filtering.
        """
        from packages.prompts.deal_prompts import CLAUSE_EXTRACTION_PROMPT

        batches = DealAnalysisAgent._split_into_batches(text, DealAnalysisAgent._BATCH_CHARS)
        payloads: list[dict] = []

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
                payloads.append({
                    "clause_type": clause_type_str,
                    "title": str(item.get("title", ""))[:500],
                    "content": content,
                    "page_number": item.get("page_number"),
                    "confidence": confidence,
                })

        return payloads


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
