"""Record documents a fan-out stage could not analyse, without failing it.

A model request that fails for one document (a runaway generation truncated at
the output limit, a refusal, malformed JSON after the retry) is a gap in the
analysis, not a reason to discard the other documents' results. The gap must
be visible to the professional, so each unanalysed document becomes a
medium-priority ``OpenQuestion`` in the report language, and the stage result
lists it under ``failed_documents``.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TypeVar

from sqlalchemy.orm import Session

from packages.agents.concurrency import TaskFailure

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

def _labels() -> dict[str, tuple[str, str]]:
    from packages.real_estate.pipeline import STAGE_LABELS
    return {name: (it.lower(), en.lower()) for name, (it, en) in STAGE_LABELS.items()}


def split_outcomes(items: Sequence[T], outcomes: Sequence[R | TaskFailure]):
    """Pair inputs with outcomes: ``(analysed, failed)`` in input order."""
    analysed: list[tuple[T, R]] = []
    failed: list[tuple[T, TaskFailure]] = []
    for item, outcome in zip(items, outcomes):
        (failed if isinstance(outcome, TaskFailure) else analysed).append((item, outcome))
    return analysed, failed


def unanalysed_question(filename: str, agent_name: str, error: str, language: str) -> str:
    label_it, label_en = _labels().get(agent_name, (agent_name, agent_name))
    name = " ".join(str(filename).split())[:300] or "\u2014"
    reason = " ".join(str(error).split())[:400]
    if language == "it":
        return (
            f"Documento non analizzato \u2014 '{name}' ({label_it}): la richiesta al modello "
            f"non \u00e8 andata a buon fine ({reason}). I rilievi di questo documento mancano "
            "dall'analisi: verificarlo manualmente o rieseguire l'analisi."
        )
    return (
        f"Document not analysed \u2014 '{name}' ({label_en}): the model request failed "
        f"({reason}). This document's findings are missing from the analysis: review it "
        "manually or rerun the analysis."
    )


def record_unanalysed_documents(
    db: Session, deal_id: int, agent_name: str,
    failures: Sequence[tuple[int, str, str]],
) -> list[dict]:
    """Replace the stage's previous unanalysed-document questions with these.

    Called on every run of the stage, inside its persistence transaction, so
    a document that analyses correctly on the next run clears its question.
    Returns the ``failed_documents`` entries for the stage result.
    """
    from app.models.deal import Deal
    from app.models.open_question import OpenQuestion, Priority
    from packages.agents.output_language import resolve_output_language

    db.query(OpenQuestion).filter(
        OpenQuestion.deal_id == deal_id,
        OpenQuestion.agent_name == agent_name,
    ).delete(synchronize_session=False)
    if not failures:
        return []
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    language = resolve_output_language(deal, db) if deal is not None else "en"
    recorded = []
    for document_id, filename, error in failures:
        logger.warning("[%s] deal=%d doc=%s — not analysed: %s", agent_name, deal_id, document_id, error)
        db.add(OpenQuestion(
            deal_id=deal_id, document_id=document_id, agent_name=agent_name,
            question=unanalysed_question(filename, agent_name, error, language),
            priority=Priority.medium,
        ))
        recorded.append({"document_id": document_id, "filename": filename, "error": error})
    db.flush()
    return recorded
