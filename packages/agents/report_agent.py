"""Due-diligence report for the purchase of a residential property.

Renders the report with the section structure of a professional Italian
property due diligence:

    1. Introduction (purpose / object / limitations — deterministic boilerplate,
       including the twenty-year chain coverage computed from the titles on file)
    2. Property Identification — one table per unit, consolidated from the
       ``PropertyProfile`` rows (deed → cadastral extract → floor plan → …)
    3. Executive Summary (grounded prose, or a bounded factual overview for large reports)
    4. Key Findings — one table per property area, each row carrying the
       Issue | Risk | Recommendation | Severity quadruple
    5. Observations / Information Requests (from the aggregator's AgentFindings
       and the property checklist)
    6. Appendix I: Documents Reviewed

Everything except the Executive Summary is rendered deterministically from
database rows — structure and data sections cannot hallucinate. Only the
summary prose goes through the LLM.

The report is stored in the ``Report`` table with
``report_type = due_diligence``.  Calling the function again for the same deal
replaces the previous due-diligence report (idempotent).
"""
import logging
from datetime import date

from sqlalchemy.orm import Session, joinedload

from packages.agents.deal_analysis_agent import LLMProvider, get_judgment_provider

logger = logging.getLogger(__name__)


# ── Localized template strings ──────────────────────────────────────────────
# "Executive Summary" and "Key Findings" stay in English in Italian reports,
# as in professional practice; everything else is localized.

from packages.real_estate.areas import AREA_ORDER as _AREA_ORDER, AREA_TITLES as _AREA_TITLES

_AREA_ORDER_KEYS = list(_AREA_ORDER)

_REPORT_TITLE = {
    "en": "Real Estate Due Diligence Report",
    "it": "Relazione di Due Diligence Immobiliare",
}

_L10N: dict[str, dict[str, str]] = {
    "en": {
        "confidential": "STRICTLY PRIVATE AND CONFIDENTIAL",
        "intro_heading": "## Introduction",
        "corp_info_heading": "## Property Identification",
        "observations_heading": "## Observations",
        "info_requests_heading": "## Information Requests",
        "appendix_heading": "## Appendix I: Documents Reviewed",
        "none_identified": "_None identified based on available documents._",
        "no_documents": "_No processed documents._",
        "issue_label": "Issue",
        "risk_label": "Risk",
        "recommendation_label": "Recommendation",
        "findings_header": "| # | Issue | Risk | Recommendation | Severity |",
        "findings_sep": "|---|-------|------|----------------|----------|",
        "doc_table_header": "| Document | Language | Pages |",
        "doc_table_sep": "|----------|----------|-------|",
        "field": "Field",
        "value": "Value",
    },
    "it": {
        "confidential": "STRETTAMENTE CONFIDENZIALE",
        "intro_heading": "## Introduzione",
        "corp_info_heading": "## Identificazione dell'Immobile",
        "observations_heading": "## Osservazioni",
        "info_requests_heading": "## Richieste di Informazioni",
        "appendix_heading": "## Allegato I: Lista dei Documenti Esaminati",
        "none_identified": "_Nessun rilievo sulla base dei documenti disponibili._",
        "no_documents": "_Nessun documento processato._",
        "issue_label": "Rilievo",
        "risk_label": "Rischio",
        "recommendation_label": "Raccomandazione",
        "findings_header": "| # | Argomento | Rischio | Raccomandazione | Gravità |",
        "findings_sep": "|---|-----------|---------|-----------------|---------|",
        "doc_table_header": "| Documento | Lingua | Pagine |",
        "doc_table_sep": "|-----------|--------|--------|",
        "field": "Campo",
        "value": "Valore",
    },
}

