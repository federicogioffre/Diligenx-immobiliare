"""Multi-agent orchestrator for the real-estate purchase analysis.

Runs the stages of :mod:`packages.real_estate.pipeline` in order, each
tracked by an ``AgentRun`` record. Every stage is **idempotent** — re-running
the pipeline replaces that stage's previous outputs.

Pipeline stages:

1. **Intake** — validates the deal, sets status ``analyzing``, inventories
   the documents and records a ``MissingDocument`` for every item of the
   property checklist (:mod:`packages.real_estate.checklist`) no document
   covers.
2. **Document routing** — classifies each document into the property
   vocabulary (:mod:`packages.real_estate.document_types`).
3. **Property identification** — one ``PropertyProfile`` per unit per
   document (:mod:`packages.real_estate.property_identity_agent`).
4. **Specialist reviews** — title chain, encumbrances, building and
   cadastre, condominium and occupancy
   (:mod:`packages.real_estate.specialists`) → ``AgentFinding`` rows.
5. **Consistency check** — deterministic comparison of the property
   profiles across documents (:mod:`packages.real_estate.consistency`).
6. **Red-flag aggregation** — ``RedFlag`` rows plus ``OpenQuestion`` entries,
   through the source-fidelity review.
7. **Report generation** — the Markdown report stored in ``Report``.

Design principles:

* Every stage is wrapped in its own ``AgentRun``; a failing stage marks
  its run as *failed*; independent stages continue and dependent stages are blocked.
* All logging includes agent name and deal_id for easy filtering.
* The pipeline returns a summary dict with per-stage outcomes.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import LLMProvider, get_llm_provider
from packages.real_estate.pipeline import STAGES

logger = logging.getLogger(__name__)

# Agent names used for AgentRun records.
AGENT_INTAKE = "intake"
AGENT_ROUTER = "document_router"
AGENT_PROPERTY_IDENTITY = "property_identity"
AGENT_CONSISTENCY = "consistency_check"
AGENT_RED_FLAG = "red_flag_aggregation"
AGENT_REPORT = "report_generation"

# Maps the stage keys used in the pipeline summary dict to the canonical
# ``AgentRun.agent_name`` recorded for that stage. Used when a stage has to
# be rolled back and its failure re-recorded in a fresh transaction (the
# stage's own AgentRun disappears with the rollback).
_STAGE_AGENT_NAMES = dict(STAGES)


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

def _record_failed_run(
    db: Session, deal_id: int, stage_key: str, error: str, *, started_at: datetime | None = None,
) -> None:
    """Record a failed AgentRun for *stage_key* in a fresh committed transaction.

    Called after a stage has been rolled back — the AgentRun the stage created
    for itself is gone with the rollback, so the failure is re-recorded here so
    it stays visible on the ``/agent-runs`` and SSE surfaces.
    """
    agent_name = _STAGE_AGENT_NAMES.get(stage_key, stage_key)
    try:
        _clear_previous_runs(db, deal_id, agent_name)
        run = _create_run(db, deal_id, agent_name)
        if started_at is not None:
            run.started_at = started_at
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
    started_at = datetime.now(timezone.utc)
    try:
        result = fn()
    except Exception as exc:  # stage crashed outright (e.g. poisoned session)
        logger.exception("[%s] deal=%d — stage crashed", stage_key, deal_id)
        db.rollback()
        _record_failed_run(db, deal_id, stage_key, str(exc), started_at=started_at)
        return {"error": str(exc)}

    if isinstance(result, dict) and "error" in result:
        # Stage handled its own exception and reported failure: discard its
        # (possibly partial) work so it can't wipe previously-good data.
        db.rollback()
        _record_failed_run(db, deal_id, stage_key, str(result.get("error")), started_at=started_at)
        return result

    try:
        db.commit()
    except Exception as exc:  # commit itself failed — treat as a stage failure
        logger.exception("[%s] deal=%d — stage commit failed", stage_key, deal_id)
        db.rollback()
        _record_failed_run(db, deal_id, stage_key, str(exc), started_at=started_at)
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

        # Detect which items of the property checklist the documents cover,
        # and record a MissingDocument for every item that no document
        # matches (filename + first 1000 chars).
        from packages.real_estate.checklist import CHECKLIST, matched_keys

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
    from packages.real_estate.document_types import classify

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
            return classify(llm, filename, text, context=f"Document classification, document {doc_id}")

        from packages.agents.concurrency import run_llm_tasks
        from packages.agents.stage_tx import release_connection_before_llm

        # No transaction may stay open across the LLM phase.
        release_connection_before_llm(db)

        outcomes = run_llm_tasks(to_classify, _classify, isolate_failures=True)
        from packages.agents.stage_failures import split_outcomes, record_unanalysed_documents
        classified, failed = split_outcomes(to_classify, outcomes)

        # Idempotency: wipe the previous run's classifications in the same
        # transaction as the new ones.
        # A document whose request failed keeps its previous classification.
        kept_ids = [doc.id for (doc, _, _, _), _ in failed]
        db.query(AgentFinding).filter(
            AgentFinding.deal_id == deal_id,
            AgentFinding.agent_name == agent,
            or_(AgentFinding.document_id.is_(None), AgentFinding.document_id.notin_(kept_ids)),
        ).delete(synchronize_session=False)
        db.flush()

        for (doc, _, _, _), classification in classified:
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

        failed_documents = record_unanalysed_documents(
            db, deal_id, agent,
            [(doc.id, doc.filename, failure.error) for (doc, _, _, _), failure in failed],
        )
        db.flush()
        _complete_run(db, run)

        result = {"documents_classified": len(classifications), "classifications": classifications,
                  "failed_documents": failed_documents}
        logger.info("[%s] deal=%d — routing complete: %d documents", agent, deal_id, len(classifications))
        return result

    except Exception as exc:
        logger.exception("[%s] deal=%d — routing failed", agent, deal_id)
        _complete_run(db, run, error=str(exc))
        return {"error": str(exc)}


# ── Stage 3: Property identification ─────────────────────────────────────

def _stage_property_identity(
    deal_id: int, db: Session, llm: LLMProvider, classifications: list[dict],
) -> dict:
    """One ``PropertyProfile`` per unit per document (self-contained AgentRun)."""
    from packages.real_estate.property_identity_agent import PropertyIdentityAgent

    try:
        return PropertyIdentityAgent(provider=llm).run(deal_id, db, classifications=classifications)
    except Exception as exc:
        logger.exception("[%s] deal=%d — PropertyIdentityAgent failed", AGENT_PROPERTY_IDENTITY, deal_id)
        return {"error": str(exc)}


# ── Stage 4: Specialist reviews ───────────────────────────────────────────

def _stage_specialist(
    agent_cls, deal_id: int, db: Session, llm: LLMProvider, classifications: list[dict],
) -> dict:
    """Run one documentary reviewer (self-contained AgentRun + idempotency)."""
    try:
        return agent_cls(provider=llm).run(deal_id, db, classifications=classifications)
    except Exception as exc:
        logger.exception("[%s] deal=%d — review failed", agent_cls.AGENT_NAME, deal_id)
        return {"error": str(exc)}


# ── Stage 5: Consistency check ────────────────────────────────────────────

def _stage_consistency_check(deal_id: int, db: Session) -> dict:
    """Deterministic cross-document comparison of the property profiles."""
    from packages.real_estate.consistency import ConsistencyCheckAgent

    try:
        return ConsistencyCheckAgent().run(deal_id, db)
    except Exception as exc:
        logger.exception("[%s] deal=%d — consistency check failed", AGENT_CONSISTENCY, deal_id)
        return {"error": str(exc)}


# ── Stage 6: Red-flag aggregation ─────────────────────────────────────────

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


# ── Stage 7: Report generation ────────────────────────────────────────────

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
            "stages": {"<stage key>": {...}, ...},  # see real_estate.pipeline
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
    # An explicitly injected provider serves every stage (tests, tooling);
    # otherwise the judgment stages get their own, possibly stronger, model.
    from packages.agents.deal_analysis_agent import get_judgment_provider
    judgment = llm if provider is not None else with_deal_context(get_judgment_provider(), db, deal_id)

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

    execute("property_identity",
            lambda: _stage_property_identity(deal_id, db, llm, classifications),
            ("document_routing",))
    from packages.real_estate.specialists import SPECIALISTS
    for agent_cls in SPECIALISTS:
        execute(agent_cls.AGENT_NAME,
                lambda agent_cls=agent_cls: _stage_specialist(agent_cls, deal_id, db, llm, classifications),
                ("document_routing",))
    execute("consistency_check", lambda: _stage_consistency_check(deal_id, db), ("property_identity",))

    # Aggregation and publication require a complete analysis. Leave the
    # previous findings/report intact when any prerequisite fails.
    execute("red_flag_aggregation", lambda: _stage_red_flag_aggregation(deal_id, db, judgment),
            tuple(stages))
    execute("report_generation", lambda: _stage_report_generation(deal_id, db, judgment),
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
