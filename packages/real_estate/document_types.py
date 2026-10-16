"""Document types the routing stage assigns to a property dossier."""
from __future__ import annotations

DOCUMENT_TYPES: dict[str, str] = {
    "atto_provenienza": "deed by which the seller (or a previous owner) acquired the property: compravendita, donazione, divisione, permuta, assegnazione, decreto di trasferimento",
    "successione": "declaration of succession, certificate of inheritance, deed of acceptance of an inheritance, will",
    "ispezione_ipotecaria": "mortgage-registry search (ispezione / visura ipotecaria, elenco sintetico delle formalità, note di trascrizione o iscrizione), notarial twenty-year report (relazione / certificazione notarile)",
    "visura_catastale": "cadastral extract (visura catastale, anche storica)",
    "planimetria": "cadastral floor plan, elaborato planimetrico, estratto di mappa",
    "titolo_edilizio": "building permit or filing: licenza edilizia, concessione, permesso di costruire, DIA, SCIA, CILA, condono or sanatoria, with its drawings",
    "agibilita": "certificate of habitability (agibilità / abitabilità) or the related SCA filing",
    "cdu": "certificate of urban-planning use (certificato di destinazione urbanistica)",
    "ape": "energy performance certificate (attestato di prestazione energetica)",
    "conformita_impianti": "declaration of conformity or of compliance of the installations (DM 37/2008), installation logbooks",
    "regolamento_condominiale": "condominium by-laws (regolamento di condominio) and their tables",
    "verbale_assemblea": "minutes of a condominium meeting",
    "situazione_condominiale": "administrator's statement of the owner's payments and pending disputes, condominium budgets and accounts",
    "locazione": "lease or loan-for-use contract on the property",
    "preliminare": "purchase offer, preliminary contract (preliminare / compromesso)",
    "perizia": "valuation report: bank appraisal, court expert report (perizia CTU), notice of judicial sale",
    "documento_venditore": "personal documents of the seller: identity document, marriage extract, civil status, power of attorney",
    "other": "any document that does not fit the types above",
}

VALID_DOCUMENT_TYPES = frozenset(DOCUMENT_TYPES)

_TYPE_LINES = "\n".join(f"- {key}: {description}" for key, description in DOCUMENT_TYPES.items())

DOCUMENT_CLASSIFICATION_PROMPT = (
    "You are a document classification expert for the due diligence of an Italian residential property purchase.\n\n"
    "CLASSIFY the following document into exactly one type:\n"
    + _TYPE_LINES.replace("{", "{{").replace("}", "}}")
    + """

File name: {filename}
Document text (excerpt):
{text}

Return ONLY a JSON object (no markdown fences, no explanation):
{{"document_type": "<type>", "confidence": <0.0-1.0>, "rationale": "<one sentence>"}}
"""
)


def normalize_document_type(value: object) -> str:
    """Map a raw model answer to a known type; anything else is ``other``.

    The vocabulary is long and Italian, so a model answering "visura" or
    "atto" must not fail the routing stage: the specialists select their
    documents by keyword as well, and "other" loses nothing they need.
    """
    if not isinstance(value, str):
        return "other"
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in VALID_DOCUMENT_TYPES else "other"


def classify(provider, filename: str, text: str, *, context: str) -> dict:
    """Classify one document. Pure: safe on a worker thread."""
    from packages.agents.deal_analysis_agent import LLMResponseError, _complete_json

    prompt = DOCUMENT_CLASSIFICATION_PROMPT.format(filename=filename, text=text)
    result = _complete_json(provider, prompt, max_tokens=512, context=context, response_type="object")
    if not isinstance(result, dict) or "document_type" not in result:
        raise LLMResponseError(f"{context}: expected an object with document_type")
    result = dict(result)
    result["document_type"] = normalize_document_type(result.get("document_type"))
    return result
