"""Property-identity stage: what each document states about each property unit.

Reads the deeds, cadastral extracts, floor plans, successions, preliminary
contracts and valuations, and stores one ``PropertyProfile`` per unit per
document. The rows feed the report's identification table (consolidated by
``property_identity.consolidate_property_profiles``) and the deterministic
``consistency_check`` stage, which compares them across documents.

Grounding: a cadastral identifier the model returns is kept only if it
appears in the text the model read. An invented "sub. 5" would otherwise
become a discrepancy against the cadastral extract and a red flag.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import LLMProvider, _complete_llm_items, get_llm_provider
from packages.real_estate import stage_support

logger = logging.getLogger(__name__)

AGENT_NAME = "property_identity"

ROUTED_TYPES = frozenset({
    "atto_provenienza", "visura_catastale", "planimetria", "successione", "preliminare", "perizia",
})

DOC_KEYWORDS = (
    "visura catastale", "visura storica", "planimetria", "catasto fabbricati",
    "dati catastali", "foglio", "mappale", "particella", "subalterno",
)

#: Keyword fallback for the source kind when routing did not classify a document.
_KIND_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("visura_catastale", ("visura catastale", "visura storica", "visura per immobile")),
    ("planimetria", ("planimetria",)),
    ("atto_provenienza", ("atto di compravendita", "atto di donazione", "repertorio", "rogito")),
    ("successione", ("dichiarazione di successione",)),
    ("preliminare", ("contratto preliminare", "proposta di acquisto", "proposta d'acquisto")),
    ("perizia", ("perizia", "relazione di stima")),
)

_TEXT_MAX_CHARS = 12000
_MIN_CONFIDENCE = 0.5
_STRING_FIELDS: dict[str, int] = {
    "unit_label": 200, "comune": 200, "sezione": 40, "foglio": 40, "particella": 60,
    "subalterno": 40, "categoria": 40, "classe": 40, "consistenza": 100, "superficie": 100,
    "rendita": 100, "indirizzo": 500, "piano": 100, "titolo": 500, "data_titolo": 40,
}
_IDENTIFIERS = ("foglio", "particella", "subalterno")
_COLUMNS = frozenset(_STRING_FIELDS) | {"intestatari", "confidence"}


def _clean(value, limit: int) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = " ".join(str(value).split())
    return text[:limit] or None


def _appears(value: str, text: str) -> bool:
    """True when *value* appears in *text* as a token (digits not glued to others)."""
    pattern = re.escape(value).replace(r"\ ", r"\s*")
    return re.search(rf"(?<![0-9A-Za-z]){pattern}(?![0-9A-Za-z])", text, re.IGNORECASE) is not None


def _holders(raw) -> list[dict]:
    holders: list[dict] = []
    if not isinstance(raw, list):
        return holders
    for item in raw:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("name"), 200)
        if not name:
            continue
        holders.append({
            "name": name,
            "tax_code": _clean(item.get("tax_code"), 32),
            "share": _clean(item.get("share"), 40),
            "right": _clean(item.get("right"), 80),
        })
    return holders[:20]


def normalize_unit(item: dict, text: str) -> dict | None:
    """Validate one model record against the text it was extracted from."""
    if not isinstance(item, dict):
        return None
    confidence = item.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and confidence < _MIN_CONFIDENCE:
        return None
    unit = {attr: _clean(item.get(attr), limit) for attr, limit in _STRING_FIELDS.items()}
    for attr in _IDENTIFIERS:
        if unit[attr] and not _appears(unit[attr], text):
            logger.info("[%s] dropped ungrounded %s=%r", AGENT_NAME, attr, unit[attr])
            unit[attr] = None
    unit["intestatari"] = _holders(item.get("intestatari"))
    unit["confidence"] = float(confidence) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None
    meaningful = any(unit[attr] for attr in ("foglio", "particella", "indirizzo", "categoria")) or unit["intestatari"]
    return unit if meaningful else None


def source_kind(doc_id: int, filename: str, text: str, kinds: dict[int, str]) -> str | None:
    kind = kinds.get(doc_id)
    if kind and kind != "other":
        return kind
    needle = (filename or "").lower().replace("_", " ") + " " + text[:2000].lower()
    for candidate, keywords in _KIND_KEYWORDS:
        if any(kw in needle for kw in keywords):
            return candidate
    return kind


class PropertyIdentityAgent:
    AGENT_NAME = AGENT_NAME

    def __init__(self, provider: LLMProvider | None = None):
        self._llm = provider or get_llm_provider()

    def run(
        self,
        deal_id: int,
        db: Session,
        *,
        classifications: list[dict] | None = None,
        document_ids: set[int] | None = None,
    ) -> dict:
        from app.models.deal import Deal
        from app.models.property_profile import PropertyProfile
        from packages.agents.concurrency import run_llm_tasks
        from packages.agents.stage_failures import record_unanalysed_documents, split_outcomes
        from packages.agents.stage_tx import release_connection_before_llm

        if db.query(Deal).filter(Deal.id == deal_id).first() is None:
            raise ValueError(f"Deal {deal_id} not found")

        run = stage_support.open_run(db, deal_id, self.AGENT_NAME)
        try:
            documents = stage_support.select_documents(
                db, deal_id,
                document_ids=document_ids,
                routed_document_ids=stage_support.routed_ids(classifications, ROUTED_TYPES),
                keywords=DOC_KEYWORDS,
            )
            kinds = stage_support.kinds_by_document(classifications)
            work = [(doc.id, doc.filename, doc.raw_text or "") for doc in documents if (doc.raw_text or "").strip()]
            work_kinds = {doc_id: source_kind(doc_id, filename, text, kinds) for doc_id, filename, text in work}

            release_connection_before_llm(db)
            outcomes = run_llm_tasks(work, lambda item: self._units(*item), isolate_failures=True)
            analysed, failed = split_outcomes(work, outcomes)

            failed_ids = [doc_id for (doc_id, _, _), _ in failed]
            query = db.query(PropertyProfile).filter(PropertyProfile.deal_id == deal_id)
            if failed_ids:
                query = query.filter(
                    (PropertyProfile.source_document_id.is_(None))
                    | (PropertyProfile.source_document_id.notin_(failed_ids))
                )
            query.delete(synchronize_session="fetch")
            db.flush()

            rows = []
            for (doc_id, _, _), units in analysed:
                for unit in units:
                    row = PropertyProfile(
                        deal_id=deal_id,
                        source_document_id=doc_id,
                        source_kind=work_kinds.get(doc_id),
                        **{k: v for k, v in unit.items() if k in _COLUMNS},
                    )
                    db.add(row)
                    rows.append(row)
            db.flush()

            result = {
                "deal_id": deal_id,
                "documents_analysed": len(analysed),
                "property_profiles_count": len(rows),
                "failed_documents": record_unanalysed_documents(
                    db, deal_id, self.AGENT_NAME,
                    [(doc_id, filename, failure.error) for (doc_id, filename, _), failure in failed],
                ),
            }
            stage_support.complete_run(db, run, result)
            return result
        except Exception as exc:
            stage_support.fail_run(db, run, exc)
            raise

    def _units(self, document_id: int, filename: str, text: str) -> list[dict]:
        """LLM + validation for one document. Pure: safe on a worker thread."""
        from packages.agents.document_coverage import collect_document_payloads

        return collect_document_payloads(
            text, lambda batch: self._units_batch(document_id, filename, batch), max_chars=_TEXT_MAX_CHARS,
        )

    def _units_batch(self, document_id: int, filename: str, text: str) -> list[dict]:
        from packages.real_estate.prompts import PROPERTY_IDENTITY_PROMPT

        items = _complete_llm_items(
            self._llm,
            PROPERTY_IDENTITY_PROMPT.format(filename=filename, text=text),
            max_tokens=6144,
            context=f"{self.AGENT_NAME}, document {document_id}",
        )
        units = []
        for item in items:
            unit = normalize_unit(item, text)
            if unit is not None:
                units.append(unit)
        return units
