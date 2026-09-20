"""Financial documentary-review agent.

Analyses financial documents in the data room (bilanci, note integrative,
relazioni sulla gestione, relazioni del collegio sindacale / della società
di revisione) and extracts findings that are legally relevant to an
Italian share acquisition, persisted as ``AgentFinding`` rows
(``agent_name = "financial_analysis"``) that flow into the red-flag
aggregation stage with ``area = financial``.

Scope
-----
This is a *legal* review of financial documents, not an accounting
analysis: it surfaces auditor qualifications, going-concern doubts,
statutory capital losses, covenants, related-party exposures and
guarantees — the facts a lawyer must reflect in the SPA. It does not
recompute figures or assess the business, and it does not substitute a
full financial due diligence by the client's accounting advisors; the
report boilerplate states this explicitly.

Document selection
------------------
When ``document_ids`` is *None* the agent auto-detects financial
documents by keyword matching (normalised filename + first 1 500
characters of body text, Italian and English keywords). The orchestrator
additionally passes ``routed_document_ids`` — documents the routing stage
classified as ``financial_statement`` — which are unioned with the
auto-detected set, so routing rescues documents the keywords miss and
vice versa.

Finding types
-------------
``finding_type`` is stored in ``AgentFinding.category`` and must be one of
``_VALID_FINDING_TYPES``. Alongside the statutory shapes (auditor_opinion,
going_concern, capital_loss, covenant, related_party, guarantee,
subsequent_event, equity_position) it covers the shapes every real
financial due-diligence report produces and that a purely accounting
reading of the statements would lose: ``debt_like_item`` (liabilities that
behave as financing — overdue tax and social-security debts, overdue
payables, leasing, factoring with recourse, cash that is not really
available, untaken holiday), ``receivables_at_risk``,
``accounting_irregularity``, ``concentration``, ``public_funding``,
``prior_deal_claim`` (warranty positions under the target's own earlier
acquisitions) and ``information_limitation`` — what the document itself
records as not provided, not reconciled or still in draft, which in the
reference reports is roughly a fifth of their content.

Amounts
-------
``amount_eur`` is populated only where the document states a figure, and
``amount_source`` records which case applies. The agent never estimates:
pricing an item belongs to the client's advisers. Covenant findings also
carry ``change_of_control_clause`` and ``financial_covenant`` as
tri-state flags, because those two booleans are the whole legal
deliverable of a financing review and "not stated" must stay distinct
from "stated as false".

Deterministic heuristics
------------------------
``_FINANCIAL_HEURISTICS`` provides a safety net for the highest-signal
Italian red flags: when a heuristic keyword appears in the document text
and the LLM produced no finding of that type, a floor finding is written
(``structured_payload_json.source = "heuristic"``), so a going-concern
paragraph or an art. 2446 c.c. loss can never be silently dropped. Each
entry may carry a note appended to the finding, used where a keyword has
a legal consequence the accounts do not state: negative equity points at
the dissolution cause, overdue tax and social-security debts oblige the
qualified public creditors to report the company under the business
crisis code, and "unaudited" is only a finding where an audit was
required in the first place.

Idempotency
-----------
Re-running for the same deal deletes this agent's previous ``AgentRun``
and ``AgentFinding`` rows before writing fresh results.
"""
import logging
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import (
    LLMProvider,
    get_llm_provider,
    _complete_llm_items,
    _normalize_severity,
)

logger = logging.getLogger(__name__)

# ── Public constants ─────────────────────────────────────────────────────────

AGENT_NAME = "financial_analysis"

_VALID_FINDING_TYPES = frozenset({
    "auditor_opinion",
    "going_concern",
    "capital_loss",
    "covenant",
    "related_party",
    "guarantee",
    "subsequent_event",
    "equity_position",
    # Shapes that recur in every real financial due-diligence report and
    # that a purely accounting reading of the statements would lose.
    "debt_like_item",
    "receivables_at_risk",
    "accounting_irregularity",
    "concentration",
    "public_funding",
    "prior_deal_claim",
    "information_limitation",
    "other_financial",
})

