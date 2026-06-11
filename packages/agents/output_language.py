"""Output-language resolution for LLM prose and report boilerplate.

A deal's output language is:

1. ``deal.report_language`` when explicitly set ("it" | "en"), else
2. the majority language across the deal's *processed* documents
   (``Document.language``, populated by the ingestion pipeline), else
3. "en".

The result drives both the language instruction injected into LLM prompts
(executive summary, red-flag aggregation) and the localized boilerplate of
the deterministic report template.
"""
from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

SUPPORTED_LANGUAGES = ("it", "en")

#: Human-readable names used in LLM prompt instructions.
LANGUAGE_NAMES = {"it": "Italian", "en": "English"}


def resolve_output_language(deal, db: Session) -> str:
    """Return "it" or "en" for *deal* according to the resolution order."""
    if deal.report_language in SUPPORTED_LANGUAGES:
        return deal.report_language

    from app.models.document import Document, DocumentStatus

    langs = [
        lang
        for (lang,) in db.query(Document.language)
        .filter(
            Document.deal_id == deal.id,
            Document.status == DocumentStatus.processed,
            Document.language.isnot(None),
        )
        .all()
        if lang in SUPPORTED_LANGUAGES
    ]
    if not langs:
        return "en"
    return Counter(langs).most_common(1)[0][0]


def language_instruction(lang: str) -> str:
    """One-line prompt instruction for the LLM output language."""
    name = LANGUAGE_NAMES.get(lang, "English")
    return (
        f"OUTPUT LANGUAGE: write all free-text output in {name}. "
        "Keep verbatim quotes from documents in their original language."
    )
