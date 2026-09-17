"""Due-diligence report generation for deals.

Renders a red-flag due diligence report with the section structure used by
professional Italian M&A legal advisors:

    1. Introduction (purpose / object / limitations — deterministic boilerplate)
    2. Corporate Introductory Information (placeholder until extraction ships)
    3. Executive Summary (grounded prose, or a bounded factual overview for large reports)
    4. Key Findings — one table per DD area, each row carrying the
       Issue | Risk | Recommendation | Severity quadruple
    5. Observations / Information Requests (from the aggregator's AgentFindings)
    6. Appendix I: Documents Reviewed

Everything except the Executive Summary is rendered deterministically from
database rows — structure and data sections cannot hallucinate. Only the
summary prose goes through the LLM. Large reports use a clearly abbreviated,
deterministic summary while retaining every finding in the detail sections.

The report is stored in the ``Report`` table with
``report_type = due_diligence``.  Calling the function again for the same deal
replaces the previous due-diligence report (idempotent).
"""
import logging
from datetime import date

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)


# ── Localized template strings ──────────────────────────────────────────────
# Faithful to the bilingual practice observed in professional reports: the
# title, "Executive Summary" and "Key Findings" headings stay in English even
# in Italian reports; introduction, appendix and table headers are localized.

_AREA_ORDER_KEYS = [
    "corporate", "indebtedness", "financial", "real_estate", "employees",
    "suppliers_customers", "insurance", "litigation", "ip_it",
    "data_protection", "tax", "other",
]

_AREA_TITLES: dict[str, dict[str, str]] = {
    "en": {
        "corporate": "Corporate Matters",
        "indebtedness": "Indebtedness",
        "real_estate": "Real Estate",
        "employees": "Employees",
        "suppliers_customers": "Suppliers / Customers",
        "insurance": "Insurance",
        "litigation": "Litigation",
        "ip_it": "IP / IT",
        "data_protection": "Data Protection",
        "financial": "Financial Matters",
        "tax": "Tax",
        "other": "Other Matters",
    },
    "it": {
        "corporate": "Aspetti Societari",
        "indebtedness": "Indebitamento",
        "real_estate": "Immobili",
        "employees": "Dipendenti",
        "suppliers_customers": "Fornitori / Clienti",
        "insurance": "Assicurazioni",
        "litigation": "Contenzioso",
        "ip_it": "IP / IT",
        "data_protection": "Protezione dei Dati",
        "financial": "Materia Finanziaria",
        "tax": "Fiscale",
        "other": "Altri Aspetti",
    },
}