# Keywords used to recognise financial documents automatically. Matching is
# case-insensitive against the normalised filename (underscores / hyphens
# replaced with spaces) and the first 1 500 chars of raw_text.
_FINANCIAL_DOC_KEYWORDS = [
    # Italian
    "bilancio d'esercizio",
    "bilancio di esercizio",
    "bilancio consolidato",
    "bilancio abbreviato",
    "progetto di bilancio",
    "situazione patrimoniale",
    "stato patrimoniale",
    "conto economico",
    "nota integrativa",
    "rendiconto finanziario",
    "relazione sulla gestione",
    "relazione del collegio sindacale",
    "relazione della società di revisione",
    "relazione di revisione",
    "revisione legale dei conti",
    "continuità aziendale",
    "patrimonio netto",
    # English
    "financial statements",
    "balance sheet",
    "income statement",
    "profit and loss",
    "statement of cash flows",
    "notes to the financial statements",
    "auditor's report",
    "independent auditors report",
    "management report",
    "going concern",
]

class FinancialHeuristic(NamedTuple):
    """One deterministic floor: a keyword that must never be dropped."""

    keyword: str
    finding_type: str
    title: str
    severity: str
    note: str | None = None


# Overdue tax and social-security debts are not only a price item: past
# set thresholds they oblige the revenue agency, the collection agent and
# the social-security institution to report the debtor under the business
# crisis code. Carried on the keywords that surface them.
_UNAUDITED_NOTE = (
    "Only a finding where an audit was required: check the thresholds for "
    "appointing a control body under art. 2477 c.c."
)

_PUBLIC_CREDITOR_NOTE = (
    "Overdue tax and social-security debts above the statutory thresholds "
    "oblige the qualified public creditors to report the company under "
    "art. 25-novies of the business crisis code; verify whether any "
    "report has been served."
)

