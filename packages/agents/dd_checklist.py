"""Standard due-diligence document checklist.

Defines the documents a professional Italian DD review expects to find in a
target's data room. Shared between :mod:`packages.agents.intake_agent`
(matches uploaded documents against the checklist and flags absences) and
:mod:`packages.agents.report_agent` (renders the absences as numbered
information requests in the Q&A style used by professional reports).

Each item is matched against a normalised needle composed of the document
filename (with underscores and hyphens converted to spaces) and the first
1000 characters of extracted text, both lower-cased. Keywords are matched
as substrings. Italian and English keywords coexist so an Italian data
room with a stray English filename still matches.
"""
from __future__ import annotations

from typing import TypedDict

from app.models.open_question import Priority


class ChecklistItem(TypedDict):
    key: str           # stable identifier, persisted as MissingDocument.document_category
    area: str          # one of the DueDiligenceArea enum values
    name_it: str       # short human-readable name
    name_en: str
    question_it: str   # ready-to-render question for the Information Requests section
    question_en: str
    keywords: list[str]
    priority: Priority


CHECKLIST: list[ChecklistItem] = [
    # ── Corporate ──────────────────────────────────────────────────────────
    {
        "key": "visura_camerale",
        "area": "corporate",
        "name_it": "Visura camerale aggiornata",
        "name_en": "Current company registration extract",
        "question_it": (
            "Si chiede di fornire la visura camerale aggiornata del Target."
        ),
        "question_en": (
            "Please provide the current Companies' Registry extract of the "
            "Target."
        ),
        "keywords": [
            "visura", "camerale", "rea ", "registro imprese",
            "company registration", "chamber of commerce",
        ],
        "priority": Priority.high,
    },
    {
        "key": "atto_costitutivo_statuto",
        "area": "corporate",
        "name_it": "Atto costitutivo e statuto vigente",
        "name_en": "Articles of incorporation and current bylaws",
        "question_it": (
            "Si chiede di fornire l'atto costitutivo e lo statuto vigente "
            "del Target."
        ),
        "question_en": (
            "Please provide the articles of incorporation and current bylaws "
            "of the Target."
        ),
        "keywords": [
            "atto costitutivo", "statuto", "bylaws", "by-laws",
            "articles of association", "articles of incorporation",
        ],
        "priority": Priority.high,
    },
    {
        "key": "libro_soci",
        "area": "corporate",
        "name_it": "Libro soci aggiornato",
        "name_en": "Updated shareholders' register",
        "question_it": (
            "Si chiede di fornire il libro soci aggiornato del Target."
        ),
        "question_en": (
            "Please provide the updated shareholders' register of the Target."
        ),
        "keywords": [
            "libro soci", "shareholders register", "shareholder register",
        ],
        "priority": Priority.medium,
    },
    {
        "key": "patti_parasociali",
        "area": "corporate",
        "name_it": "Patti parasociali",
        "name_en": "Shareholders' agreement",
        "question_it": (
            "Si chiede di confermare l'esistenza e, in tal caso, di fornire "
            "copia di eventuali patti parasociali in essere."
        ),
        "question_en": (
            "Please confirm the existence of any shareholders' agreement in "
            "place and, if so, provide a copy."
        ),
        "keywords": [
            "patto parasociale", "patti parasociali",
            "shareholders agreement", "shareholder agreement",
        ],
        "priority": Priority.high,
    },
    {
        "key": "verbali_assemblea_cda",
        "area": "corporate",
        "name_it": "Verbali assemblee e CdA degli ultimi 3 anni",
        "name_en": "Shareholders' meetings and board minutes (last 3 years)",
        "question_it": (
            "Si chiede di fornire i verbali delle assemblee dei soci e del "
            "Consiglio di Amministrazione degli ultimi tre esercizi."
        ),
        "question_en": (
            "Please provide the minutes of the shareholders' meetings and "
            "board of directors meetings for the last three fiscal years."
        ),
        "keywords": [
            "verbale assemblea", "verbale cda", "verbale consiglio",
            "board minutes", "shareholders meeting minutes",
        ],
        "priority": Priority.medium,
    },
    # ── Indebtedness / Financial ───────────────────────────────────────────
    {
        "key": "bilanci",
        "area": "indebtedness",
        "name_it": "Bilanci approvati degli ultimi 3 esercizi",
        "name_en": "Approved financial statements (last 3 years)",
        "question_it": (
            "Si chiede di fornire i bilanci approvati relativi agli ultimi "
            "tre esercizi."
        ),
        "question_en": (
            "Please provide the approved financial statements for the last "
            "three fiscal years."
        ),
        "keywords": [
            "bilancio", "stato patrimoniale", "conto economico",
            "financial statements", "balance sheet", "income statement",
        ],
        "priority": Priority.high,
    },
    {
        "key": "finanziamenti",
        "area": "indebtedness",
        "name_it": "Contratti di finanziamento, leasing e factoring in essere",
        "name_en": "Outstanding loan, leasing and factoring agreements",
        "question_it": (
            "Si chiede di fornire l'elenco e copia dei contratti di "
            "finanziamento, leasing e factoring in essere."
        ),
        "question_en": (
            "Please provide a list and copies of outstanding loan, leasing "
            "and factoring agreements."
        ),
        "keywords": [
            "mutuo", "finanziamento", "leasing", "factoring",
            "loan agreement", "credit facility", "credit agreement",
            "promissory note", "term loan", "revolving credit",
        ],
        "priority": Priority.high,
    },
    {
        "key": "garanzie",
        "area": "indebtedness",
        "name_it": "Elenco delle garanzie reali e personali rilasciate",
        "name_en": "List of security interests and personal guarantees granted",
        "question_it": (
            "Si chiede di fornire l'elenco delle garanzie reali (ipoteche, "
            "pegni) e personali (fideiussioni) rilasciate dal Target."
        ),
        "question_en": (
            "Please provide the list of security interests (mortgages, "
            "pledges) and personal guarantees (sureties) granted by the "
            "Target."
        ),
        "keywords": [
            "fideiussione", "garanzia", "ipoteca", "pegno",
            "mortgage", "pledge", "guarantee", "surety",
            "security agreement",
        ],
        "priority": Priority.medium,
    },
    # ── Real estate ────────────────────────────────────────────────────────
    {
        "key": "immobili",
        "area": "real_estate",
        "name_it": "Elenco immobili di proprietà e in locazione",
        "name_en": "List of owned and leased real estate",
        "question_it": (
            "Si chiede di fornire l'elenco degli immobili di proprietà e in "
            "locazione, con copia dei relativi atti."
        ),
        "question_en": (
            "Please provide the list of owned and leased real estate, "
            "together with copies of the relevant deeds."
        ),
        "keywords": [
            "immobile", "immobili", "locazione", "affitto",
            "lease agreement", "real estate", "proprietà immobiliare",
        ],
        "priority": Priority.medium,
    },
    # ── Employees ──────────────────────────────────────────────────────────
    {
        "key": "personale",
        "area": "employees",
        "name_it": "Organigramma ed elenco del personale dipendente",
        "name_en": "Organisational chart and employees list",
        "question_it": (
            "Si chiede di fornire l'organigramma aggiornato e l'elenco del "
            "personale dipendente con livello, inquadramento e anzianità."
        ),
        "question_en": (
            "Please provide the updated organisational chart and the list "
            "of employees with level, classification and seniority."
        ),
        "keywords": [
            "organigramma", "elenco dipendenti", "elenco personale",
            "organisational chart", "organizational chart", "headcount",
            "employees list",
        ],
        "priority": Priority.medium,
    },
    {
        "key": "ccnl_contratti_lavoro",
        "area": "employees",
        "name_it": "CCNL applicato e contratti dei dirigenti / figure chiave",
        "name_en": "Applicable collective agreement and key employment contracts",
        "question_it": (
            "Si chiede di indicare il CCNL applicato e di fornire copia dei "
            "contratti di lavoro dei dirigenti e delle figure chiave."
        ),
        "question_en": (
            "Please indicate the applicable collective bargaining agreement "
            "and provide copies of the employment contracts of executives "
            "and key personnel."
        ),
        "keywords": [
            "ccnl", "contratto collettivo", "contratto di lavoro",
            "employment contract", "collective bargaining",
        ],
        "priority": Priority.medium,
    },
    {
        "key": "contenzioso_lavoro",
        "area": "employees",
        "name_it": "Contenziosi giuslavoristici in essere o minacciati",
        "name_en": "Pending or threatened labour disputes",
        "question_it": (
            "Si chiede di confermare l'esistenza e di fornire dettaglio di "
            "eventuali contenziosi giuslavoristici in essere o minacciati."
        ),
        "question_en": (
            "Please confirm the existence and provide details of any "
            "pending or threatened labour disputes."
        ),
        "keywords": [
            "contenzios lavoro", "vertenza", "controversi lavoro",
            "labour dispute", "employment litigation",
        ],
        "priority": Priority.medium,
    },
    # ── Suppliers / Customers ──────────────────────────────────────────────
    {
        "key": "contratti_clienti",
        "area": "suppliers_customers",
        "name_it": "Contratti con i principali clienti",
        "name_en": "Contracts with key customers",
        "question_it": (
            "Si chiede di fornire copia dei contratti in essere con i "
            "principali clienti del Target."
        ),
        "question_en": (
            "Please provide copies of the contracts in place with the "
            "Target's key customers."
        ),
        "keywords": [
            "contratto cliente", "customer contract", "customer agreement",
            "clienti principali", "key customers",
        ],
        "priority": Priority.high,
    },
    {
        "key": "contratti_fornitori",
        "area": "suppliers_customers",
        "name_it": "Contratti con i principali fornitori",
        "name_en": "Contracts with key suppliers",
        "question_it": (
            "Si chiede di fornire copia dei contratti in essere con i "
            "principali fornitori del Target."
        ),
        "question_en": (
            "Please provide copies of the contracts in place with the "
            "Target's key suppliers."
        ),
        "keywords": [
            "contratto fornitore", "supplier contract", "supplier agreement",
            "vendor agreement", "fornitori principali",
        ],
        "priority": Priority.medium,
    },
    {
        "key": "contratti_agenzia_distribuzione",
        "area": "suppliers_customers",
        "name_it": "Contratti di agenzia e distribuzione",
        "name_en": "Agency and distribution agreements",
        "question_it": (
            "Si chiede di fornire copia dei contratti di agenzia e di "
            "distribuzione in essere."
        ),
        "question_en": (
            "Please provide copies of any agency and distribution "
            "agreements in place."
        ),
        "keywords": [
            "contratto di agenzia", "agente di commercio", "distribuzione",
            "agency agreement", "distribution agreement",
        ],
        "priority": Priority.medium,
    },
    # ── Insurance ──────────────────────────────────────────────────────────
    {
        "key": "polizze",
        "area": "insurance",
        "name_it": "Polizze assicurative in essere",
        "name_en": "Current insurance policies",
        "question_it": (
            "Si chiede di fornire l'elenco e copia delle polizze "
            "assicurative in essere (RC, danni, infortuni, D&O)."
        ),
        "question_en": (
            "Please provide a list and copies of current insurance "
            "policies (liability, property, accident, D&O)."
        ),
        "keywords": [
            "polizza", "polizza assicurativa", "assicurazione",
            "insurance policy", "insurance certificate",
        ],
        "priority": Priority.medium,
    },
    # ── Litigation ─────────────────────────────────────────────────────────
    {
        "key": "contenzioso",
        "area": "litigation",
        "name_it": "Contenziosi in corso (civili, fiscali, amministrativi)",
        "name_en": "Pending litigation (civil, tax, administrative)",
        "question_it": (
            "Si chiede di fornire l'elenco aggiornato dei contenziosi in "
            "corso o minacciati (civili, fiscali, amministrativi) con "
            "indicazione del rischio quantificato."
        ),
        "question_en": (
            "Please provide an updated list of pending or threatened "
            "litigation (civil, tax, administrative) with quantification "
            "of the related risk."
        ),
        # Italian noun stems ("contenzios", "controversi") match both
        # singular and plural forms ("contenzioso/i", "controversia/e").
        "keywords": [
            "contenzios", "controversi", "lawsuit", "litigation",
            "arbitrato", "arbitration", "complaint", "court order",
            "judgment",
        ],
        "priority": Priority.high,
    },
    # ── IP / IT ────────────────────────────────────────────────────────────
    {
        "key": "ip_it",
        "area": "ip_it",
        "name_it": "Marchi, brevetti, domini e contratti software",
        "name_en": "Trademarks, patents, domains and software agreements",
        "question_it": (
            "Si chiede di fornire l'elenco dei marchi, brevetti e domini "
            "registrati e copia dei contratti software / IT principali."
        ),
        "question_en": (
            "Please provide a list of registered trademarks, patents and "
            "domains, and copies of the main software / IT agreements."
        ),
        "keywords": [
            "marchio", "brevetto", "dominio",
            "trademark", "patent", "domain name",
            "software license", "licenza software", "license agreement",
        ],
        "priority": Priority.medium,
    },
    # ── Data protection ────────────────────────────────────────────────────
    {
        "key": "gdpr",
        "area": "data_protection",
        "name_it": "Documentazione GDPR (informative, registro trattamenti, DPIA)",
        "name_en": "GDPR documentation (notices, processing register, DPIA)",
        "question_it": (
            "Si chiede di fornire la documentazione GDPR del Target "
            "(informative privacy, registro dei trattamenti, eventuali "
            "DPIA, nomina del DPO)."
        ),
        "question_en": (
            "Please provide the Target's GDPR documentation (privacy "
            "notices, processing register, DPIAs if any, DPO appointment)."
        ),
        "keywords": [
            "gdpr", "privacy", "registro trattamenti", "informativa privacy",
            "data protection", "dpia",
            "data protection impact assessment",
        ],
        "priority": Priority.high,
    },
]


def items_by_key() -> dict[str, ChecklistItem]:
    """Lookup table keyed by ``ChecklistItem.key`` — for the report renderer."""
    return {item["key"]: item for item in CHECKLIST}


def normalize_needle(filename: str | None, raw_text: str | None) -> str:
    """Build the search needle a checklist item is matched against."""
    fn = (filename or "").lower().replace("_", " ").replace("-", " ")
    body = (raw_text or "")[:1000].lower()
    return fn + " " + body


def matched_keys(filename: str | None, raw_text: str | None) -> set[str]:
    """Return the set of checklist keys this document covers."""
    needle = normalize_needle(filename, raw_text)
    return {
        item["key"]
        for item in CHECKLIST
        if any(kw in needle for kw in item["keywords"])
    }