_INTRO_TEMPLATES: dict[str, str] = {
    "en": """{intro_heading}

### Purpose of this Report
This Report summarises the results of the legal due diligence conducted on the property described in **{deal_title}**, on behalf of the prospective buyer. It focuses on the issues arising from the documents made available that may prevent, condition or affect the purchase, and indicates for each the action to take before the preliminary contract or the deed.

### Object of this Report
The review covered the following areas, based on the documents available:

{areas_text}

{chain_scope_sentence} The review is documentary: it does not include an inspection of the property, a survey of its actual state, nor an access to the building records of the municipality, which are left to the technician appointed by the buyer. Where an exposure is quantified, the figure is the one stated in the source document; costs of regularisation, taxes and fees are left to the notary and the technician.

### Limitations
This Report is based on the following assumptions:

- all copies reviewed are true and complete copies of the originals;
- the registry and cadastral searches reflect the position at their date, and later entries may exist;
- no relevant documents or information have been withheld;
- no independent verification of the information supplied has been carried out;
- the review is limited to matters of Italian law;
- the Report reflects the position as of the date stated above and there is no obligation to update it.
""",
    "it": """{intro_heading}

### Scopo della Relazione
La presente Relazione riassume gli esiti della due diligence legale condotta sull'immobile oggetto di **{deal_title}**, nell'interesse della parte acquirente. Si concentra sulle criticità emerse dai documenti messi a disposizione che possano impedire, condizionare o incidere sull'acquisto, e indica per ciascuna l'azione da intraprendere prima del preliminare o del rogito.

### Oggetto della Relazione
La revisione ha riguardato le seguenti aree, sulla base dei documenti disponibili:

{areas_text}

{chain_scope_sentence} La revisione è documentale: non comprende il sopralluogo dell'immobile, il rilievo dello stato di fatto né l'accesso agli atti edilizi presso il Comune, rimessi al tecnico incaricato dalla parte acquirente. Ove un'esposizione sia quantificata, l'importo è quello indicato nel documento di origine; i costi di regolarizzazione, imposte e oneri sono rimessi al notaio e al tecnico.

### Limitazioni
La presente Relazione si basa sulle seguenti assunzioni:

- tutte le copie esaminate sono copie conformi e complete degli originali;
- le ispezioni ipotecarie e catastali riflettono la situazione alla loro data, e possono esistere formalità successive;
- nessun documento o informazione rilevante è stato omesso;
- non è stata svolta alcuna verifica indipendente delle informazioni fornite;
- la revisione è limitata a questioni di diritto italiano;
- la Relazione riflette la situazione alla data sopra indicata, senza alcun obbligo di aggiornamento.
""",
}

_NO_AREAS_LINE = {
    "en": "- No findings-bearing areas identified in the reviewed documents.",
    "it": "- Nessuna area con rilievi identificata nei documenti esaminati.",
}

_ITALIAN_MONTHS = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def _format_report_date(d: date, lang: str) -> str:
    if lang == "it":
        return f"{d.day} {_ITALIAN_MONTHS[d.month - 1]} {d.year}"
    return d.strftime("%d %B %Y")


import re as _re

# Heading patterns that should NOT be auto-numbered:
#   * Appendices (already labelled "Allegato I" / "Appendix I")
#   * Information Requests sub-sections that already carry the firm's
#     letter code ("### A. Documenti societari ...")
_APPENDIX_HEADING_RE = _re.compile(
    r"^(allegato|appendice|appendix)\b", _re.IGNORECASE
)
_FIRM_LETTER_PREFIX_RE = _re.compile(r"^[A-Z]\.\s")


def _add_section_numbering(markdown: str) -> str:
    """Prefix ## and ### headings with legal numbering (1., 1.1, 2., ...).

    The H1 title and Appendix headings are left unchanged. H3 sub-sections
    whose text already starts with a firm code (``A. Documenti ...``) are
    left unchanged too — that prefix IS their numbering.

    The numbering resets to 1 on every new ## (so H3 counters are scoped
    to their parent H2). This is a single-pass, line-by-line rewrite —
    fenced code blocks are not used in this template, so we don't need
    to skip them.
    """
    h2 = 0
    h3 = 0
    out: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("### "):
            text = line[4:].strip()
            if _FIRM_LETTER_PREFIX_RE.match(text):
                out.append(line)
                continue
            h3 += 1
            out.append(f"### {h2}.{h3} {text}")
            continue
        if line.startswith("## "):
            text = line[3:].strip()
            if _APPENDIX_HEADING_RE.match(text):
                # Appendix keeps its roman numeral, resets H3 counter.
                h3 = 0
                out.append(line)
                continue
            h2 += 1
            h3 = 0
            out.append(f"## {h2}. {text}")
            continue
        out.append(line)
    return "\n".join(out)


def _md_cell(text: str | None) -> str:
    """Make text safe for a Markdown table cell (no pipes / newlines).

    Returns the placeholder "n/a" when the source text is missing so the
    output never contains em-dashes (Italian legal prose convention).
    """
    if not text:
        return "n/a"
    # A list that occupies several lines (shareholders, board members) becomes
    # one cell, so the entries are separated rather than run together: without
    # a separator a cap table reads as "PALMIRA - 68% DANIELA - 10,67%".
    joined = "; ".join(line.strip() for line in text.splitlines() if line.strip())
    return joined.replace("|", "\\|").strip()