# Deterministic red-flag floor, matched case-insensitively against the FULL
# document text. A floor finding is written only when the LLM produced no
# finding of the same type for that document, and at most one per type.
#
# Article numbers are matched with their "art." prefix or "c.c." suffix: a
# bare "2446" would collide with amounts printed in the accounts.
_FINANCIAL_HEURISTICS: list[FinancialHeuristic] = [
    # ── Going concern and the crisis regime ──────────────────────────────
    FinancialHeuristic(
        "continuità aziendale",
        "going_concern",
        "Going concern referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "going concern",
        "going_concern",
        "Going concern referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "patrimonio netto negativo",
        "going_concern",
        "Negative net equity referenced in the document",
        "high",
        note=(
            "Negative equity is a legal event before it is an accounting "
            "one: check artt. 2446-2447 or 2482-bis-2482-ter c.c. and the "
            "dissolution cause under art. 2484 c.c."
        ),
    ),
    FinancialHeuristic(
        "deficit patrimoniale",
        "going_concern",
        "Equity deficit referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "composizione negoziata",
        "going_concern",
        "Negotiated crisis composition referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "concordato preventivo",
        "going_concern",
        "Composition with creditors referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "material uncertainty",
        "going_concern",
        "Material uncertainty on going concern referenced",
        "high",
    ),
    # ── Auditor's opinion ────────────────────────────────────────────────
    FinancialHeuristic(
        "giudizio con rilievi",
        "auditor_opinion",
        "Qualified audit opinion referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "giudizio negativo",
        "auditor_opinion",
        "Adverse audit opinion referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "impossibilità di esprimere un giudizio",
        "auditor_opinion",
        "Disclaimer of audit opinion referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "richiamo di informativa",
        "auditor_opinion",
        "Emphasis-of-matter paragraph referenced in the document",
        "medium",
    ),
    # Wording varies across sets of accounts ("non sottoposto", "non è
    # sottoposto", "non assoggettato"), so all three forms are matched.
    FinancialHeuristic(
        "non sottoposto a revisione",
        "auditor_opinion",
        "Financial statements not audited",
        "low",
        note=_UNAUDITED_NOTE,
    ),
    FinancialHeuristic(
        "non è sottoposto a revisione",
        "auditor_opinion",
        "Financial statements not audited",
        "low",
        note=_UNAUDITED_NOTE,
    ),
    FinancialHeuristic(
        "non assoggettato a revisione",
        "auditor_opinion",
        "Financial statements not audited",
        "low",
        note=_UNAUDITED_NOTE,
    ),
    FinancialHeuristic(
        "unaudited",
        "auditor_opinion",
        "Financial statements not audited",
        "low",
    ),
    # ── Capital losses ───────────────────────────────────────────────────
    FinancialHeuristic(
        "art. 2446",
        "capital_loss",
        "Loss reducing capital (art. 2446 c.c.) referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "2446 c.c.",
        "capital_loss",
        "Loss reducing capital (art. 2446 c.c.) referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "art. 2447",
        "capital_loss",
        "Loss below legal minimum (art. 2447 c.c.) referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "2447 c.c.",
        "capital_loss",
        "Loss below legal minimum (art. 2447 c.c.) referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "2482-bis",
        "capital_loss",
        "Loss reducing capital (art. 2482-bis c.c.) referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "2482-ter",
        "capital_loss",
        "Loss below legal minimum (art. 2482-ter c.c.) referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "art. 2484",
        "capital_loss",
        "Dissolution cause (art. 2484 c.c.) referenced in the document",
        "high",
    ),
    FinancialHeuristic(
        "perdite sospese",
        "capital_loss",
        "Losses deferred under the emergency regime referenced",
        "high",
        note=(
            "Losses postponed under the pandemic regime fall due at the "
            "fifth following financial year; verify the deadline and the "
            "note disclosure."
        ),
    ),
    # ── Financing ────────────────────────────────────────────────────────
    FinancialHeuristic(
        "covenant",
        "covenant",
        "Financial covenant referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "cross default",
        "covenant",
        "Cross-default clause referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "negative pledge",
        "covenant",
        "Negative pledge referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "change of control",
        "covenant",
        "Change-of-control clause in a financing agreement",
        "high",
        note=(
            "A change-of-control clause in a financing agreement can be "
            "triggered by the transaction itself; check whether consent or "
            "a waiver is required before closing."
        ),
    ),
    # ── Guarantees ───────────────────────────────────────────────────────
    FinancialHeuristic(
        "fideiussione",
        "guarantee",
        "Surety (fideiussione) referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "lettera di patronage",
        "guarantee",
        "Comfort letter referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "controgaranzia",
        "guarantee",
        "Counter-guarantee referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "polizza fideiussoria",
        "guarantee",
        "Surety insurance policy referenced in the document",
        "medium",
    ),
    # ── Related parties ──────────────────────────────────────────────────
    FinancialHeuristic(
        "art. 2467",
        "related_party",
        "Shareholder-loan subordination (art. 2467 c.c.) referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "2467 c.c.",
        "related_party",
        "Shareholder-loan subordination (art. 2467 c.c.) referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "postergazione",
        "related_party",
        "Shareholder-loan subordination (postergazione) referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "finanziamento soci",
        "related_party",
        "Shareholder loan referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "cash pooling",
        "related_party",
        "Cash pooling arrangement referenced in the document",
        "medium",
    ),
    # ── Debt-like items ──────────────────────────────────────────────────
    # Every financial due-diligence report in the reference set converges
    # on the same list, twelve years apart.
    FinancialHeuristic(
        "debiti tributari scaduti",
        "debt_like_item",
        "Overdue tax liabilities treated as debt-like",
        "high",
        note=_PUBLIC_CREDITOR_NOTE,
    ),
    FinancialHeuristic(
        "debiti previdenziali scaduti",
        "debt_like_item",
        "Overdue social-security liabilities treated as debt-like",
        "high",
        note=_PUBLIC_CREDITOR_NOTE,
    ),
    FinancialHeuristic(
        "debiti contributivi scaduti",
        "debt_like_item",
        "Overdue social-security liabilities treated as debt-like",
        "high",
        note=_PUBLIC_CREDITOR_NOTE,
    ),
    FinancialHeuristic(
        "ferie non godute",
        "debt_like_item",
        "Accrued untaken holiday treated as debt-like",
        "medium",
        note=(
            "Holiday accrued beyond the statutory carry-over period must "
            "be paid out."
        ),
    ),
    FinancialHeuristic(
        "indennità di fine rapporto agenti",
        "debt_like_item",
        "Agents' leaving indemnity treated as debt-like",
        "medium",
    ),
    FinancialHeuristic(
        "factoring pro solvendo",
        "debt_like_item",
        "Receivables factored with recourse treated as debt-like",
        "medium",
    ),
    # ── Receivables ──────────────────────────────────────────────────────
    FinancialHeuristic(
        "fatture da emettere",
        "receivables_at_risk",
        "Accrued revenue not yet invoiced",
        "medium",
        note=(
            "Check how long the accrual has been carried and whether the "
            "invoices will in fact be issued."
        ),
    ),
    FinancialHeuristic(
        "crediti scaduti",
        "receivables_at_risk",
        "Overdue trade receivables referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "fondo svalutazione crediti",
        "receivables_at_risk",
        "Bad-debt provision referenced in the document",
        "low",
        note="Verify whether the provision covers the overdue positions.",
    ),
    # ── Grants ───────────────────────────────────────────────────────────
    FinancialHeuristic(
        "contributo a fondo perduto",
        "public_funding",
        "Public grant referenced in the document",
        "medium",
        note=(
            "Verify the conditions attached and any clawback triggered by "
            "the transaction."
        ),
    ),
    FinancialHeuristic(
        "contributi pubblici",
        "public_funding",
        "Public grants referenced in the document",
        "medium",
    ),
    FinancialHeuristic(
        "finanziamento agevolato",
        "public_funding",
        "Subsidised financing referenced in the document",
        "medium",
    ),
]

