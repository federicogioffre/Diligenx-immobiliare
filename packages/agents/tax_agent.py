"""Tax documentary-review agent.

Analyses tax documents in the data room (dichiarazioni, avvisi di
accertamento, cartelle, rateizzazioni, interpelli, TP documentation, …)
and extracts findings relevant to an Italian share acquisition, persisted
as ``AgentFinding`` rows (``agent_name = "tax_analysis"``) that flow into
the red-flag aggregation stage.

Scope
-----
This is a *documentary* review: it reads what is in the data room and
raises red flags with citations. It does not substitute a full tax due
diligence by the client's tax advisors — the report boilerplate states
this explicitly.

Document selection
------------------
When ``document_ids`` is *None* the agent auto-detects tax documents by
keyword matching (normalised filename + first 1 500 characters of body
text, Italian and English keywords). The orchestrator additionally passes
``routed_document_ids`` — documents the routing stage classified as
``tax`` — which are unioned with the auto-detected set, so routing rescues
documents the keywords miss and vice versa.

Finding types
-------------
``finding_type`` is stored in ``AgentFinding.category`` and must be one of
``_VALID_FINDING_TYPES`` (tax_assessment, tax_litigation, tax_debt,
tax_credit, tax_regime, tax_losses, transfer_pricing, tax_compliance,
other_tax).

Deterministic heuristics
------------------------
``_TAX_HEURISTICS`` provides a safety net for the highest-signal Italian
tax red flags: when a heuristic keyword appears in the document text and
the LLM produced no finding of that type for the document, a floor
finding is written (``structured_payload_json.source = "heuristic"``),
so a notified assessment can never be silently dropped.

Idempotency
-----------
Re-running for the same deal deletes this agent's previous ``AgentRun``
and ``AgentFinding`` rows before writing fresh results.
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

AGENT_NAME = "tax_analysis"

_VALID_FINDING_TYPES = frozenset({
    "tax_assessment",
    "tax_litigation",
    "tax_debt",
    "tax_credit",
    "tax_regime",
    "tax_losses",
    "transfer_pricing",
    "tax_compliance",
    "other_tax",
})

# Keywords used to recognise tax documents automatically. Matching is
# case-insensitive against the normalised filename (underscores / hyphens
# replaced with spaces) and the first 1 500 chars of raw_text.
_TAX_DOC_KEYWORDS = [
    # Italian
    "dichiarazione dei redditi",
    "modello redditi",
    "modello unico",
    "avviso di accertamento",
    "avviso bonario",
    "processo verbale di constatazione",
    "cartella di pagamento",
    "cartella esattoriale",
    "agenzia delle entrate",
    "agenzia entrate riscossione",
    "rateizzazione",
    "ravvedimento operoso",
    "consolidato fiscale",
    "iva di gruppo",
    "patent box",
    "interpello",
    "credito d'imposta",
    "crediti d'imposta",
    "transfer pricing",
    "contenzioso tributario",
    "giustizia tributaria",
    "commissione tributaria",
    "imposta sostitutiva",
    "certificazione unica",
    "modello 770",
    "modello f24",
    "durf",
    # English
    "tax return",
    "tax assessment",
    "tax ruling",
    "tax litigation",
    "tax settlement",
    "vat return",
    "withholding tax",
]

# Deterministic red-flag floor: (keyword, finding_type, title, severity).
# Matched case-insensitively against the FULL document text. A floor
# finding is written only when the LLM produced no finding of the same
# type for that document.
_TAX_HEURISTICS: list[tuple[str, str, str, str]] = [
    (
        "avviso di accertamento",
        "tax_assessment",
        "Tax assessment referenced in the document",
        "high",
    ),
    (
        "processo verbale di constatazione",
        "tax_assessment",
        "Tax audit report (PVC) referenced in the document",
        "high",
    ),
    (
        "cartella di pagamento",
        "tax_debt",
        "Tax-collection notice (cartella) referenced in the document",
        "high",
    ),
    (
        "cartella esattoriale",
        "tax_debt",
        "Tax-collection notice (cartella) referenced in the document",
        "high",
    ),
    (
        "rateizzazione",
        "tax_debt",
        "Tax instalment plan referenced in the document",
        "medium",
    ),
    (
        "ravvedimento operoso",
        "tax_compliance",
        "Voluntary correction (ravvedimento) referenced in the document",
        "medium",
    ),
]

_HEURISTIC_CONFIDENCE = 0.60


# ── Agent ────────────────────────────────────────────────────────────────────


class TaxAgent:
    """LLM-powered tax documentary-review agent with deterministic floors.

    Usage::

        agent = TaxAgent()
        result = agent.run(deal_id, db)

        # Explicit document IDs (bypasses auto-detection):
        result = agent.run(deal_id, db, document_ids={10, 11})

        # Auto-detection unioned with routing output:
        result = agent.run(deal_id, db, routed_document_ids={12})

    Or use the module-level convenience wrapper :func:`run_tax_analysis`.
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
        routed_document_ids: set[int] | None = None,
    ) -> dict:
        """Extract tax findings from documents in *deal_id*.

        Parameters
        ----------
        deal_id:
            ID of the deal whose documents should be analysed.
        db:
            Active SQLAlchemy session.
        document_ids:
            Optional set of document IDs to analyse. When *None*, the agent
            auto-detects tax documents by keyword matching, unioned with
            *routed_document_ids*. Pass an empty set to produce a
            zero-finding result without querying the LLM.
        routed_document_ids:
            Document IDs the routing stage classified as tax documents.
            Only used when *document_ids* is None.

        Returns::

            {
                "deal_id": int,
                "documents_analyzed": int,
                "agent_findings_count": int,
                "heuristic_findings_count": int,
                "findings_by_severity": {"low": int, "medium": int, "high": int},
                "findings_by_finding_type": {"tax_assessment": int, ...},
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

        # ── 0. Validate deal ──────────────────────────────────────────── #
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        logger.info(
            "[%s] deal=%d ('%s') — starting tax documentary review",
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
            documents = self._resolve_documents(
                db, deal_id, document_ids, routed_document_ids
            )

            logger.info(
                "[%s] deal=%d — %d document(s) to analyse",
                self.AGENT_NAME, deal_id, len(documents),
            )

            all_findings: list = []
            heuristic_count = 0
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
                lambda pair: self._tax_payloads(pair[0].filename, pair[1], pair[0].id),
            )

            for (doc, text), payloads in zip(to_analyse, payload_lists):
                # Deterministic floor for high-signal Italian tax red flags.
                floor_payloads = self._heuristic_payloads(text, payloads)
                heuristic_count += len(floor_payloads)

                doc_findings = self._persist_findings(
                    doc, payloads + floor_payloads, deal_id, db
                )
                all_findings.extend(doc_findings)

                logger.info(
                    "[%s] deal=%d doc=%d — %d finding(s) (%d heuristic)",
                    self.AGENT_NAME, deal_id, doc.id,
                    len(doc_findings), len(floor_payloads),
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

            result = self._build_result(
                deal_id, all_findings, findings_by_document, heuristic_count
            )
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
        self,
        db: Session,
        deal_id: int,
        document_ids: set[int] | None,
        routed_document_ids: set[int] | None,
    ) -> list:
        """Return the documents that should be analysed.

        * ``document_ids=None``   → auto-detect by keyword matching, unioned
          with ``routed_document_ids`` (routing-stage classifications).
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
            routed = routed_document_ids or set()
            docs = [
                d for d in docs
                if d.id in routed or self._is_tax_document(d)
            ]
            logger.info(
                "[%s] deal=%d — selected %d tax doc(s) (auto-detection ∪ routing)",
                self.AGENT_NAME, deal_id, len(docs),
            )

        return docs

    def _is_tax_document(self, doc) -> bool:
        """Return True if *doc* looks like a tax document.

        Matching is performed against:
        * the normalised filename (lower-case, underscores/hyphens → spaces)
        * the first 1 500 characters of ``raw_text`` (lower-case)
        """
        normalised_filename = (
            doc.filename.lower()
            .replace("_", " ")
            .replace("-", " ")
        )
        snippet = (doc.raw_text or "")[:1500].lower()
        haystack = normalised_filename + " " + snippet
        return any(kw in haystack for kw in _TAX_DOC_KEYWORDS)

    # ── Finding extraction ──────────────────────────────────────────────

    def _tax_payloads(
        self,
        filename: str,
        text: str,
        document_id: int,
    ) -> list[dict]:
        """Call the LLM and return normalized finding payload dicts.

        PURE with respect to the database — safe to run on a worker thread
        (see packages.agents.concurrency). Persistence happens separately in
        :meth:`_persist_findings`.
        """
        from packages.prompts.deal_prompts import TAX_ANALYSIS_PROMPT

        prompt = TAX_ANALYSIS_PROMPT.format(
            filename=filename,
            text=text[:8000],
        )
        raw = self._llm.complete(prompt, max_tokens=2048)

        try:
            items = _safe_json(raw)
        except Exception:
            logger.warning(
                "[%s] doc=%d — tax parse error: %r",
                self.AGENT_NAME, document_id, raw,
            )
            items = []

        payloads: list[dict] = []
        for item in items if isinstance(items, list) else []:
            finding_type = item.get("finding_type", "other_tax")
            if finding_type not in _VALID_FINDING_TYPES:
                finding_type = "other_tax"

            severity_str = _normalize_severity(str(item.get("severity", "")).lower())

            payloads.append({
                "finding_type": finding_type,
                "title": str(item.get("title", ""))[:100],
                "description": str(item.get("description", ""))[:400],
                "severity": severity_str,
                "confidence": item.get("confidence"),
                "source": "llm",
            })
        return payloads

    def _heuristic_payloads(
        self, text: str, llm_payloads: list[dict]
    ) -> list[dict]:
        """Deterministic floor findings the LLM must not silently drop.

        For each heuristic whose keyword appears in *text*, emit a finding
        unless the LLM already produced one of the same ``finding_type``
        for this document.
        """
        lowered = text.lower()
        covered_types = {p["finding_type"] for p in llm_payloads}
        seen_types: set[str] = set()

        payloads: list[dict] = []
        for keyword, finding_type, title, severity in _TAX_HEURISTICS:
            if finding_type in covered_types or finding_type in seen_types:
                continue
            if keyword in lowered:
                payloads.append({
                    "finding_type": finding_type,
                    "title": title,
                    "description": (
                        f'The document mentions "{keyword}". The exposure was '
                        "not extracted by the analysis and must be verified "
                        "with a tax specialist."
                    ),
                    "severity": severity,
                    "confidence": _HEURISTIC_CONFIDENCE,
                    "source": "heuristic",
                })
                seen_types.add(finding_type)
        return payloads

    def _persist_findings(
        self, doc, payloads: list[dict], deal_id: int, db: Session
    ) -> list:
        """Create one ``AgentFinding`` per payload. Main-thread only."""
        from app.models.agent_finding import AgentFinding
        from app.models.red_flag import Severity

        findings: list = []
        for p in payloads:
            finding = AgentFinding(
                deal_id=deal_id,
                document_id=doc.id,
                agent_name=self.AGENT_NAME,
                category=p["finding_type"],
                title=p["title"],
                description=p["description"],
                severity=Severity(p["severity"]),
                confidence=p["confidence"],
                structured_payload_json={
                    "finding_type": p["finding_type"],
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "source": p["source"],
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
        heuristic_count: int,
    ) -> dict:
        findings_by_severity: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
        findings_by_finding_type: dict[str, int] = {t: 0 for t in _VALID_FINDING_TYPES}

        for f in all_findings:
            sev = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
            if sev in findings_by_severity:
                findings_by_severity[sev] += 1
            cat = f.category
            if cat in findings_by_finding_type:
                findings_by_finding_type[cat] += 1

        return {
            "deal_id": deal_id,
            "documents_analyzed": len(findings_by_document),
            "agent_findings_count": len(all_findings),
            "heuristic_findings_count": heuristic_count,
            "findings_by_severity": findings_by_severity,
            "findings_by_finding_type": findings_by_finding_type,
            "findings_by_document": findings_by_document,
        }


# ── Module-level convenience function ────────────────────────────────────────


def run_tax_analysis(
    deal_id: int,
    db: Session,
    *,
    document_ids: set[int] | None = None,
    routed_document_ids: set[int] | None = None,
    provider: LLMProvider | None = None,
) -> dict:
    """Create a :class:`TaxAgent` and run the tax documentary review."""
    return TaxAgent(provider=provider).run(
        deal_id, db,
        document_ids=document_ids,
        routed_document_ids=routed_document_ids,
    )
