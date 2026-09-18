"""Multi-agent orchestrator for deal analysis.

Runs a structured pipeline of specialist agents, each tracked by an
``AgentRun`` record.  Stages execute sequentially and each stage is
**idempotent** — re-running the pipeline deletes previous outputs for
that stage before writing new ones.

Pipeline stages:

1. **Intake** — validates the deal, transitions status to ``analyzing``,
   inventories documents, and records ``MissingDocument`` entries when
   expected standard document categories are absent.
2. **Document routing** — classifies each processed document and records
   the classification as an ``AgentFinding``.
3. **Contract analysis** — extracts clauses from contracts/agreements
   and stores them as ``ClauseFinding`` rows via
   :class:`~packages.agents.contract_agent.ContractAgent`.
4. **Corporate governance analysis** — analyses governance documents
   (articles of association, bylaws, shareholder agreements, etc.) via
   :class:`~packages.agents.corporate_agent.CorporateAgent`.
4c. **Tax documentary review** — analyses tax documents (accertamenti,
   cartelle, rateizzazioni, crediti d'imposta, …) via
   :class:`~packages.agents.tax_agent.TaxAgent`.
4d. **Financial documentary review** — analyses financial statements and
   their annexes (auditor qualifications, going concern, statutory capital
   losses, covenants, related parties, …) via
   :class:`~packages.agents.financial_agent.FinancialAgent`.
5. **Red-flag aggregation** — reviews all findings across the deal and
   produces ``RedFlag`` rows plus ``OpenQuestion`` entries for items
   requiring human follow-up.
6. **Report generation** — delegates to ``generate_due_diligence_report``
   to produce the final Markdown report stored in the ``Report`` table.

Design principles:

* Every stage is wrapped in its own ``AgentRun``; a failing stage marks
  its run as *failed*; independent stages continue and dependent stages are blocked.
* All logging includes agent name and deal_id for easy filtering.
* The pipeline returns a summary dict with per-stage outcomes.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import (
    LLMProvider,
    get_llm_provider,
    _parse_classification,
    _VALID_SEVERITIES,
    _CONTRACT_TYPES,
)

logger = logging.getLogger(__name__)

# Agent names used for AgentRun records — one per stage.
AGENT_INTAKE = "intake"
AGENT_ROUTER = "document_router"
AGENT_SPECIALIST = "contract_analysis"   # == ContractAgent.AGENT_NAME
AGENT_CORPORATE = "corporate_governance"  # == CorporateAgent.AGENT_NAME
AGENT_CORPORATE_INTRO = "corporate_intro_extraction"  # == CorporateIntroAgent.AGENT_NAME
AGENT_TAX = "tax_analysis"  # == TaxAgent.AGENT_NAME
AGENT_FINANCIAL = "financial_analysis"  # == FinancialAgent.AGENT_NAME
AGENT_RED_FLAG = "red_flag_aggregation"
AGENT_REPORT = "report_generation"

# Maps the stage keys used in the pipeline summary dict to the canonical
# ``AgentRun.agent_name`` recorded for that stage. Used when a stage has to
# be rolled back and its failure re-recorded in a fresh transaction (the
# stage's own AgentRun disappears with the rollback).
_STAGE_AGENT_NAMES = {
    "intake": AGENT_INTAKE,
    "document_routing": AGENT_ROUTER,
    "specialist_analysis": AGENT_SPECIALIST,
    "corporate_analysis": AGENT_CORPORATE,
    "corporate_intro_extraction": AGENT_CORPORATE_INTRO,
    "tax_analysis": AGENT_TAX,
    "financial_analysis": AGENT_FINANCIAL,
    "red_flag_aggregation": AGENT_RED_FLAG,
    "report_generation": AGENT_REPORT,
}


# ── Helper: AgentRun lifecycle ────────────────────────────────────────────

def _create_run(
    db: Session,
    deal_id: int,
    agent_name: str,
    *,
    document_id: int | None = None,
    input_hash: str | None = None,
) -> "AgentRun":  # noqa: F821
    """Create an AgentRun in *running* state with ``started_at = now()``."""
    from app.models.agent_run import AgentRun, AgentRunStatus

    run = AgentRun(
        deal_id=deal_id,
        document_id=document_id,
        agent_name=agent_name,
        status=AgentRunStatus.running,
        started_at=datetime.now(timezone.utc),
        input_hash=input_hash,
    )
    db.add(run)
    db.flush()
    return run


def _complete_run(db: Session, run, *, error: str | None = None) -> None:
    """Mark an AgentRun as *completed* or *failed* and log the duration."""
    from app.models.agent_run import AgentRunStatus

    run.completed_at = datetime.now(timezone.utc)
    _started = run.started_at
    if _started is not None and _started.tzinfo is None:
        _started = _started.replace(tzinfo=timezone.utc)
    duration = (
        (run.completed_at - _started).total_seconds()
        if _started is not None
        else None
    )
    if error:
        run.status = AgentRunStatus.failed
        run.error_message = error[:2000]  # cap to avoid huge payloads
        logger.warning(
            "[%s] deal=%d — FAILED in %.2fs: %s",
            run.agent_name,
            run.deal_id,
            duration or 0.0,
            error[:200],
        )
    else:
        run.status = AgentRunStatus.completed
        logger.info(
            "[%s] deal=%d — completed in %.2fs",
            run.agent_name,
            run.deal_id,
            duration or 0.0,
        )
    db.flush()


# ── Helper: idempotency cleanup ──────────────────────────────────────────

def _clear_previous_runs(db: Session, deal_id: int, agent_name: str) -> None:
    """Delete AgentRun rows from a previous execution of the same stage."""
    from app.models.agent_run import AgentRun

    db.query(AgentRun).filter(
        AgentRun.deal_id == deal_id,
        AgentRun.agent_name == agent_name,
    ).delete(synchronize_session=False)
    db.flush()


# ── Helper: transactional stage isolation ────────────────────────────────

def _record_failed_run(db: Session, deal_id: int, stage_key: str, error: str) -> None:
    """Record a failed AgentRun for *stage_key* in a fresh committed transaction.

    Called after a stage has been rolled back — the AgentRun the stage created
    for itself is gone with the rollback, so the failure is re-recorded here so
    it stays visible on the ``/agent-runs`` and SSE surfaces.
    """
    agent_name = _STAGE_AGENT_NAMES.get(stage_key, stage_key)
    try:
        _clear_previous_runs(db, deal_id, agent_name)
        run = _create_run(db, deal_id, agent_name)
        _complete_run(db, run, error=error)
        db.commit()
    except Exception:
        logger.exception(
            "[%s] deal=%d — could not record failed run", agent_name, deal_id
        )
        db.rollback()


def _execute_stage(db: Session, deal_id: int, stage_key: str, fn) -> dict:
    """Run one pipeline stage with transactional isolation.

    On **success** the stage's work is committed immediately, so it is durable
    and cannot be undone by a later stage's failure. On **failure** (an
    exception, a poisoned session, or a stage that returned ``{"error": ...}``)
    the uncommitted work is rolled back — which protects earlier committed
    results and, crucially, restores rows a delete-then-regenerate stage may
    have deleted before failing — and the failure is recorded separately.
    """
    try:
        result = fn()
    except Exception as exc:  # stage crashed outright (e.g. poisoned session)
        logger.exception("[%s] deal=%d — stage crashed", stage_key, deal_id)
        db.rollback()
        _record_failed_run(db, deal_id, stage_key, str(exc))
        return {"error": str(exc)}

    if isinstance(result, dict) and "error" in result:
        # Stage handled its own exception and reported failure: discard its
        # (possibly partial) work so it can't wipe previously-good data.
        db.rollback()
        _record_failed_run(db, deal_id, stage_key, str(result.get("error")))
        return result

    try:
        db.commit()
    except Exception as exc:  # commit itself failed — treat as a stage failure
        logger.exception("[%s] deal=%d — stage commit failed", stage_key, deal_id)
        db.rollback()
        _record_failed_run(db, deal_id, stage_key, str(exc))
        return {"error": str(exc)}

    return result


# ── Stage 1: Intake ──────────────────────────────────────────────────────

def _stage_intake(deal_id: int, db: Session) -> dict:
    """Validate deal, inventory documents, detect missing document categories."""
    from app.models.deal import Deal, DealStatus
    from app.models.document import Document, DocumentStatus
    from app.models.missing_document import MissingDocument

    agent = AGENT_INTAKE
    logger.info("[%s] deal=%d — starting intake stage", agent, deal_id)

    # Idempotency: remove previous intake runs and missing-documents
    _clear_previous_runs(db, deal_id, agent)
    db.query(MissingDocument).filter(
        MissingDocument.deal_id == deal_id,
    ).delete(synchronize_session=False)
    db.flush()

    run = _create_run(db, deal_id, agent)

    try:
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        # Transition status
        deal.status = DealStatus.analyzing
        db.flush()

        # Inventory documents
        docs = (
            db.query(Document)
            .filter(Document.deal_id == deal_id)
            .all()
        )
        processed = [d for d in docs if d.status == DocumentStatus.processed]
        incomplete = [
            d for d in docs
            if d.status != DocumentStatus.processed or not (d.raw_text or "").strip()
        ]
        if incomplete:
            raise ValueError(
                f"Document ingestion is incomplete for {len(incomplete)} document(s): "
                + ", ".join(str(d.id) for d in incomplete[:20])
            )

        from packages.agents.analysis_checkpoint import corpus_fingerprint
        if docs:
            run.input_hash, _ = corpus_fingerprint(db, deal_id)

        logger.info(
            "[%s] deal=%d — %d total documents, %d processed",
            agent, deal_id, len(docs), len(processed),
        )

        # Detect which NM Standard Legal Checklist items the data room
        # covers, and record a MissingDocument for every item that no
        # document matches. Matching uses the same keyword logic the
        # report renderer relies on (filename + first 1000 chars).
        from packages.agents.dd_checklist import CHECKLIST, matched_keys

        present_keys: set[str] = set()
        for doc in processed:
            present_keys |= matched_keys(doc.filename, doc.raw_text)

        missing_docs: list[MissingDocument] = []
        for item in CHECKLIST:
            if item["key"] in present_keys:
                continue
            # expected_item is String(500): firm code + section label.
            expected = f"{item['key']} — {item['section_name_it']}"
            md = MissingDocument(
                deal_id=deal_id,
                document_category=item["key"],
                expected_item=expected[:480],
                reason=item["request_it"],
                priority=item["priority"],
            )
            db.add(md)
            missing_docs.append(md)

        db.flush()
        _complete_run(db, run)

        result = {
            "total_documents": len(docs),
            "processed_documents": len(processed),
            "missing_categories": len(missing_docs),
        }
        logger.info("[%s] deal=%d — intake complete: %s", agent, deal_id, result)
        return result

    except Exception as exc:
        logger.exception("[%s] deal=%d — intake failed", agent, deal_id)
        _complete_run(db, run, error=str(exc))
        return {"error": str(exc)}


# ── Stage 2: Document routing (classification) ───────────────────────────

def _stage_document_routing(
    deal_id: int, db: Session, llm: LLMProvider
) -> dict:
    """Classify every processed document and record AgentFinding rows."""
    from app.models.document import Document, DocumentStatus
    from app.models.agent_finding import AgentFinding
    from app.models.red_flag import Severity
    from packages.prompts.deal_prompts import DOCUMENT_CLASSIFICATION_PROMPT

    agent = AGENT_ROUTER
    logger.info("[%s] deal=%d — starting document routing", agent, deal_id)

    # Idempotency: replace the previous AgentRun. Previous classification
    # findings are deleted in the persistence phase, in the same transaction
    # as the new ones (see stage_tx).
    _clear_previous_runs(db, deal_id, agent)

    run = _create_run(db, deal_id, agent)

    try:
        documents = (
            db.query(Document)
            .filter(
                Document.deal_id == deal_id,
                Document.status == DocumentStatus.processed,
            )
            .all()
        )

        classifications: list[dict] = []

        # Inputs are read on this thread; the LLM+parse work per document is
        # pure, so it fans out on a bounded pool (results come back in input
        # order). Persistence stays on this thread — Sessions aren't
        # thread-safe.
        # Plain values for the workers: after the commit below the ORM
        # instances are expired and must not be touched off-thread.
        to_classify = []
        for doc in documents:
            if doc.raw_text:
                to_classify.append((doc, doc.id, doc.filename, doc.raw_text[:3000]))
            else:
                logger.warning(
                    "[%s] deal=%d doc=%d — no text, skipping", agent, deal_id, doc.id
                )

        def _classify(item) -> dict:
            _, doc_id, filename, text = item
            prompt = DOCUMENT_CLASSIFICATION_PROMPT.format(
                filename=filename,
                text=text,
            )
            raw = llm.complete(prompt, max_tokens=512)

            return _parse_classification(raw)

        from packages.agents.concurrency import run_llm_tasks
        from packages.agents.stage_tx import release_connection_before_llm

        # No transaction may stay open across the LLM phase.
        release_connection_before_llm(db)

        results = run_llm_tasks(to_classify, _classify)

        # Idempotency: wipe the previous run's classifications in the same
        # transaction as the new ones.
        db.query(AgentFinding).filter(
            AgentFinding.deal_id == deal_id,
            AgentFinding.agent_name == agent,
        ).delete(synchronize_session=False)
        db.flush()

        for (doc, _, _, _), classification in zip(to_classify, results):
            doc_type = classification.get("document_type", "other")
            confidence = classification.get("confidence", 0.0)

            finding = AgentFinding(
                deal_id=deal_id,
                document_id=doc.id,
                agent_name=agent,
                category="document_classification",
                title=f"Classified as '{doc_type}'",
                description=classification.get("rationale", ""),
                severity=Severity.low,  # classification is informational
                confidence=confidence,
                structured_payload_json=classification,
            )
            db.add(finding)

            classifications.append({
                "document_id": doc.id,
                "document_type": doc_type,
                "confidence": confidence,
            })

            logger.info(
                "[%s] deal=%d doc=%d — classified as '%s' (conf=%.2f)",
                agent, deal_id, doc.id, doc_type, confidence,
            )

        db.flush()
        _complete_run(db, run)

        result = {"documents_classified": len(classifications), "classifications": classifications}
        logger.info("[%s] deal=%d — routing complete: %d documents", agent, deal_id, len(classifications))
        return result

    except Exception as exc:
        logger.exception("[%s] deal=%d — routing failed", agent, deal_id)
        _complete_run(db, run, error=str(exc))
        return {"error": str(exc)}


# ── Stage 3: Specialist analysis (clause extraction via ContractAgent) ────────

def _stage_specialist_analysis(
    deal_id: int,
    db: Session,
    llm: LLMProvider,
    classifications: list[dict],
) -> dict:
    """Delegate clause extraction to :class:`ContractAgent`.

    Identifies contract-type documents from Stage-2 classifications and
    passes their IDs to :class:`~packages.agents.contract_agent.ContractAgent`,
    which manages its own ``AgentRun`` record (``agent_name = "contract_analysis"``),
    idempotency, ``ClauseFinding`` persistence, and ``AgentFinding`` summaries.
    """
    from packages.agents.contract_agent import ContractAgent

    logger.info("[%s] deal=%d — starting specialist analysis", AGENT_SPECIALIST, deal_id)

    # Collect document IDs classified as contract-type by the routing stage.
    contract_doc_ids: set[int] = {
        c["document_id"]
        for c in classifications
        if c.get("document_type") in _CONTRACT_TYPES
    }
    # The upload role is authoritative even if classification says "other".
    # These IDs still pass through ContractAgent's deal/status filter and full
    # ordinary document windows; shared context excerpts never replace them.
    from app.models.document import Document, DocumentStatus
    contract_doc_ids.update(
        doc_id for (doc_id,) in db.query(Document.id).filter(
            Document.deal_id == deal_id,
            Document.document_role == "loi",
            Document.status == DocumentStatus.processed,
        )
    )

    logger.info(
        "[%s] deal=%d — %d contract document(s) identified from routing",
        AGENT_SPECIALIST, deal_id, len(contract_doc_ids),
    )

    try:
        # ContractAgent handles AgentRun tracking, idempotency, and DB writes.
        return ContractAgent(provider=llm).run(
            deal_id, db, contract_document_ids=contract_doc_ids,
        )
    except Exception as exc:
        logger.exception(
            "[%s] deal=%d — ContractAgent failed", AGENT_SPECIALIST, deal_id
        )
        return {"error": str(exc)}


# ── Stage 4: Corporate governance analysis ────────────────────────────────

def _stage_corporate_analysis(
    deal_id: int, db: Session, llm: LLMProvider
) -> dict:
    """Delegate corporate governance analysis to :class:`CorporateAgent`.

    The agent manages its own ``AgentRun`` record
    (``agent_name = "corporate_governance"``), idempotency (clearing previous
    ``AgentFinding`` rows), and ``AgentFinding`` persistence.
    """
    from packages.agents.corporate_agent import CorporateAgent

    logger.info("[%s] deal=%d — starting corporate governance analysis", AGENT_CORPORATE, deal_id)

    try:
        return CorporateAgent(provider=llm).run(deal_id, db)
    except Exception as exc:
        logger.exception(
            "[%s] deal=%d — CorporateAgent failed", AGENT_CORPORATE, deal_id
        )
        return {"error": str(exc)}


# ── Stage 4b: Corporate introductory information extraction ──────────────

def _stage_corporate_intro_extraction(
    deal_id: int, db: Session, llm: LLMProvider
) -> dict:
    """Delegate Corporate Introductory Information extraction to
    :class:`CorporateIntroAgent`.

    Populates ``CompanyProfile`` rows for the target companies described in
    the deal's corporate documents (visure, atti, statuti). Self-contained
    AgentRun + idempotency.
    """
    from packages.agents.corporate_intro_agent import CorporateIntroAgent

    logger.info(
        "[%s] deal=%d — starting corporate intro extraction",
        AGENT_CORPORATE_INTRO, deal_id,
    )

    try:
        return CorporateIntroAgent(provider=llm).run(deal_id, db)
    except Exception as exc:
        logger.exception(
            "[%s] deal=%d — CorporateIntroAgent failed",
            AGENT_CORPORATE_INTRO, deal_id,
        )
        return {"error": str(exc)}


# ── Stage 4c: Tax documentary review ──────────────────────────────────────

def _stage_tax_analysis(
    deal_id: int,
    db: Session,
    llm: LLMProvider,
    classifications: list[dict],
) -> dict:
    """Delegate the tax documentary review to :class:`TaxAgent`.

    Documents the routing stage classified as ``tax`` are passed as
    ``routed_document_ids``; the agent unions them with its own keyword
    auto-detection. Self-contained AgentRun + idempotency
    (``agent_name = "tax_analysis"``).
    """
    from packages.agents.tax_agent import TaxAgent

    logger.info("[%s] deal=%d — starting tax documentary review", AGENT_TAX, deal_id)

    routed_tax_ids: set[int] = {
        c["document_id"]
        for c in classifications
        if c.get("document_type") == "tax"
    }

    try:
        return TaxAgent(provider=llm).run(
            deal_id, db, routed_document_ids=routed_tax_ids,
        )
    except Exception as exc:
        logger.exception(
            "[%s] deal=%d — TaxAgent failed", AGENT_TAX, deal_id
        )
        return {"error": str(exc)}


# ── Stage 4d: Financial documentary review ────────────────────────────────

def _stage_financial_analysis(
    deal_id: int,
    db: Session,
    llm: LLMProvider,
    classifications: list[dict],
) -> dict:
    """Delegate the financial documentary review to :class:`FinancialAgent`.

    Documents the routing stage classified as ``financial_statement`` are
    passed as ``routed_document_ids``; the agent unions them with its own
    keyword auto-detection. Self-contained AgentRun + idempotency
    (``agent_name = "financial_analysis"``).
    """
    from packages.agents.financial_agent import FinancialAgent

    logger.info(
        "[%s] deal=%d — starting financial documentary review",
        AGENT_FINANCIAL, deal_id,
    )

    routed_financial_ids: set[int] = {
        c["document_id"]
        for c in classifications
        if c.get("document_type") == "financial_statement"
    }

    try:
        return FinancialAgent(provider=llm).run(
            deal_id, db, routed_document_ids=routed_financial_ids,
        )
    except Exception as exc:
        logger.exception(
            "[%s] deal=%d — FinancialAgent failed", AGENT_FINANCIAL, deal_id
        )
        return {"error": str(exc)}


# ── Stage 5: Red-flag aggregation ─────────────────────────────────────────

def _stage_red_flag_aggregation(
    deal_id: int, db: Session, llm: LLMProvider
) -> dict:
    """Delegate red-flag aggregation to :class:`RedFlagAggregationAgent`.

    The agent manages its own ``AgentRun`` record
    (``agent_name = "red_flag_aggregation"``), idempotency (clearing previous
    ``RedFlag`` and ``OpenQuestion`` rows), deduplication, and ``RedFlag`` /
    ``OpenQuestion`` persistence.
    """
    from packages.agents.red_flag_aggregator import RedFlagAggregationAgent

    logger.info("[%s] deal=%d — starting red-flag aggregation", AGENT_RED_FLAG, deal_id)

    try:
        return RedFlagAggregationAgent(provider=llm).run(deal_id, db)
    except Exception as exc:
        logger.exception(
            "[%s] deal=%d — RedFlagAggregationAgent failed", AGENT_RED_FLAG, deal_id
        )
        return {"error": str(exc)}


# ── Stage 6: Report generation ────────────────────────────────────────────

def _stage_report_generation(
    deal_id: int, db: Session, llm: LLMProvider
) -> dict:
    """Generate the due-diligence report (delegates to report_agent)."""
    agent = AGENT_REPORT
    logger.info("[%s] deal=%d — starting report generation", agent, deal_id)

    _clear_previous_runs(db, deal_id, agent)

    run = _create_run(db, deal_id, agent)

    try:
        from packages.agents.report_agent import generate_due_diligence_report

        report_result = generate_due_diligence_report(deal_id, db, provider=llm)

        _complete_run(db, run)

        result = {
            "report_id": report_result["report_id"],
            "markdown_length": len(report_result.get("markdown", "")),
        }
        logger.info("[%s] deal=%d — report generated (id=%d)", agent, deal_id, result["report_id"])
        return result

    except Exception as exc:
        logger.exception("[%s] deal=%d — report generation failed", agent, deal_id)
        _complete_run(db, run, error=str(exc))
        return {"error": str(exc)}


# ── Public entry point ────────────────────────────────────────────────────

def run_deal_analysis_pipeline(
    deal_id: int,
    db: Session,
    *,
    provider: LLMProvider | None = None,
    resume: bool = False,
) -> dict:
    """Run the full multi-agent analysis pipeline for a deal.

    Returns a summary dict::

        {
            "deal_id": int,
            "stages": {
                "intake": {...},
                "document_routing": {...},
                "specialist_analysis": {...},
                "corporate_analysis": {...},
                "corporate_intro_extraction": {...},
                "tax_analysis": {...},
                "financial_analysis": {...},
                "red_flag_aggregation": {...},
                "report_generation": {...},
            },
            "completed": bool,   # True if all stages succeeded
        }

    Individual stage failures are recorded; independent stages continue,
    while dependent stages are blocked to preserve their previous outputs.  The ``"error"`` key is present in a stage result only
    when that stage failed.

    Raises ``ValueError`` if *deal_id* does not exist.
    """
    from app.models.deal import Deal, DealStatus

    # Validate early — avoids FK constraint issues in AgentRun inserts.
    if db.query(Deal).filter(Deal.id == deal_id).first() is None:
        raise ValueError(f"Deal {deal_id} not found")

    from packages.agents.analysis_checkpoint import validate_resume
    checkpoint = validate_resume(db, deal_id) if resume else None
    from packages.agents.deal_context import with_deal_context
    llm = with_deal_context(provider or get_llm_provider(), db, deal_id)

    logger.info("=== Pipeline START for deal %d ===", deal_id)

    stages: dict[str, dict] = {}

    def execute(key, fn, dependencies):
        if checkpoint and key in checkpoint.completed:
            stages[key] = {"resumed_from_checkpoint": True}
            if key == "document_routing":
                stages[key]["classifications"] = checkpoint.classifications
            logger.info("[%s] deal=%d — reusing completed checkpoint", key, deal_id)
            return
        failed = [name for name in dependencies if "error" in stages[name]]
        if failed:
            error = "Analysis incomplete; prerequisite stages failed: " + ", ".join(failed)
            _record_failed_run(db, deal_id, key, error)
            stages[key] = {"error": error}
        else:
            stages[key] = _execute_stage(db, deal_id, key, fn)

    execute("intake", lambda: _stage_intake(deal_id, db), ())
    execute("document_routing", lambda: _stage_document_routing(deal_id, db, llm), ("intake",))
    classifications = stages["document_routing"].get("classifications", [])

    execute("specialist_analysis",
            lambda: _stage_specialist_analysis(deal_id, db, llm, classifications),
            ("document_routing",))
    # These specialists discover their inputs independently of routing.
    execute("corporate_analysis", lambda: _stage_corporate_analysis(deal_id, db, llm), ("intake",))
    execute("corporate_intro_extraction",
            lambda: _stage_corporate_intro_extraction(deal_id, db, llm), ("intake",))
    execute("tax_analysis", lambda: _stage_tax_analysis(deal_id, db, llm, classifications),
            ("document_routing",))
    execute("financial_analysis",
            lambda: _stage_financial_analysis(deal_id, db, llm, classifications),
            ("document_routing",))

    # Aggregation and publication require a complete analysis. Leave the
    # previous findings/report intact when any prerequisite fails.
    execute("red_flag_aggregation", lambda: _stage_red_flag_aggregation(deal_id, db, llm),
            tuple(stages))
    execute("report_generation", lambda: _stage_report_generation(deal_id, db, llm),
            tuple(stages))

    # ── Finalise deal status ───────────────────────────────────────────
    all_ok = all("error" not in s for s in stages.values())

    try:
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal:
            deal.status = DealStatus.reviewed if all_ok else DealStatus.draft
            db.commit()
    except Exception:
        logger.exception(
            "=== Pipeline: failed to finalise status for deal %d ===", deal_id
        )
        db.rollback()

    logger.info(
        "=== Pipeline %s for deal %d ===",
        "COMPLETE" if all_ok else "FINISHED WITH ERRORS",
        deal_id,
    )

    return {
        "deal_id": deal_id,
        "stages": stages,
        "completed": all_ok,
    }
