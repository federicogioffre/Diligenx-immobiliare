"""Validate durable stage checkpoints before resuming an unchanged corpus."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

STAGES = (
    ("intake", "intake"),
    ("document_routing", "document_router"),
    ("specialist_analysis", "contract_analysis"),
    ("corporate_analysis", "corporate_governance"),
    ("corporate_intro_extraction", "corporate_intro_extraction"),
    ("tax_analysis", "tax_analysis"),
    ("financial_analysis", "financial_analysis"),
    ("red_flag_aggregation", "red_flag_aggregation"),
    ("report_generation", "report_generation"),
)


class CheckpointError(ValueError):
    pass


def utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def corpus_fingerprint(db, deal_id: int) -> tuple[str, set[int]]:
    from app.models.deal import Deal
    from app.models.document import Document

    deal = db.query(Deal).filter_by(id=deal_id).one()
    digest = hashlib.sha256()
    def add(value):
        digest.update(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
        digest.update(b"\n")
    add([deal.id, deal.title, deal.description, deal.value, deal.report_language])
    # Preserve existing fingerprints for unconfigured legacy deals, but any
    # explicit perimeter change must invalidate the old analysis checkpoint.
    if deal.target_company_names:
        add({"target_company_names": deal.target_company_names})
    ids = set()
    for doc in db.query(Document).filter_by(deal_id=deal_id).order_by(Document.id).yield_per(10):
        if not doc.analysis_ready:
            raise CheckpointError("Tutti i documenti devono essere pronti prima di riprendere l'analisi.")
        ids.add(doc.id)
        add([doc.id, doc.filename, doc.file_path, doc.mime_type, doc.file_size,
             doc.page_count, doc.language, hashlib.sha256(doc.raw_text.encode("utf-8")).hexdigest()])
    if not ids:
        raise CheckpointError("Nessun documento disponibile per la ripresa.")
    return digest.hexdigest(), ids


@dataclass(frozen=True)
class ResumePlan:
    completed: tuple[str, ...]
    classifications: list[dict]
    fingerprint: str
    intake_started_at: datetime


def _checkpoint_runs(db, deal_id):
    from app.models.agent_run import AgentRun
    runs = db.query(AgentRun).filter_by(deal_id=deal_id).order_by(AgentRun.id).all()
    by_name = {run.agent_name: run for run in runs}
    intake = by_name.get("intake")
    if intake is None or intake.status != "completed" or not intake.started_at or not intake.completed_at:
        raise CheckpointError("Non esiste un checkpoint valido: avvia una nuova analisi.")
    return intake, by_name


def validate_resume(db, deal_id: int) -> ResumePlan:
    """Fail closed on edited documents, incomplete routing, or stale stage rows."""
    from app.models.agent_finding import AgentFinding

    intake, by_name = _checkpoint_runs(db, deal_id)
    fingerprint, document_ids = corpus_fingerprint(db, deal_id)
    if not intake.input_hash or intake.input_hash != fingerprint:
        raise CheckpointError("I documenti o i dati della pratica sono cambiati, oppure manca il checkpoint: avvia una nuova analisi.")
    completed = []
    previous_end = utc(intake.started_at)
    for key, name in STAGES:
        run = by_name.get(name)
        if run is None or run.status != "completed":
            break
        if not run.started_at or not run.completed_at or utc(run.started_at) < previous_end:
            break
        if utc(run.completed_at) < utc(run.started_at):
            raise CheckpointError("Checkpoint con timestamp non validi.")
        completed.append(key)
        previous_end = utc(run.completed_at)
    if len(completed) == len(STAGES):
        raise CheckpointError("L'analisi è già completata.")
    classifications = []
    if "document_routing" in completed:
        rows = db.query(AgentFinding).filter_by(deal_id=deal_id, agent_name="document_router").all()
        seen = set()
        for row in rows:
            payload = row.structured_payload_json
            if (row.document_id not in document_ids or row.document_id in seen
                    or not isinstance(payload, dict) or not isinstance(payload.get("document_type"), str)
                    or not payload["document_type"].strip()):
                raise CheckpointError("Classificazione salvata incompleta o non valida.")
            seen.add(row.document_id)
            classifications.append({"document_id": row.document_id,
                                    "document_type": payload["document_type"],
                                    "confidence": payload.get("confidence", 0)})
        if seen != document_ids:
            raise CheckpointError("La classificazione salvata non copre gli stessi documenti.")
    return ResumePlan(tuple(completed), classifications, fingerprint, utc(intake.started_at))


def adopt_legacy_checkpoint(db, deal_id: int, *, expected_intake_started_at: datetime,
                            expected_document_count: int) -> ResumePlan:
    """Maintenance-only adoption of a known interrupted pre-checkpoint run.

    Caller must own the deal row lock and prove its Redis job is absent. Never
    exposed as an HTTP option. The old admission must still lock the inventory.
    """
    from app.models.deal import Deal
    from app.models.document import Document

    deal = db.query(Deal).filter_by(id=deal_id).one()
    intake, _ = _checkpoint_runs(db, deal_id)
    if deal.status != "analyzing" or utc(intake.started_at) != utc(expected_intake_started_at):
        raise CheckpointError("Legacy admission does not match the verified interrupted run")
    if utc(deal.updated_at or deal.created_at) > utc(intake.started_at):
        raise CheckpointError("Legacy deal metadata changed after intake")
    fingerprint, ids = corpus_fingerprint(db, deal_id)
    if len(ids) != expected_document_count:
        raise CheckpointError("Legacy document inventory changed")
    for created, updated in db.query(Document.created_at, Document.updated_at).filter_by(deal_id=deal_id):
        if not created or not updated or max(utc(created), utc(updated)) > utc(intake.started_at):
            raise CheckpointError("Legacy documents changed after intake")
    old_hash = intake.input_hash
    if old_hash and old_hash != fingerprint:
        raise CheckpointError("Existing checkpoint must not be overwritten")
    intake.input_hash = fingerprint
    db.flush()
    try:
        plan = validate_resume(db, deal_id)
        if len(plan.completed) < 2:
            raise CheckpointError("Legacy routing is not a completed checkpoint")
        return plan
    except Exception:
        intake.input_hash = old_hash
        db.flush()
        raise