_HEURISTIC_CONFIDENCE = 0.60


# ── Payload normalisation ────────────────────────────────────────────────────


def _normalize_amount(item: dict) -> float | None:
    """Return the euro amount the document states, or None.

    The agent never estimates a figure, so an unusable value becomes no
    value rather than a coerced one.
    """
    raw = item.get("amount_eur")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return None
    return amount if amount >= 0 else None


def _normalize_flag(raw: object) -> bool | None:
    """Return a tri-state flag: True, False, or None for "not stated"."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"true", "yes", "y", "si", "sì"}:
            return True
        if lowered in {"false", "no", "n"}:
            return False
    return None


# ── Agent ────────────────────────────────────────────────────────────────────


class FinancialAgent:
    """LLM-powered financial documentary-review agent with deterministic floors.

    Usage::

        agent = FinancialAgent()
        result = agent.run(deal_id, db)

        # Explicit document IDs (bypasses auto-detection):
        result = agent.run(deal_id, db, document_ids={10, 11})

        # Auto-detection unioned with routing output:
        result = agent.run(deal_id, db, routed_document_ids={12})

    Or use the module-level convenience wrapper :func:`run_financial_analysis`.
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
        """Extract financial findings from documents in *deal_id*.

        Parameters
        ----------
        deal_id:
            ID of the deal whose documents should be analysed.
        db:
            Active SQLAlchemy session.
        document_ids:
            Optional set of document IDs to analyse. When *None*, the agent
            auto-detects financial documents by keyword matching, unioned
            with *routed_document_ids*. Pass an empty set to produce a
            zero-finding result without querying the LLM.
        routed_document_ids:
            Document IDs the routing stage classified as financial
            statements. Only used when *document_ids* is None.

        Returns::

            {
                "deal_id": int,
                "documents_analyzed": int,
                "agent_findings_count": int,
                "heuristic_findings_count": int,
                "findings_by_severity": {"low": int, "medium": int, "high": int},
                "findings_by_finding_type": {"auditor_opinion": int, ...},
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
            "[%s] deal=%d ('%s') — starting financial documentary review",
            self.AGENT_NAME, deal_id, deal.title,
        )

        # ── 1. Idempotency: replace the previous AgentRun ─────────────── #
        # Previous AgentFinding rows are deleted in the persistence phase,
        # inside the same transaction as the new rows (see stage_tx).
        db.query(AgentRun).filter(
            AgentRun.deal_id == deal_id,
            AgentRun.agent_name == self.AGENT_NAME,
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

            # LLM+parse batches are pure; one bounded queue serves all documents
            # so a large ledger does not become a sequential tail of the stage.
            # ORM persistence happens below on this thread, in input order.
            # Plain values for the workers: after the commit below the ORM
            # instances are expired and must not be touched off-thread.
            to_analyse = []
            for doc in documents:
                text = (doc.raw_text or "").strip()
                if text:
                    to_analyse.append((doc, doc.id, doc.filename, text))
                else:
                    logger.warning(
                        "[%s] deal=%d doc=%d — no text, skipping",
                        self.AGENT_NAME, deal_id, doc.id,
                    )

            from app.core.config import settings
            from packages.agents.analysis_progress import publish_progress
            from packages.agents.document_coverage import collect_documents_payloads
            from packages.agents.stage_tx import release_connection_before_llm

            # No transaction may stay open across the LLM phase.
            progress_run_id = run.id
            release_connection_before_llm(db)

            filenames = {document_id: filename for _, document_id, filename, _ in to_analyse}
            batch_workers = max(1, min(2, settings.LLM_MAX_CONCURRENCY, settings.LLM_MAX_IN_FLIGHT))
            payload_lists = collect_documents_payloads(
                [(document_id, text) for _, document_id, _, text in to_analyse],
                lambda document_id, batch: self._financial_payloads_batch(
                    filenames[document_id], batch, document_id,
                ),
                max_workers=batch_workers,
                progress_context=self.AGENT_NAME,
                on_progress=lambda done, total, document_id: publish_progress(
                    deal_id, progress_run_id, done, total, document_id,
                ),
                isolate_failures=True,
            )
            from packages.agents.stage_failures import split_outcomes, record_unanalysed_documents
            analysed, failed = split_outcomes(to_analyse, payload_lists)

            # Idempotency: wipe the previous run's outputs in the same
            # transaction as the new rows.
            # A document whose request failed keeps the previous run's outputs:
            # a gap is recorded for it, but nothing it had is destroyed.
            kept_ids = [doc.id for (doc, _, _, _), _ in failed]
            db.query(AgentFinding).filter(
                AgentFinding.deal_id == deal_id,
                AgentFinding.agent_name == self.AGENT_NAME,
                or_(AgentFinding.document_id.is_(None), AgentFinding.document_id.notin_(kept_ids)),
            ).delete(synchronize_session=False)
            db.flush()

            for (doc, _, _, text), payloads in analysed:
                # Deterministic floor for high-signal Italian red flags.
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
            result["failed_documents"] = record_unanalysed_documents(
                db, deal_id, self.AGENT_NAME,
                [(doc.id, doc.filename, failure.error) for (doc, _, _, _), failure in failed],
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
                if d.id in routed or self._is_financial_document(d)
            ]
            logger.info(
                "[%s] deal=%d — selected %d financial doc(s) (auto-detection ∪ routing)",
                self.AGENT_NAME, deal_id, len(docs),
            )

        return docs

    def _is_financial_document(self, doc) -> bool:
        """Return True if *doc* looks like a financial document.

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
        return any(kw in haystack for kw in _FINANCIAL_DOC_KEYWORDS)

    # ── Finding extraction ──────────────────────────────────────────────

    def _financial_payloads(self, filename: str, text: str, document_id: int) -> list[dict]:
        from packages.agents.document_coverage import collect_document_payloads

        return collect_document_payloads(
            text, lambda batch: self._financial_payloads_batch(filename, batch, document_id)
        )

    def _financial_payloads_batch(
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
        from packages.prompts.deal_prompts import FINANCIAL_ANALYSIS_PROMPT

        prompt = FINANCIAL_ANALYSIS_PROMPT.format(
            filename=filename,
            text=text,
        )
        items = _complete_llm_items(
            self._llm, prompt, max_tokens=12288, context=f"{self.AGENT_NAME}, document {document_id}"
        )

        payloads: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            finding_type = item.get("finding_type", "other_financial")
            if finding_type not in _VALID_FINDING_TYPES:
                finding_type = "other_financial"

            severity_str = _normalize_severity(str(item.get("severity", "")).lower())

            counterparty = item.get("counterparty")
            counterparty = str(counterparty)[:200] if counterparty else None
            from packages.agents.evidence import grounded_amount
            amount, amount_source, amount_evidence = grounded_amount(item, text)

            payloads.append({
                "finding_type": finding_type,
                "title": str(item.get("title", ""))[:100],
                "description": str(item.get("description", ""))[:400],
                "severity": severity_str,
                "amount_eur": amount,
                "amount_source": amount_source,
                "amount_evidence": amount_evidence,
                "counterparty": counterparty,
                # Only meaningful on a covenant finding; the two booleans
                # are the whole legal deliverable of a financing review, so
                # they travel as fields rather than buried in prose.
                "change_of_control_clause": _normalize_flag(
                    item.get("change_of_control_clause")
                ),
                "financial_covenant": _normalize_flag(
                    item.get("financial_covenant")
                ),
                "confidence": item.get("confidence"),
                "source": "llm",
            })
        return payloads

    def _heuristic_payloads(
        self, text: str, llm_payloads: list[dict]
    ) -> list[dict]:
        """Deterministic floor findings the LLM must not silently drop.

        Keep the strongest matching floor per type. An existing weaker
        finding of that type must not suppress a stronger control trigger.
        """
        lowered = text.lower()
        severity_order = {"low": 0, "medium": 1, "high": 2}
        covered_types = {
            p["finding_type"]: max(severity_order.get(q["severity"], 0)
                for q in llm_payloads if q["finding_type"] == p["finding_type"])
            for p in llm_payloads
        }
        seen_types: set[str] = set()

        payloads: list[dict] = []
        for h in sorted(_FINANCIAL_HEURISTICS, key=lambda h: severity_order[h.severity], reverse=True):
            if covered_types.get(h.finding_type, -1) >= severity_order[h.severity] or h.finding_type in seen_types:
                continue
            if h.keyword not in lowered:
                continue

            description = (
                f'The document mentions "{h.keyword}". The matter was not '
                "extracted by the analysis and must be verified against the "
                "underlying documents."
            )
            if h.note:
                description = f"{description} {h.note}"

            payloads.append({
                "finding_type": h.finding_type,
                "title": h.title,
                "description": description[:400],
                "severity": h.severity,
                # A keyword evidences the fact, not the figure.
                "amount_eur": None,
                "counterparty": None,
                "change_of_control_clause": None,
                "financial_covenant": None,
                "confidence": _HEURISTIC_CONFIDENCE,
                "source": "heuristic",
            })
            seen_types.add(h.finding_type)
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
                    "source_spans": p.get("source_spans", []),
                    "source": p["source"],
                    "amount_eur": p.get("amount_eur"),
                    # Distinguishes "the document states no figure" from
                    # "nobody looked": pricing an item is the client's
                    # advisers' job, never the pipeline's.
                    "amount_source": p.get("amount_source", "not_stated"),
                    "amount_evidence": p.get("amount_evidence"),
                    "counterparty": p.get("counterparty"),
                    "change_of_control_clause": p.get("change_of_control_clause"),
                    "financial_covenant": p.get("financial_covenant"),
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


def run_financial_analysis(
    deal_id: int,
    db: Session,
    *,
    document_ids: set[int] | None = None,
    routed_document_ids: set[int] | None = None,
    provider: LLMProvider | None = None,
) -> dict:
    """Create a :class:`FinancialAgent` and run the financial documentary review."""
    return FinancialAgent(provider=provider).run(
        deal_id, db,
        document_ids=document_ids,
        routed_document_ids=routed_document_ids,
    )