def _chain_scope_sentence(coverage, lang: str) -> str:
    """State how far back the titles on file reach, computed from their dates."""
    from packages.real_estate.rules_registry import format_date

    if coverage is None:
        return (
            "Nessun titolo di provenienza datato è presente tra i documenti esaminati: la "
            "provenienza ventennale non è verificata."
            if lang == "it" else
            "No dated title deed is among the documents reviewed: the twenty-year chain of "
            "title is not verified."
        )
    earliest = format_date(coverage.earliest_title, lang)
    required = format_date(coverage.required_from, lang)
    if coverage.covered:
        return (
            f"Il titolo più risalente esaminato è del {earliest}: i titoli agli atti coprono il "
            f"ventennio anteriore (dal {required})."
            if lang == "it" else
            f"The earliest title reviewed is dated {earliest}: the titles on file cover the "
            f"preceding twenty years (from {required})."
        )
    return (
        f"Il titolo più risalente esaminato è del {earliest}: la provenienza ventennale (dal "
        f"{required}) non è coperta dai documenti esaminati."
        if lang == "it" else
        f"The earliest title reviewed is dated {earliest}: the twenty-year chain (from "
        f"{required}) is not covered by the documents reviewed."
    )


def _render_introduction(deal_title: str, areas_reviewed: list[str], lang: str, coverage=None) -> str:
    areas_text = (
        "\n".join(f"- {label}" for label in areas_reviewed)
        if areas_reviewed
        else _NO_AREAS_LINE[lang]
    )
    return _INTRO_TEMPLATES[lang].format(
        intro_heading=_L10N[lang]["intro_heading"],
        deal_title=deal_title,
        areas_text=areas_text,
        chain_scope_sentence=_chain_scope_sentence(coverage, lang),
    )


def _format_source_citation(flag, doc_names: dict, lang: str) -> str:
    """Inline pinpoint citation for a red flag, e.g. "(SPA.pdf, p. 12)".

    Returns "" when there is no source document. The page is included only
    when the aggregator attributed (and validated) one.
    """
    payload = getattr(flag, "structured_payload_json", None) or {}
    if not isinstance(payload, dict) or payload.get("grounding_reviewed") is not True:
        payload = {}
    # New reports can have several independently validated source pages.
    # Never collapse a combined finding to one arbitrary page.
    references: dict[int, set[int]] = {}
    for entry in payload.get("evidence", []):
        if isinstance(entry, dict) and type(entry.get("source_document_id")) is int:
            doc_id = entry["source_document_id"]
            if doc_id in doc_names:
                references.setdefault(doc_id, set())
    for item in payload.get("source_pages", []):
        if not isinstance(item, dict):
            continue
        doc_id, page = item.get("source_document_id"), item.get("page")
        if type(doc_id) is int and doc_id in doc_names and type(page) is int and page > 0:
            references.setdefault(doc_id, set()).add(page)
    if references:
        page_label = "pp." if lang == "en" else "pagg."
        single_label = "p." if lang == "en" else "pag."
        return "(" + "; ".join(
            (f"{doc_names[doc_id]}, {page_label if len(pages) > 1 else single_label} "
             + ", ".join(str(page) for page in sorted(pages))) if pages else doc_names[doc_id]
            for doc_id, pages in sorted(references.items())
        ) + ")"
    doc_id = getattr(flag, "source_document_id", None)
    if doc_id is None:
        return ""
    filename = doc_names.get(doc_id)
    if not filename:
        return ""
    page = getattr(flag, "source_page", None)
    page_label = "p." if lang == "en" else "pag."
    inner = f"{filename}, {page_label} {page}" if page is not None else filename
    return f"({inner})"


# The instrument each recommendation calls for, rendered at the end of the
# recommendation cell the way a consolidated risk memo tags its lines.
_REMEDY_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "condition_precedent": "Condition precedent",
        "seller_undertaking": "Seller's undertaking",
        "escrow": "Escrow with the notary",
        "warranty": "Seller's warranty",
        "price_adjustment": "Price reduction",
        "pre_closing_verification": "Verification before the deed",
        "information_request": "Information request",
    },
    "it": {
        "condition_precedent": "Condizione sospensiva",
        "seller_undertaking": "Impegno del venditore",
        "escrow": "Deposito presso il notaio",
        "warranty": "Garanzia del venditore",
        "price_adjustment": "Riduzione del prezzo",
        "pre_closing_verification": "Verifica prima del rogito",
        "information_request": "Richiesta di informazioni",
    },
}


def _format_amount(amount: float, lang: str) -> str:
    """Render an amount in the conventions of the report's language."""
    rendered = f"{amount:,.0f}"
    if lang == "it":
        # Italian uses the dot as thousands separator.
        return "Euro " + rendered.replace(",", ".")
    return "EUR " + rendered


