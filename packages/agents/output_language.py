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
import re

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
        "This includes every title, issue, risk and recommendation, even when "
        "the examples or standard remedy labels below use another language. "
        "Translate example wording; never copy an English recommendation into an Italian report. "
        "Keep only verbatim source quotes, proper names and conventional acronyms "
        "(DSCR, SPA, IRES) in their original language."
    )


def has_language_mismatch(text: str | None, lang: str) -> bool:
    """Reject clear IT/EN leakage without guessing the language of short labels.

    This is a conservative backstop to the semantic review, not a general
    language classifier. Shared words, quotations and filenames are excluded.
    Long text is checked sentence by sentence so an English recommendation is
    not masked by the Italian surrounding prose.
    """
    if not text or lang not in SUPPORTED_LANGUAGES:
        return False
    from packages.parsing.language import _EN_WORDS, _IT_WORDS

    words = {"it": _IT_WORDS - _EN_WORDS, "en": _EN_WORDS - _IT_WORDS}
    other = "en" if lang == "it" else "it"
    prose = re.sub(r'"[^"\n]+"|“[^”\n]+”|«[^»\n]+»', '', text)
    prose = re.sub(r'\b\S+\.(?:pdf|docx?|txt|xlsx?)\b', '', prose, flags=re.I)
    sentences = re.split(r'[.!?;\n]+', prose)
    for sentence in sentences:
        tokens = re.findall(r"[a-zà-öø-ÿ]+", sentence.casefold())
        expected = sum(w in words[lang] for w in tokens)
        unexpected = sum(w in words[other] for w in tokens)
        if unexpected >= 3 and unexpected >= 3 * max(1, expected):
            return True
    return False


def recommendation_examples(lang: str) -> str:
    """Examples in the requested language; source facts must never be copied."""
    if lang == "it":
        examples = (
            "Ottenere prima del perfezionamento il consenso della banca e la rinuncia alla violazione del covenant, nel rispetto dei termini contrattuali.",
            "Prevedere nel contratto di acquisizione una garanzia specifica sull'esposizione documentata, definendone durata e modalità con i consulenti competenti.",
            "Verificare la recuperabilità dei crediti e negoziare un eventuale aggiustamento del prezzo sulla base delle risultanze.",
            "Richiedere la documentazione mancante prima di formulare una conclusione sull'esistenza o sull'assenza del presidio.",
        )
    else:
        examples = (
            "Obtain the lender's consent and a waiver of the covenant breach before completion, subject to the contractual notice and cure provisions.",
            "Negotiate a specific indemnity for the documented exposure, agreeing its duration and terms with the relevant advisers.",
            "Verify recoverability of the receivables and negotiate any price adjustment on the basis of the findings.",
            "Request the missing documents before concluding that a safeguard exists or is absent.",
        )
    return "\n".join(f"- {example}" for example in examples)