_L10N: dict[str, dict[str, str]] = {
    "en": {
        "confidential": "STRICTLY PRIVATE AND CONFIDENTIAL",
        "intro_heading": "## Introduction",
        "corp_info_heading": "## Corporate Introductory Information",
        "observations_heading": "## Observations",
        "info_requests_heading": "## Information Requests",
        "appendix_heading": "## Appendix I: Documents Reviewed",
        "none_identified": "_None identified based on available documents._",
        "no_documents": "_No processed documents._",
        "corp_info_placeholder": (
            "_To be completed by the deal team (registered office, corporate "
            "capital, shareholders, managing body, auditors)._"
        ),
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
        "corp_info_heading": "## Informazioni Societarie",
        "observations_heading": "## Osservazioni",
        "info_requests_heading": "## Richieste di Informazioni",
        "appendix_heading": "## Allegato I: Lista dei Documenti Esaminati",
        "none_identified": "_Nessun rilievo sulla base dei documenti disponibili._",
        "no_documents": "_Nessun documento processato._",
        "corp_info_placeholder": (
            "_Da completare a cura del deal team (sede legale, capitale "
            "sociale, soci, organo amministrativo, sindaci)._"
        ),
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
This Report summarises the results of the red-flag legal due diligence review conducted on **{deal_title}**. It focuses on material legal issues ("red flags") arising from the documents made available for review, to the extent they may significantly impact the contemplated transaction. It is not a substitute for a full set of contractual warranties.

### Object of this Report
The review covered the following areas, based on the documents available:

{areas_text}

Financial and tax matters are covered on a documentary, red-flag basis only, limited to the documents made available; this Report does not substitute a full financial or tax due diligence by the client's accounting and tax advisors. {tax_scope_sentence} Where an exposure is quantified, the figure is the one stated in the source document: the quantification of higher taxes, penalties and interest is left to the client's tax advisors, the applicable measures depending on the fiscal year and on the procedure followed. Accounting, technical, environmental and regulatory matters are outside the scope of this review.

### Limitations
This Report is based on the following assumptions:

- all copies reviewed are true and complete copies of the originals;
- all documents reviewed were validly executed by parties with the necessary capacity;
- no relevant documents or information have been withheld;
- no independent verification of the information supplied has been carried out;
- the review is limited to matters of Italian law;
- the Report reflects the position as of the date stated above and there is no obligation to update it.
""",
    "it": """{intro_heading}

### Scopo del Report
Il presente Report riassume gli esiti della legal due diligence di tipo red flag condotta su **{deal_title}**. Il Report si concentra sulle criticità legali rilevanti ("red flags") emerse dai documenti messi a disposizione, nella misura in cui possano incidere significativamente sull'operazione prospettata. Non sostituisce un set completo di dichiarazioni e garanzie contrattuali.

### Oggetto del Report
La revisione ha riguardato le seguenti aree, sulla base dei documenti disponibili:

{areas_text}

Gli aspetti finanziari e fiscali sono trattati su base esclusivamente documentale e di tipo red flag, nei limiti dei documenti messi a disposizione; il presente Report non sostituisce una due diligence finanziaria o fiscale completa a cura dei consulenti contabili e fiscali del cliente. {tax_scope_sentence} Ove un'esposizione sia quantificata, l'importo è quello indicato nel documento di origine: la quantificazione di maggiori imposte, sanzioni e interessi è rimessa ai consulenti fiscali del cliente, dipendendo le misure applicabili dal periodo d'imposta e dalla procedura seguita. Restano esclusi dall'ambito della revisione gli aspetti contabili, tecnici, ambientali e regolamentari.

### Limitazioni
Il presente Report si basa sulle seguenti assunzioni:

- tutte le copie esaminate sono copie conformi e complete degli originali;
- tutti i documenti esaminati sono stati validamente sottoscritti da parti munite dei necessari poteri;
- nessun documento o informazione rilevante è stato omesso;
- non è stata svolta alcuna verifica indipendente delle informazioni fornite;
- la revisione è limitata a questioni di diritto italiano;
- il Report riflette la situazione alla data sopra indicata, senza alcun obbligo di aggiornamento.
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
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _render_introduction(deal_title: str, areas_reviewed: list[str], lang: str) -> str:
    areas_text = (
        "\n".join(f"- {label}" for label in areas_reviewed)
        if areas_reviewed
        else _NO_AREAS_LINE[lang]
    )
    # Computed from the rules registry rather than fixed: the assessment
    # period moved from four years to five, so a sentence naming a number of
    # years would already be wrong for anything filed from 2016 on.
    from packages.agents import tax_rules_registry

    return _INTRO_TEMPLATES[lang].format(
        intro_heading=_L10N[lang]["intro_heading"],
        deal_title=deal_title,
        areas_text=areas_text,
        tax_scope_sentence=tax_rules_registry.describe_scope(language=lang),
    )


def _format_source_citation(flag, doc_names: dict, lang: str) -> str:
    """Inline pinpoint citation for a red flag, e.g. "(SPA.pdf, p. 12)".

    Returns "" when there is no source document. The page is included only
    when the aggregator attributed (and validated) one.
    """
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
        "indemnity": "Indemnity",
        "warranty": "Warranty",
        "price_adjustment": "Price adjustment",
        "earn_out": "Earn-out",
        "condition_precedent": "Condition precedent",
        "pre_closing_verification": "Pre-closing verification",
        "post_closing_action": "Post-closing action",
        "information_request": "Information request",
    },
    "it": {
        "indemnity": "Indennizzo",
        "warranty": "Dichiarazione e garanzia",
        "price_adjustment": "Aggiustamento prezzo",
        "earn_out": "Earn-out",
        "condition_precedent": "Condizione sospensiva",
        "pre_closing_verification": "Verifica pre-closing",
        "post_closing_action": "Adempimento post-closing",
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


_INTRO_FIELDS: dict[str, list[tuple[str, str]]] = {
    "en": [
        ("legal_form", "Legal Form"),
        ("incorporation_date", "Incorporation"),
        ("registered_office", "Registered Office"),
        ("corporate_capital", "Corporate Capital"),
        ("shareholders", "Shareholders"),
        ("pledge", "Pledge"),
        ("managing_body", "Managing Body"),
        ("auditors", "Auditors"),
        ("auditing_company", "Auditing Company"),
        ("business", "Business"),
        ("fiscal_year", "Fiscal Year"),
        ("duration", "Duration"),
    ],
    "it": [
        ("legal_form", "Forma Giuridica"),
        ("incorporation_date", "Costituzione"),
        ("registered_office", "Sede Legale"),
        ("corporate_capital", "Capitale Sociale"),
        ("shareholders", "Soci"),
        ("pledge", "Pegno"),
        ("managing_body", "Organo Amministrativo"),
        ("auditors", "Collegio Sindacale"),
        ("auditing_company", "Società di Revisione"),
        ("business", "Oggetto Sociale"),
        ("fiscal_year", "Esercizio Sociale"),
        ("duration", "Durata"),
    ],
}


def _render_corporate_intro(profiles: list, lang: str) -> str:
    if not profiles:
        return (
            f"{_L10N[lang]['corp_info_heading']}\n\n"
            f"{_L10N[lang]['corp_info_placeholder']}\n"
        )

    parts: list[str] = [f"{_L10N[lang]['corp_info_heading']}\n"]
    for p in profiles:
        parts.append(f"### {p.company_name}\n")
        parts.append(f"| {_L10N[lang]['field']} | {_L10N[lang]['value']} |")
        parts.append("|-------|-------|")
        for attr, label in _INTRO_FIELDS[lang]:
            value = getattr(p, attr, None)
            if value:
                parts.append(f"| {label} | {_md_cell(value)} |")
        parts.append("")
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
    from packages.agents.dd_checklist import (
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
    from app.models.company_profile import CompanyProfile
    from packages.prompts.deal_prompts import EXECUTIVE_SUMMARY_PROMPT

    llm = provider or get_llm_provider()

    # ── Validate deal ─────────────────────────────────────────────────── #
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if deal is None:
        raise ValueError(f"Deal {deal_id} not found")

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

        company_profiles = (
            db.query(CompanyProfile)
            .filter(CompanyProfile.deal_id == deal_id)
            .order_by(CompanyProfile.id.asc())
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
            executive_summary = llm.complete(summary_prompt, max_tokens=1024).strip()
        if not executive_summary:
            from packages.agents.deal_analysis_agent import LLMResponseError

            raise LLMResponseError("Executive summary: AI response contained no text")

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
        from packages.agents.dd_checklist import (
            CHECKLIST,
            SECTIONS_ORDER,
            SECTION_NAMES,
            items_by_key,
        )

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
            "# Red Flag Due Diligence Report",
            "",
            f"**{deal.title}**",
            "",
            f"_{_L10N[lang]['confidential']}_",
            "",
            f"_{_format_report_date(date.today(), lang)}_",
            "",
            _render_introduction(deal.title, areas_reviewed, lang),
            _render_corporate_intro(company_profiles, lang),
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
        report.title = f"Due Diligence Report — {deal.title}"
        report.content = markdown
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