def _format_figures(flag, lang: str) -> str:
    """Render the amount and fiscal years a finding carries, if any.

    Real tax and financial reports put a figure and a year on the row. The
    amount is only ever the one the source document stated — the pipeline
    never computes an exposure — so a row without it is correct, not
    incomplete.
    """
    payload = getattr(flag, "structured_payload_json", None) or {}
    bits: list[str] = []

    amount = payload.get("amount_eur")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool):
        bits.append(_format_amount(float(amount), lang))

    years = payload.get("fiscal_years")
    if years:
        label = "es." if lang == "it" else "FY"
        bits.append(f"{label} {', '.join(str(y) for y in years)}")

    return f"({' · '.join(bits)})" if bits else ""


def _render_key_findings(red_flags: list, lang: str, doc_names: dict | None = None) -> str:
    """One table per DD area: rows hold the # / Issue / Risk / Recommendation
    / Severity quintuple. Mirrors the layout used by professional Italian
    red-flag DD reports (see the 5 anonymised sample reports). Flags
    without an area fall under "Other Matters".

    The first column of each row carries the finding title in bold
    followed by the issue prose in the same cell, so both are visible
    even at narrow column widths. PDF / DOCX exporters apply explicit
    column widths so long prose wraps cleanly.
    """
    doc_names = doc_names or {}
    if not red_flags:
        return (
            "## Key Findings\n\n"
            f"{_L10N[lang]['none_identified']}\n"
        )

    by_area: dict[str, list] = {}
    for f in red_flags:
        key = f.area.value if f.area else "other"
        by_area.setdefault(key, []).append(f)

    sev_rank = {"high": 0, "medium": 1, "low": 2}
    parts: list[str] = ["## Key Findings\n"]
    for area_key in _AREA_ORDER_KEYS:
        flags = by_area.get(area_key)
        if not flags:
            continue
        flags.sort(key=lambda f: sev_rank.get(f.severity.value, 3))
        parts.append(f"### {_AREA_TITLES[lang][area_key]}\n")
        parts.append(_L10N[lang]["findings_header"])
        parts.append(_L10N[lang]["findings_sep"])
        for i, f in enumerate(flags, start=1):
            # [SEVERITY] tokens are colorized by both PDF and DOCX exporters.
            sev = f"[{f.severity.value.upper()}]"
            issue_cell = (
                f"**{f.title}.** {f.issue.strip()}"
                if f.title else f.issue.strip()
            )
            # Append an inline pinpoint citation (document + page) so the
            # reader can trace each finding to its source.
            citation = _format_source_citation(f, doc_names, lang)
            if citation:
                issue_cell = f"{issue_cell} _{citation}_"
            figures = _format_figures(f, lang)
            if figures:
                issue_cell = f"{issue_cell} **{figures}**"

            recommendation_cell = f.recommendation
            remedy = _REMEDY_LABELS[lang].get(
                getattr(f, "remedy_type", None) or ""
            )
            if remedy:
                recommendation_cell = (
                    f"{(recommendation_cell or '').strip()} _[{remedy}]_".strip()
                )

            parts.append(
                f"| {i} | {_md_cell(issue_cell)} | {_md_cell(f.risk)} "
                f"| {_md_cell(recommendation_cell)} | {sev} |"
            )
        parts.append("")
    return "\n".join(parts)


_PROPERTY_FIELDS: dict[str, list[tuple[str, str]]] = {
    "en": [
        ("unit_label", "Unit"),
        ("indirizzo", "Address"),
        ("piano", "Floor"),
        ("comune", "Municipality"),
        ("sezione", "Section"),
        ("foglio", "Sheet (foglio)"),
        ("particella", "Parcel (particella)"),
        ("subalterno", "Sub-unit (subalterno)"),
        ("categoria", "Cadastral category"),
        ("classe", "Class"),
        ("consistenza", "Size"),
        ("superficie", "Cadastral surface"),
        ("rendita", "Cadastral income"),
        ("intestatari", "Holders"),
        ("titolo", "Title"),
        ("data_titolo", "Date of title"),
    ],
    "it": [
        ("unit_label", "Unità"),
        ("indirizzo", "Indirizzo"),
        ("piano", "Piano"),
        ("comune", "Comune"),
        ("sezione", "Sezione"),
        ("foglio", "Foglio"),
        ("particella", "Particella"),
        ("subalterno", "Subalterno"),
        ("categoria", "Categoria"),
        ("classe", "Classe"),
        ("consistenza", "Consistenza"),
        ("superficie", "Superficie catastale"),
        ("rendita", "Rendita"),
        ("intestatari", "Intestatari"),
        ("titolo", "Titolo"),
        ("data_titolo", "Data del titolo"),
    ],
}


def _render_property_identification(profiles: list, lang: str) -> str:
    """One table per unit, one value per field from the most authoritative source."""
    from packages.real_estate.property_identity import consolidate_property_profiles, format_holders

    heading = _L10N[lang]["corp_info_heading"]
    units = consolidate_property_profiles(profiles)
    if not units:
        message = (
            "No document among those reviewed identifies the property (cadastral "
            "extract, deed, floor plan). Obtain them before the preliminary contract."
            if lang == "en" else
            "Nessun documento tra quelli esaminati identifica l'immobile (visura "
            "catastale, atto di provenienza, planimetria). Acquisirli prima del preliminare."
        )
        return f"{heading}\n\n_{message}_\n"

    parts: list[str] = [f"{heading}\n"]
    for unit in units:
        parts.append(f"### {_md_cell(unit.label)}\n")
        parts.append(f"| {_L10N[lang]['field']} | {_L10N[lang]['value']} |")
        parts.append("|-------|-------|")
        for attr, label in _PROPERTY_FIELDS[lang]:
            value = format_holders(unit.intestatari) if attr == "intestatari" else unit.values.get(attr)
            if value:
                parts.append(f"| {label} | {_md_cell(value)} |")
        parts.append("")
        sources = unit.source_filenames or [
            f"{'Document' if lang == 'en' else 'Documento'} #{doc_id}" for doc_id in unit.source_document_ids
        ]
        if sources:
            label = "Sources" if lang == "en" else "Fonti"
            parts.append(f"**{label}:** {'; '.join(_md_cell(source) for source in sources)}.\n")
        if unit.conflicting_fields:
            fields = ", ".join(label for attr, label in _PROPERTY_FIELDS[lang] if attr in unit.conflicting_fields)
            message = (
                f"The deed, cadastral records and floor plans state different values for: {fields}. "
                "The table states the value of the most authoritative source; the point requires "
                "verification before the deed."
                if lang == "en" else
                f"Atto, visura e planimetria riportano valori diversi per: {fields}. La tabella "
                "riporta il valore della fonte più autorevole; il punto richiede verifica prima "
                "del rogito."
            )
            parts.append(f"_{message}_\n")
    return "\n".join(parts)


def _render_information_requests(
    missing_docs: list,
    info_requests: list,
    lang: str,
) -> str:
    """Render the Information Requests section grouped by checklist section.

    Layout follows the firm's standard checklist (sections A. through Q.):
    each section that has at least one missing item appears as a `###`
    sub-section, with the relevant items listed in their natural order
    (A.1, A.2, ...) and prefixed by the firm's item code. Free-form
    requests raised by the LLM aggregator that don't correspond to a
    checklist key fall under a trailing "Altri rilievi" section.
    """
    from packages.real_estate.checklist import (
        SECTIONS_ORDER,
        SECTION_NAMES,
        items_by_key,
    )

    heading = _L10N[lang]["info_requests_heading"]
    if not missing_docs and not info_requests:
        return f"{heading}\n\n{_L10N[lang]['none_identified']}\n"

    by_key = items_by_key()
    grouped: dict[str, list] = {}
    free_form_md: list = []  # MissingDocument rows with unknown key (legacy data)

    for md in missing_docs:
        item = by_key.get(md.document_category)
        if item is None:
            # Legacy data (pre-checklist run): render at the end.
            free_form_md.append(md)
            continue
        grouped.setdefault(item["section_code"], []).append((item, md))

    parts: list[str] = [heading, ""]
    counter = 1
    for section in SECTIONS_ORDER:
        items = grouped.get(section)
        if not items:
            continue
        section_label = SECTION_NAMES[section][lang]
        parts.append(f"### {section}. {section_label}")
        parts.append("")
        # Items are already ordered by id (intake writes them in CHECKLIST
        # order). Sort defensively by the firm's code suffix.
        items.sort(key=lambda pair: _sort_key_for_code(pair[0]["key"]))
        for item, md in items:
            text = (md.reason or item["request_it"]).strip()
            parts.append(f"{counter}. **{item['key']}** {text}")
            counter += 1
        parts.append("")

    extras: list[str] = []
    if free_form_md:
        for md in free_form_md:
            extras.append(
                f"{counter}. {(md.reason or md.expected_item).strip()}"
            )
            counter += 1
    for f in info_requests:
        extras.append(f"{counter}. **{f.title}.** {f.description}")
        counter += 1
    if extras:
        extras_label = (
            "Altri rilievi" if lang == "it" else "Other items"
        )
        parts.append(f"### {extras_label}")
        parts.append("")
        parts.extend(extras)
        parts.append("")

    return "\n".join(parts)


def _sort_key_for_code(code: str) -> tuple[str, int]:
    """Sort checklist codes like 'A.1', 'A.10' numerically within section."""
    if "." not in code:
        return (code, 0)
    letter, num = code.split(".", 1)
    try:
        return (letter, int(num))
    except ValueError:
        return (letter, 0)


def _render_documents_appendix(documents: list, lang: str) -> str:
    if not documents:
        return (
            f"{_L10N[lang]['appendix_heading']}\n\n"
            f"{_L10N[lang]['no_documents']}\n"
        )
    rows = "\n".join(
        f"| {_md_cell(d.filename)} | {d.language or 'n/a'} | {d.page_count or 'n/a'} |"
        for d in documents
    )
    return (
        f"{_L10N[lang]['appendix_heading']}\n\n"
        f"{_L10N[lang]['doc_table_header']}\n"
        f"{_L10N[lang]['doc_table_sep']}\n"
        f"{rows}\n"
    )


def _large_report_summary(documents_count: int, flags: list, observations_count: int, lang: str) -> str:
    """A bounded factual overview when the complete findings exceed the AI budget.

    All findings remain in the deterministic report tables. This overview makes
    its abbreviated scope explicit and does not infer an overall legal opinion.
    """
    counts = {severity: sum(f.severity.value == severity for f in flags)
              for severity in ("high", "medium", "low")}
    ranks = {"high": 0, "medium": 1, "low": 2}
    ordered = sorted(flags, key=lambda f: (ranks.get(f.severity.value, 3), f.id))
    titles = [f.title if len(f.title) <= 160 else f.title[:157] + "..." for f in ordered[:5]]
    if lang == "it":
        text = (f"Riepilogo sintetico: {documents_count} documenti analizzati, {len(flags)} rilievi "
                f"({counts['high']} di gravità alta, {counts['medium']} media, {counts['low']} bassa) "
                f"e {observations_count} osservazioni. ")
        if titles:
            text += "Primi rilievi in ordine di gravità: " + "; ".join(titles) + ". "
        return text + "Questo riepilogo è abbreviato; tutti i rilievi e le raccomandazioni sono riportati nelle sezioni successive."
    text = (f"Brief summary: {documents_count} documents analyzed, {len(flags)} findings "
            f"({counts['high']} high, {counts['medium']} medium, {counts['low']} low severity) "
            f"and {observations_count} observations. ")
    if titles:
        text += "First findings in severity order: " + "; ".join(titles) + ". "
    return text + "This summary is abbreviated; all findings and recommendations appear in the sections below."


class IncompleteAnalysisError(RuntimeError):
    """A report cannot be published from failed or unfinished analysis."""


def _analysis_signature(db, deal_id: int) -> tuple:
    """Identify the exact prerequisite runs, even on identical input data."""
    from app.models.agent_run import AgentRun
    return tuple(db.query(
        AgentRun.id, AgentRun.agent_name, AgentRun.status,
        AgentRun.started_at, AgentRun.completed_at, AgentRun.input_hash,
    ).filter(AgentRun.deal_id == deal_id, AgentRun.agent_name != "report_generation")
                 .order_by(AgentRun.id).all())


def generate_due_diligence_report(
    deal_id: int,
    db: Session,
    provider: LLMProvider | None = None,
) -> dict:
    """Generate (or regenerate) a due-diligence report for *deal_id*.

    Returns::

        {"report_id": int, "deal_id": int, "markdown": str}

    Raises ``ValueError`` if the deal does not exist.
    """
    from app.models.deal import Deal
    from app.models.document import Document, DocumentStatus
    from app.models.red_flag import RedFlag
    from app.models.report import Report, ReportType, ReportStatus
    from app.models.property_profile import PropertyProfile
    from packages.real_estate.prompts import EXECUTIVE_SUMMARY_PROMPT

    # ── Validate deal ─────────────────────────────────────────────────── #
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if deal is None:
        raise ValueError(f"Deal {deal_id} not found")

    from packages.agents.analysis_checkpoint import CheckpointError, require_report_inputs
    try:
        input_hash = require_report_inputs(db, deal_id)
    except CheckpointError as exc:
        raise IncompleteAnalysisError(str(exc)) from exc

    from packages.agents.deal_context import with_deal_context
    llm = with_deal_context(provider or get_judgment_provider(), db, deal_id)

    from app.models.agent_run import AgentRun, AgentRunStatus

    incomplete = (
        db.query(AgentRun)
        .filter(
            AgentRun.deal_id == deal_id,
            AgentRun.agent_name != "report_generation",
            AgentRun.status != AgentRunStatus.completed,
        )
        .first()
    )
    if incomplete is not None:
        raise IncompleteAnalysisError(
            "Analisi incompleta: riesegui l'analisi prima di generare il report."
        )

    analysis_signature = _analysis_signature(db, deal_id)
    admitted_status = deal.status

    logger.info("Generating due-diligence report for deal %d ('%s')", deal_id, deal.title)

    # Read the published report without modifying it. Replace it only
    # after generation succeeds, so a failed retry preserves its content.
    report = (
        db.query(Report)
        .filter(
            Report.deal_id == deal_id,
            Report.report_type == ReportType.due_diligence,
        )
        .first()
    )
    try:
        from app.models.agent_finding import AgentFinding
        from packages.agents.red_flag_aggregator import AGENT_NAME as AGGREGATOR_AGENT

        # ── Gather data ───────────────────────────────────────────────── #
        documents = (
            db.query(Document)
            .filter(
                Document.deal_id == deal_id,
                Document.status == DocumentStatus.processed,
            )
            .all()
        )

        red_flags = db.query(RedFlag).filter(RedFlag.deal_id == deal_id).all()

        property_profiles = (
            db.query(PropertyProfile)
            .options(joinedload(PropertyProfile.source_document))
            .filter(PropertyProfile.deal_id == deal_id)
            .order_by(PropertyProfile.id.asc())
            .all()
        )

        observations = (
            db.query(AgentFinding)
            .filter(
                AgentFinding.deal_id == deal_id,
                AgentFinding.agent_name == AGGREGATOR_AGENT,
                AgentFinding.category == "observation",
            )
            .all()
        )
        info_requests = (
            db.query(AgentFinding)
            .filter(
                AgentFinding.deal_id == deal_id,
                AgentFinding.agent_name == AGGREGATOR_AGENT,
                AgentFinding.category == "information_request",
            )
            .all()
        )

        # ── Executive summary via LLM (the only generated prose) ────────── #
        flags_context = (
            "\n".join(
                f"- [{f.severity.value.upper()}] {f.title}: {f.issue}"
                + (f" | Risk: {f.risk}" if f.risk else "")
                for f in red_flags
            )
            or "No red flags detected."
        )
        observations_context = (
            "\n".join(f"- {f.title}: {f.description}" for f in observations)
            or "None."
        )
        from packages.agents.output_language import (
            language_instruction,
            resolve_output_language,
        )
        lang = resolve_output_language(deal, db)

        summary_prompt = EXECUTIVE_SUMMARY_PROMPT.format(
            deal_title=deal.title,
            deal_description=deal.description or "N/A",
            documents_count=len(documents),
            red_flags=flags_context,
            observations=observations_context,
            language_instruction=language_instruction(lang),
        )
        if len(summary_prompt) > 24000:
            executive_summary = _large_report_summary(len(documents), red_flags, len(observations), lang)
        else:
            from packages.agents.grounding_review import review_grounded_text
            # Review against the persisted findings, including their
            # limitations and remedies. The generator cannot promote an
            # information gap into a fact at this final summarization step.
            import json
            summary_sources = [{
                "document_id": 0, "filename": "confirmed-review-context",
                "text": json.dumps({
                    "deal_title": deal.title,
                    "deal_description": deal.description,
                    "documents_reviewed": len(documents),
                    "red_flags_count": len(red_flags),
                    "observations_count": len(observations),
                    "severity_counts": {
                        severity: sum(f.severity.value == severity for f in red_flags)
                        for severity in ("high", "medium", "low")
                    },
                }, ensure_ascii=False),
            }] + [
                {"document_id": index + 1, "filename": f"finding-{index + 1}",
                 "text": "\n".join(str(value) for value in values if value)}
                for index, values in enumerate(
                    [(f.title, f"Severity: {f.severity.value}", f.issue, f.risk, f.recommendation) for f in red_flags]
                    + [(f.title, f.description) for f in observations]
                )
            ]
            context = getattr(llm, "context", None)
            for offset, loi in enumerate(getattr(context, "lois", ())):
                summary_sources.append({
                    "document_id": len(red_flags) + len(observations) + offset + 1,
                    "filename": loi.filename,
                    "text": "Proposed transaction context only; excerpt may be incomplete.\n" + loi.text,
                })
            from packages.agents.stage_tx import release_connection_before_llm
            release_connection_before_llm(db)
            executive_summary = llm.complete(summary_prompt, max_tokens=1536).strip()
            if executive_summary:
                executive_summary = review_grounded_text(
                    llm, executive_summary, summary_sources, lang,
                )
        if not executive_summary:
            from packages.agents.deal_analysis_agent import LLMResponseError

            raise LLMResponseError("Executive summary: AI response contained no text")

        # The model calls run without holding the admission row lock. Reacquire
        # it and check both inputs and run identity before reading live ORM rows
        # for assembly. Even an identical-corpus reanalysis is a new snapshot.
        deal = db.query(Deal).filter(Deal.id == deal_id).with_for_update().populate_existing().first()
        if deal is None:
            raise IncompleteAnalysisError("La pratica è cambiata durante la generazione: riprova.")
        try:
            current_hash = require_report_inputs(db, deal_id)
        except CheckpointError as exc:
            raise IncompleteAnalysisError(str(exc)) from exc
        if (current_hash != input_hash or deal.status != admitted_status
                or _analysis_signature(db, deal_id) != analysis_signature):
            raise IncompleteAnalysisError("L'analisi è cambiata durante la generazione: rigenera il report aggiornato.")
        # A concurrent generator may have created the row while this one was
        # awaiting its provider. Serialize publication on the deal, then re-read.
        report = db.query(Report).filter(
            Report.deal_id == deal_id, Report.report_type == ReportType.due_diligence,
        ).populate_existing().first()

        # ── Deterministic assembly ───────────────────────────────────── #
        areas_reviewed = [
            _AREA_TITLES[lang][key]
            for key in _AREA_ORDER_KEYS
            if any((f.area.value if f.area else "other") == key for f in red_flags)
        ]

        observations_md = (
            "\n".join(
                f"- **[{f.severity.value.upper()}]** {f.title}. {f.description}"
                for f in observations
            )
            or _L10N[lang]["none_identified"]
        )
        # Information Requests are rendered with the firm's section
        # structure (A. Documenti societari... / B. Beni immobili / ...)
        # using the checklist data — items are grouped by section_code so
        # the reader recognises the standard layout. Free-form requests
        # raised by the red-flag aggregator land in an "Altri rilievi /
        # Other items" trailing section.
        from app.models.missing_document import MissingDocument
        from packages.real_estate.consistency import chain_coverage_for

        missing_docs = (
            db.query(MissingDocument)
            .filter(MissingDocument.deal_id == deal_id)
            .order_by(MissingDocument.id.asc())
            .all()
        )
        info_requests_md = _render_information_requests(
            missing_docs, info_requests, lang
        )

        markdown = "\n".join([
            f"# {_REPORT_TITLE[lang]}",
            "",
            f"**{deal.title}**",
            "",
            f"_{_L10N[lang]['confidential']}_",
            "",
            f"_{_format_report_date(date.today(), lang)}_",
            "",
            _render_introduction(deal.title, areas_reviewed, lang, chain_coverage_for(property_profiles)),
            _render_property_identification(property_profiles, lang),
            "## Executive Summary",
            "",
            executive_summary,
            "",
            _render_key_findings(
                red_flags, lang, {d.id: d.filename for d in documents}
            ),
            _L10N[lang]["observations_heading"],
            "",
            observations_md,
            "",
            info_requests_md,
            "",
            _render_documents_appendix(documents, lang),
        ])

        # Apply legal section numbering (1., 1.1, 2., 2.1, ...) before
        # persisting. Headings already carrying a firm letter code (A.1)
        # or the appendix label are left alone — see _add_section_numbering.
        markdown = _add_section_numbering(markdown)

        # ── Persist result ────────────────────────────────────────────── #
        if report is None:
            report = Report(deal_id=deal_id, report_type=ReportType.due_diligence)
            db.add(report)
        report.title = f"{_REPORT_TITLE[lang]} — {deal.title}"
        report.content = markdown
        report.input_hash = input_hash
        report.status = ReportStatus.completed
        # A manual retry after the pipeline's report stage failed must clear
        # that failure too, otherwise the UI keeps labelling this new report
        # as a retained older version. Publish both updates atomically.
        failed_report_runs = db.query(AgentRun).filter(
            AgentRun.deal_id == deal_id,
            AgentRun.agent_name == "report_generation",
            AgentRun.status == AgentRunStatus.failed,
        ).all()
        if failed_report_runs:
            from datetime import datetime, timezone
            from app.models.deal import DealStatus

            for run in failed_report_runs:
                run.status = AgentRunStatus.completed
                run.error_message = None
                run.completed_at = datetime.now(timezone.utc)
            deal.status = DealStatus.reviewed
        db.commit()
        db.refresh(report)

        logger.info(
            "Report %d generated for deal %d (%d chars).",
            report.id, deal_id, len(markdown),
        )

        return {
            "report_id": report.id,
            "deal_id": deal_id,
            "markdown": markdown,
        }

    except Exception:
        logger.exception("Report generation failed for deal %d", deal_id)
        db.rollback()
        raise
