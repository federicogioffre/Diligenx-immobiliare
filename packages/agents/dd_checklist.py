"""Standard Italian DD legal checklist (NM Standard Legal Checklist v2).

Follows the structure of a professional Italian M&A legal
due diligence checklist used by the firm: 17 sections (A-Q) and ~80
items, each identified by the firm's numbering ("A.1", "A.2", "B.1", …).

The intake agent matches every uploaded document against the checklist
keywords. Items that no document covers are persisted as
``MissingDocument`` rows and the report renders them, grouped by
section, in the "Information Requests" section as a Q&A list to the
target.

Item shape
----------
Each item is a :class:`ChecklistItem` with:

* ``key`` — stable identifier persisted in ``MissingDocument.document_category``.
  Equal to the firm's code (e.g. ``"A.1"``).
* ``section_code`` / ``section_name_it`` / ``section_name_en`` — the
  parent section (one of A..Q), used for grouping in the report.
* ``area`` — the :class:`DueDiligenceArea` slot for the Key Findings
  section. Cross-referencing only; not user-visible in IR rendering.
* ``request_it`` / ``request_en`` — the request text to provide. Used
  as the question rendered in the report.
* ``keywords`` — substrings searched (lower-cased) in a needle composed
  of the document filename + first 1000 chars of extracted text. Italian
  noun stems ("contenzios", "garanzi") match both singular and plural.
* ``priority`` — high/medium/low, used to sort within the section.
"""
from __future__ import annotations

from typing import TypedDict

from app.models.open_question import Priority


class ChecklistItem(TypedDict):
    key: str
    section_code: str
    section_name_it: str
    section_name_en: str
    area: str
    request_it: str
    request_en: str
    keywords: list[str]
    priority: Priority


# ── Section metadata ─────────────────────────────────────────────────────
SECTIONS_ORDER: list[str] = [
    "A", "B", "C", "D", "E", "F", "G", "H",
    "I", "J", "K", "L", "M", "N", "O", "P", "Q",
]

SECTION_NAMES: dict[str, dict[str, str]] = {
    "A": {"it": "Documenti societari e capitale", "en": "Corporate documents and capital"},
    "B": {"it": "Beni immobili", "en": "Real estate"},
    "C": {"it": "Materia finanziaria", "en": "Financial matters"},
    "D": {"it": "Lavoro e previdenza", "en": "Employment and social security"},
    "E": {"it": "Permessi e autorizzazioni", "en": "Permits and authorisations"},
    "F": {"it": "Ambiente", "en": "Environment"},
    "G": {"it": "Contratti commerciali", "en": "Commercial contracts"},
    "H": {"it": "Assicurazioni", "en": "Insurance"},
    "I": {"it": "Contenzioso", "en": "Litigation"},
    "J": {"it": "Concorrenza", "en": "Competition"},
    "K": {"it": "Golden Power e investimenti esteri", "en": "Golden Power and foreign investment"},
    "L": {"it": "Proprietà intellettuale", "en": "Intellectual property"},
    "M": {"it": "IT e cybersecurity", "en": "IT and cybersecurity"},
    "N": {"it": "Privacy", "en": "Privacy"},
    "O": {"it": "Compliance", "en": "Compliance"},
    "P": {"it": "ESG e sostenibilità", "en": "ESG and sustainability"},
    "Q": {"it": "Fiscale (richiamo)", "en": "Tax (reference)"},
}


def _item(
    key: str,
    section: str,
    area: str,
    request_it: str,
    request_en: str,
    keywords: list[str],
    priority: Priority,
) -> ChecklistItem:
    return {
        "key": key,
        "section_code": section,
        "section_name_it": SECTION_NAMES[section]["it"],
        "section_name_en": SECTION_NAMES[section]["en"],
        "area": area,
        "request_it": request_it,
        "request_en": request_en,
        "keywords": keywords,
        "priority": priority,
    }


# ── The checklist ────────────────────────────────────────────────────────

CHECKLIST: list[ChecklistItem] = [
    # ── A. Documenti societari e capitale ────────────────────────────────
    _item(
        "A.1", "A", "corporate",
        "Visure estratte dal Registro Imprese relative alla Società e alle "
        "sue controllate, unitamente alle pratiche già presentate ma non "
        "ancora evase.",
        "Companies' Registry extracts of the Company and its subsidiaries, "
        "together with filings submitted but not yet processed.",
        ["visura camerale", "visure registro imprese", "registro imprese",
         "camera di commercio"],
        Priority.high,
    ),
    _item(
        "A.2", "A", "corporate",
        "Atto costitutivo e statuto sociale vigente della Società e delle "
        "sue controllate, con tutte le modifiche intervenute dalla "
        "costituzione.",
        "Articles of incorporation and current bylaws of the Company and "
        "its subsidiaries, with all amendments since incorporation.",
        ["atto costitutivo", "statuto", "bylaws", "articles of association",
         "articles of incorporation"],
        Priority.high,
    ),
    _item(
        "A.3", "A", "corporate",
        "Libro soci e, ove esistenti, certificati azionari; risultanze del "
        "Registro Imprese sulla titolarità delle partecipazioni.",
        "Shareholders' register and, where applicable, share certificates; "
        "Companies' Registry data on ownership of the shares.",
        ["libro soci", "certificati azionari", "shareholders register"],
        Priority.high,
    ),
    _item(
        "A.4", "A", "corporate",
        "Organigramma del gruppo, con indicazione delle percentuali di "
        "partecipazione e di eventuali partecipazioni in altre società o "
        "enti.",
        "Group chart showing ownership percentages and any equity interests "
        "in other companies or entities.",
        ["organigramma di gruppo", "organigramma societario",
         "group structure", "group chart"],
        Priority.medium,
    ),
    _item(
        "A.5", "A", "corporate",
        "Documentazione relativa a versamenti di capitale, conferimenti in "
        "natura, versamenti in conto capitale e finanziamenti soci, con "
        "indicazione delle relative condizioni (anche ai fini dell'art. "
        "2467 c.c.).",
        "Documentation on capital contributions, in-kind contributions, "
        "capital injections and shareholder loans, with their terms "
        "(including for art. 2467 of the Italian Civil Code).",
        ["versamento in conto capitale", "conferimento in natura",
         "finanziamento soci", "shareholder loan"],
        Priority.medium,
    ),
    _item(
        "A.6", "A", "corporate",
        "Elenco degli organi di amministrazione e controllo, dei procuratori "
        "e dei soggetti con potere di firma, con indicazione di poteri, "
        "durata dell'incarico e compensi; copia delle procure e dei "
        "contratti con gli amministratori.",
        "List of directors, statutory auditors, attorneys-in-fact and "
        "signatories, with powers, term and compensation; copies of "
        "powers of attorney and directors' agreements.",
        ["procura", "consiglio di amministrazione", "collegio sindacale",
         "power of attorney", "board of directors"],
        Priority.high,
    ),
    _item(
        "A.7", "A", "corporate",
        "Verbali delle assemblee dei soci degli ultimi 5 anni.",
        "Shareholders' meeting minutes for the last 5 years.",
        ["verbale assemblea", "verbali assemblee", "shareholders meeting minutes",
         "verbale dei soci"],
        Priority.medium,
    ),
    _item(
        "A.8", "A", "corporate",
        "Verbali delle riunioni del consiglio di amministrazione degli "
        "ultimi 3 anni.",
        "Board of directors' meeting minutes for the last 3 years.",
        ["verbale cda", "verbale consiglio di amministrazione",
         "board minutes", "board of directors minutes"],
        Priority.medium,
    ),
    _item(
        "A.9", "A", "corporate",
        "Verbali del collegio sindacale (o organo equivalente) degli ultimi "
        "3 anni e relazioni del soggetto incaricato della revisione legale.",
        "Statutory auditors' meeting minutes for the last 3 years and "
        "reports of the statutory audit firm.",
        ["verbale collegio sindacale", "relazione revisione legale",
         "statutory auditors", "audit report"],
        Priority.medium,
    ),
    _item(
        "A.10", "A", "corporate",
        "Patti parasociali, accordi tra soci, opzioni, diritti di "
        "prelazione, warrant e ogni altro accordo o promessa avente ad "
        "oggetto le partecipazioni della Società.",
        "Shareholders' agreements, options, pre-emption rights, warrants "
        "and any other agreement or promise concerning the Company's shares.",
        ["patto parasociale", "patti parasociali", "shareholders agreement",
         "diritto di prelazione", "warrant", "opzione"],
        Priority.high,
    ),
    _item(
        "A.11", "A", "corporate",
        "Accordi tra la Società e parti correlate (soci, amministratori, "
        "dirigenti, società del gruppo), inclusi accordi di gestione, di "
        "ripartizione di utili e di servizi infragruppo.",
        "Related-party agreements (shareholders, directors, executives, "
        "group companies), including management agreements, profit-sharing "
        "and intercompany services agreements.",
        ["parti correlate", "related party", "infragruppo",
         "intercompany agreement"],
        Priority.medium,
    ),
    _item(
        "A.12", "A", "corporate",
        "Documentazione relativa a operazioni straordinarie (fusioni, "
        "scissioni, conferimenti, cessioni di azienda o rami) perfezionate "
        "negli ultimi 5 anni o attualmente pianificate.",
        "Documentation on extraordinary transactions (mergers, demergers, "
        "contributions, sales of business or branches) completed in the "
        "last 5 years or currently planned.",
        ["fusione", "scissione", "conferimento di azienda", "cessione di azienda",
         "merger", "demerger", "carve-out"],
        Priority.medium,
    ),
    # ── B. Beni immobili ─────────────────────────────────────────────────
    _item(
        "B.1", "B", "real_estate",
        "Elenco di tutti i beni immobili di proprietà o in uso alla Società, "
        "con ubicazione, dati catastali, superficie e destinazione (ad es. "
        "stabilimenti, uffici, magazzini).",
        "List of all real estate owned or used by the Company, with "
        "location, cadastral data, surface area and use (e.g. plants, "
        "offices, warehouses).",
        ["elenco immobili", "beni immobili", "real estate list",
         "list of real estate"],
        Priority.medium,
    ),
    _item(
        "B.2", "B", "real_estate",
        "Ispezioni ipotecarie e visure catastali relative agli immobili di "
        "proprietà, con indicazione di ipoteche, vincoli, privilegi e altri "
        "gravami.",
        "Mortgage and cadastral searches on owned real estate, with "
        "mortgages, encumbrances, liens and other charges.",
        ["ispezione ipotecaria", "visura catastale", "ipoteca",
         "cadastral search", "mortgage search"],
        Priority.medium,
    ),
    _item(
        "B.3", "B", "real_estate",
        "Atti di provenienza e contratti di acquisto degli immobili di "
        "proprietà.",
        "Title deeds and purchase agreements for owned real estate.",
        ["atto di provenienza", "rogito", "title deed", "purchase deed"],
        Priority.low,
    ),
    _item(
        "B.4", "B", "real_estate",
        "Contratti di locazione e di leasing immobiliare, con indicazione "
        "di canone, durata, facoltà di recesso, registrazione e garanzie "
        "rilasciate.",
        "Lease and real-estate leasing agreements, with rent, term, "
        "termination rights, registration and guarantees provided.",
        ["contratto di locazione", "leasing immobiliare", "lease agreement",
         "locazione commerciale"],
        Priority.medium,
    ),
    _item(
        "B.5", "B", "real_estate",
        "Titoli edilizi (permessi di costruire, SCIA, segnalazioni "
        "certificate di agibilità) relativi agli immobili utilizzati, con "
        "indicazione di eventuali abusi, condoni o procedimenti di sanatoria "
        "in corso.",
        "Building permits (building permits, SCIA, certificates of "
        "occupancy) for the used real estate, with any unauthorised works, "
        "amnesties or pending regularisation proceedings.",
        ["permesso di costruire", "scia", "certificato di agibilità",
         "building permit"],
        Priority.low,
    ),
    # ── C. Materia finanziaria ───────────────────────────────────────────
    _item(
        "C.1", "C", "indebtedness",
        "Bilanci di esercizio (e consolidati, ove redatti) degli ultimi 3 "
        "esercizi, con nota integrativa, relazione sulla gestione e "
        "relazioni dell'organo di controllo e del revisore (richiamo, in "
        "coordinamento con la due diligence finanziaria).",
        "Financial statements (and consolidated, where prepared) for the "
        "last 3 fiscal years, with notes, management report and reports "
        "of the auditors (reference, in coordination with financial DD).",
        ["bilancio di esercizio", "bilancio consolidato",
         "financial statements", "balance sheet"],
        Priority.high,
    ),
    _item(
        "C.2", "C", "indebtedness",
        "Contratti di mutuo, finanziamento e leasing finanziario, con "
        "specifica evidenza di covenant, eventi di default e clausole di "
        "change of control o di rimborso anticipato obbligatorio.",
        "Loan, financing and financial leasing agreements, with covenants, "
        "events of default and change-of-control or mandatory prepayment "
        "clauses highlighted.",
        ["contratto di mutuo", "contratto di finanziamento", "leasing finanziario",
         "loan agreement", "credit facility", "covenant"],
        Priority.high,
    ),
    _item(
        "C.3", "C", "indebtedness",
        "Garanzie reali e personali concesse dalla Società a terzi o da "
        "terzi alla Società (pegni, ipoteche, fideiussioni, lettere di "
        "patronage), con indicazione delle obbligazioni garantite.",
        "Security interests and personal guarantees granted by the Company "
        "to third parties or by third parties to the Company (pledges, "
        "mortgages, sureties, comfort letters), with secured obligations.",
        ["pegno", "ipoteca", "fideiussione", "lettera di patronage",
         "patronage letter", "guarantee", "surety"],
        Priority.high,
    ),
    _item(
        "C.4", "C", "indebtedness",
        "Contratti di factoring e di cessione di crediti, strumenti "
        "finanziari derivati, accordi di cash pooling e finanziamenti "
        "infragruppo.",
        "Factoring and receivables assignment agreements, financial "
        "derivatives, cash pooling agreements and intercompany financing.",
        ["factoring", "cessione di crediti", "cash pooling", "derivati",
         "derivative", "receivables assignment"],
        Priority.medium,
    ),
    _item(
        "C.5", "C", "indebtedness",
        "Elenco dei finanziamenti pubblici e delle agevolazioni ricevute, "
        "con indicazione di condizioni, vincoli di destinazione e obblighi "
        "di mantenimento, anche ai fini della disciplina sugli aiuti di "
        "Stato.",
        "Public financing and grants received, with conditions, "
        "earmarking and maintenance obligations, also for State aid rules.",
        ["finanziamento pubblico", "agevolazione", "aiuti di stato",
         "state aid", "contributo pubblico"],
        Priority.medium,
    ),
    _item(
        "C.6", "C", "indebtedness",
        "Elenco degli affidamenti bancari in essere e del relativo utilizzo.",
        "List of outstanding bank facilities and their utilisation.",
        ["affidamenti bancari", "linea di credito", "bank facility",
         "credit line"],
        Priority.medium,
    ),
    # ── D. Lavoro e previdenza ───────────────────────────────────────────
    _item(
        "D.1", "D", "employees",
        "Elenco del personale (dipendenti, dirigenti, collaboratori, "
        "lavoratori somministrati), predisposto nel rispetto della "
        "normativa in materia di protezione dei dati personali, con "
        "indicazione di: tipologia del rapporto, data di assunzione, "
        "inquadramento e CCNL applicato, retribuzione fissa e variabile, "
        "fringe benefit, ferie e permessi residui, TFR accantonato.",
        "Headcount list (employees, executives, collaborators, agency "
        "workers), in compliance with data-protection law, showing: "
        "contract type, hire date, classification and applicable CCNL, "
        "fixed and variable pay, benefits, residual holidays and TFR.",
        ["elenco del personale", "elenco dipendenti", "organigramma",
         "headcount", "employees list"],
        Priority.high,
    ),
    _item(
        "D.2", "D", "employees",
        "Contratti con dirigenti e risorse chiave, inclusi distacchi, patti "
        "di non concorrenza, patti di stabilità e indennità connesse alla "
        "cessazione del rapporto, nonché le relative delibere di nomina e "
        "di determinazione dei compensi.",
        "Agreements with executives and key resources, including "
        "secondments, non-compete and stability covenants and termination "
        "indemnities, plus the related appointment and compensation "
        "resolutions.",
        ["contratto dirigente", "patto di non concorrenza", "patto di stabilità",
         "non-compete", "executive contract"],
        Priority.high,
    ),
    _item(
        "D.3", "D", "employees",
        "Contratti standard di lavoro subordinato e copia di tutti i "
        "contratti non-standard (a termine, apprendistato, part-time), con "
        "relativa busta paga tipo.",
        "Standard employment contracts and copies of all non-standard "
        "ones (fixed-term, apprenticeship, part-time), with a sample "
        "payslip.",
        ["contratto di lavoro", "lavoro subordinato", "apprendistato",
         "employment contract"],
        Priority.medium,
    ),
    _item(
        "D.4", "D", "employees",
        "Policy e condizioni generali applicate al personale (rimborsi "
        "spese, straordinari, auto aziendale, riservatezza, titolarità "
        "delle invenzioni), regolamenti interni e descrizione di prassi "
        "aziendali non formalizzate.",
        "Policies and general terms applied to employees (expense "
        "reimbursement, overtime, company car, confidentiality, ownership "
        "of inventions), internal rules and description of unwritten "
        "company practices.",
        ["policy aziendale", "regolamento interno", "company policy",
         "policy hr"],
        Priority.low,
    ),
    _item(
        "D.5", "D", "employees",
        "Contratti con lavoratori autonomi, collaboratori coordinati e "
        "continuativi, prestatori occasionali e agenti; accordi con agenzie "
        "di somministrazione, con elenco dei lavoratori somministrati negli "
        "ultimi 2 anni, durata media delle missioni e ragioni del ricorso.",
        "Agreements with self-employed contractors, coordinated and "
        "continuous collaborators, occasional providers and agents; "
        "agency-work agreements, with the list of agency workers over the "
        "last 2 years, average assignment duration and reasons for use.",
        ["contratto co.co.co", "lavoratore autonomo", "somministrazione",
         "agency work", "self-employed"],
        Priority.medium,
    ),
    _item(
        "D.6", "D", "employees",
        "Piani di incentivazione (MBO, bonus, stock option o piani "
        "equivalenti), previdenza complementare e ogni altra forma di "
        "retribuzione differita.",
        "Incentive plans (MBO, bonus, stock options or equivalent), "
        "supplementary pension and any other form of deferred "
        "compensation.",
        ["mbo", "stock option", "piano di incentivazione", "incentive plan",
         "deferred compensation"],
        Priority.medium,
    ),
    _item(
        "D.7", "D", "employees",
        "Indicazione dei CCNL applicati; contratti collettivi territoriali "
        "e aziendali; descrizione delle rappresentanze sindacali (RSA/RSU), "
        "percentuale di sindacalizzazione e scioperi degli ultimi 3 anni.",
        "Applicable CCNLs; territorial and company-level collective "
        "agreements; description of trade-union representatives "
        "(RSA/RSU), unionisation rate and strikes over the last 3 years.",
        ["ccnl", "contratto collettivo", "rsa", "rsu", "sindacato",
         "collective bargaining"],
        Priority.medium,
    ),
    _item(
        "D.8", "D", "employees",
        "Documentazione relativa al collocamento obbligatorio ex L. "
        "68/1999 (prospetto informativo, convenzioni, esoneri).",
        "Documentation on mandatory placement under Law 68/1999 "
        "(information form, conventions, exemptions).",
        ["collocamento obbligatorio", "legge 68", "categorie protette"],
        Priority.low,
    ),
    _item(
        "D.9", "D", "employees",
        "DURC di data recente e documentazione attestante la regolarità dei "
        "versamenti a INPS, INAIL, Enasarco e fondi di previdenza "
        "complementare.",
        "Recent DURC and documentation proving correct payments to INPS, "
        "INAIL, Enasarco and supplementary pension funds.",
        ["durc", "inps", "inail", "enasarco"],
        Priority.medium,
    ),
    _item(
        "D.10", "D", "employees",
        "Adempimenti in materia di salute e sicurezza ex D.Lgs. 81/2008: "
        "DVR, nomine (RSPP, medico competente, addetti alle emergenze), "
        "registro infortuni, attestati di formazione.",
        "Health and safety compliance under Legislative Decree 81/2008: "
        "DVR, appointments (RSPP, competent doctor, emergency staff), "
        "accident register, training certificates.",
        ["dvr", "d.lgs. 81", "rspp", "salute e sicurezza", "health and safety"],
        Priority.medium,
    ),
    _item(
        "D.11", "D", "employees",
        "Verbali di ispezioni INPS, INAIL e Ispettorato Nazionale del "
        "Lavoro degli ultimi 5 anni; contenzioso giuslavoristico pendente "
        "o minacciato (da coordinare con la Sezione I).",
        "Inspection reports by INPS, INAIL and the National Labour "
        "Inspectorate for the last 5 years; pending or threatened labour "
        "disputes (to be coordinated with Section I).",
        ["ispezione inps", "ispezione inail", "ispettorato del lavoro",
         "contenzios lavoro"],
        Priority.medium,
    ),
    _item(
        "D.12", "D", "employees",
        "Procedure di licenziamento collettivo, ricorso ad ammortizzatori "
        "sociali e trasferimenti d'azienda ex art. 2112 c.c. negli ultimi "
        "5 anni, con indicazione degli impegni assunti verso dipendenti e "
        "sindacati.",
        "Collective dismissal procedures, recourse to social safety nets "
        "and business transfers under art. 2112 of the Italian Civil Code "
        "over the last 5 years, with commitments made to employees and "
        "unions.",
        ["licenziamento collettivo", "cassa integrazione", "trasferimento d'azienda",
         "art. 2112"],
        Priority.low,
    ),
    _item(
        "D.13", "D", "employees",
        "Adempimenti in materia di immigrazione e impiego di lavoratori "
        "extracomunitari.",
        "Immigration compliance and employment of non-EU workers.",
        ["permesso di soggiorno", "lavoratori extracomunitari",
         "immigration"],
        Priority.low,
    ),
    # ── E. Permessi e autorizzazioni ─────────────────────────────────────
    _item(
        "E.1", "E", "other",
        "Elenco e copia di tutte le autorizzazioni, licenze, concessioni, "
        "certificazioni e SCIA necessarie allo svolgimento dell'attività "
        "(escluse le materie edilizia e ambientale, di cui alle Sezioni B "
        "e F), con indicazione delle scadenze e dello stato dei rinnovi.",
        "List and copies of all authorisations, licences, concessions, "
        "certifications and SCIAs required for the business (excluding "
        "construction and environmental matters in Sections B and F), "
        "with expiry dates and status of renewals.",
        ["autorizzazione amministrativa", "licenza", "concessione",
         "certificazione iso", "scia"],
        Priority.medium,
    ),
    _item(
        "E.2", "E", "other",
        "Informazioni su autorizzazioni necessarie e non ancora ottenute o "
        "in corso di rilascio; provvedimenti di diffida, sospensione o "
        "revoca ricevuti.",
        "Information on required authorisations not yet obtained or being "
        "issued; warnings, suspensions or revocations received.",
        ["diffida", "sospensione", "revoca", "warning notice"],
        Priority.medium,
    ),
    # ── F. Ambiente ──────────────────────────────────────────────────────
    _item(
        "F.1", "F", "other",
        "Autorizzazioni ambientali (AUA, AIA, autorizzazioni a emissioni in "
        "atmosfera, scarichi idrici, gestione rifiuti), con indicazione "
        "delle scadenze e dello stato dei rinnovi.",
        "Environmental authorisations (AUA, AIA, air emissions, water "
        "discharges, waste management), with expiry dates and renewal "
        "status.",
        ["aua", "aia", "autorizzazione ambientale", "emissioni in atmosfera"],
        Priority.medium,
    ),
    _item(
        "F.2", "F", "other",
        "Gestione dei rifiuti: registri di carico e scarico, MUD, contratti "
        "con trasportatori e smaltitori e relative iscrizioni all'Albo "
        "Gestori Ambientali.",
        "Waste management: loading/unloading registers, MUD, agreements "
        "with carriers and disposers and their Environmental Operators' "
        "Register entries.",
        ["mud", "gestione rifiuti", "albo gestori ambientali",
         "rifiuti speciali"],
        Priority.low,
    ),
    _item(
        "F.3", "F", "other",
        "Informazioni su contaminazioni, procedimenti di bonifica o messa "
        "in sicurezza ex D.Lgs. 152/2006; eventuali indagini ambientali "
        "svolte (Fase I/Fase II).",
        "Information on contamination, remediation or safety procedures "
        "under Legislative Decree 152/2006; environmental surveys "
        "conducted (Phase I/Phase II).",
        ["bonifica", "contaminazione", "d.lgs. 152", "phase i environmental"],
        Priority.low,
    ),
    _item(
        "F.4", "F", "other",
        "Presenza di sostanze pericolose, amianto, serbatoi interrati; "
        "certificazioni ISO 14001 o EMAS.",
        "Presence of hazardous substances, asbestos, underground tanks; "
        "ISO 14001 or EMAS certifications.",
        ["amianto", "serbatoi interrati", "iso 14001", "emas"],
        Priority.low,
    ),
    _item(
        "F.5", "F", "other",
        "Ispezioni, sanzioni e contenzioso in materia ambientale degli "
        "ultimi 5 anni.",
        "Environmental inspections, penalties and litigation over the "
        "last 5 years.",
        ["ispezione ambientale", "sanzione ambientale",
         "contenzios ambientale"],
        Priority.medium,
    ),
    # ── G. Contratti commerciali ─────────────────────────────────────────
    _item(
        "G.1", "G", "suppliers_customers",
        "Elenco di tutti i contratti contenenti clausole di change of "
        "control, divieto di cessione, esclusiva o non concorrenza, con "
        "copia dei contratti rilevanti.",
        "List of all agreements containing change-of-control, "
        "assignment-prohibition, exclusivity or non-compete clauses, with "
        "copies of the relevant agreements.",
        ["change of control", "clausola di cambio di controllo",
         "esclusiva", "non concorrenza"],
        Priority.high,
    ),
    _item(
        "G.2", "G", "suppliers_customers",
        "Elenco dei dodici principali fornitori, suddivisi per categoria "
        "di prodotto o servizio, con copia dei relativi contratti; "
        "evidenza dei fornitori strategici o non sostituibili.",
        "List of the twelve main suppliers, broken down by product or "
        "service category, with copies of the relevant agreements; "
        "highlight strategic or irreplaceable suppliers.",
        ["principali fornitori", "elenco fornitori", "contratto fornitore",
         "key suppliers"],
        Priority.high,
    ),
    _item(
        "G.3", "G", "suppliers_customers",
        "Elenco dei dodici principali clienti, suddivisi per categoria di "
        "prodotto o servizio, con copia dei relativi contratti.",
        "List of the twelve main customers, broken down by product or "
        "service category, with copies of the relevant agreements.",
        ["principali clienti", "elenco clienti", "contratto cliente",
         "key customers"],
        Priority.high,
    ),
    _item(
        "G.4", "G", "suppliers_customers",
        "Contratti di distribuzione, agenzia, procacciamento d'affari e "
        "franchising, con elenco di distributori e agenti.",
        "Distribution, agency, business introduction and franchising "
        "agreements, with the list of distributors and agents.",
        ["distribuzione", "agenzia", "franchising", "procacciamento",
         "distribution agreement", "agency agreement"],
        Priority.medium,
    ),
    _item(
        "G.5", "G", "suppliers_customers",
        "Condizioni generali di vendita, di acquisto e di "
        "assistenza/manutenzione; garanzie convenzionali rilasciate ai "
        "clienti.",
        "General conditions of sale, purchase and "
        "support/maintenance; warranties granted to customers.",
        ["condizioni generali di vendita", "condizioni di acquisto",
         "general terms and conditions"],
        Priority.medium,
    ),
    _item(
        "G.6", "G", "suppliers_customers",
        "Contratti di joint venture, ricerca e sviluppo, partnership e "
        "accordi quadro.",
        "Joint venture, R&D, partnership and master agreements.",
        ["joint venture", "ricerca e sviluppo", "partnership agreement",
         "accordo quadro"],
        Priority.medium,
    ),
    _item(
        "G.7", "G", "suppliers_customers",
        "Contratti di appalto, subfornitura, logistica e consulenza, con "
        "indicazione del valore e della durata di ciascun contratto.",
        "Contracting, sub-supply, logistics and consulting agreements, "
        "including the value and duration of each agreement.",
        ["contratto di appalto", "subfornitura", "logistica",
         "consulting agreement"],
        Priority.medium,
    ),
    _item(
        "G.8", "G", "suppliers_customers",
        "Contratti con pubbliche amministrazioni e partecipazione ad "
        "appalti pubblici, con indicazione di eventuali contestazioni, "
        "penali o risoluzioni.",
        "Public administration contracts and participation in public "
        "tenders, with any disputes, penalties or terminations.",
        ["pubblica amministrazione", "appalto pubblico", "public procurement",
         "public tender"],
        Priority.medium,
    ),
    _item(
        "G.9", "G", "suppliers_customers",
        "Elenco dei contratti in corso di negoziazione o suscettibili di "
        "cessazione con preavviso pari o inferiore a 6 mesi; indicazione "
        "di inadempimenti o circostanze che potrebbero giustificare "
        "risoluzioni o richieste risarcitorie.",
        "List of agreements under negotiation or terminable with 6 months' "
        "notice or less; indication of breaches or circumstances that "
        "could justify terminations or damages claims.",
        ["contratto in negoziazione", "preavviso di recesso",
         "contract under negotiation"],
        Priority.low,
    ),
    _item(
        "G.10", "G", "suppliers_customers",
        "Accordi di riservatezza rilevanti in essere.",
        "Material non-disclosure agreements in place.",
        ["accordo di riservatezza", "nda ", "non-disclosure agreement"],
        Priority.low,
    ),
    _item(
        "G.11", "G", "suppliers_customers",
        "Responsabilità da prodotto: reclami significativi, campagne di "
        "richiamo e difetti seriali degli ultimi 3 anni.",
        "Product liability: material complaints, recalls and serial "
        "defects over the last 3 years.",
        ["responsabilità da prodotto", "richiamo prodotto",
         "product liability", "product recall"],
        Priority.medium,
    ),
    # ── H. Assicurazioni ─────────────────────────────────────────────────
    _item(
        "H.1", "H", "insurance",
        "Elenco di tutte le polizze assicurative (incluse polizze D&O e "
        "cyber), con indicazione di compagnia, rischi coperti, massimali, "
        "franchigie, scadenza e premio annuo.",
        "List of all insurance policies (including D&O and cyber), with "
        "insurer, covered risks, limits, deductibles, expiry and annual "
        "premium.",
        ["polizza assicurativa", "polizza d&o", "polizza cyber",
         "insurance policy"],
        Priority.high,
    ),
    _item(
        "H.2", "H", "insurance",
        "Elenco dei sinistri pendenti o definiti negli ultimi 3 anni, con "
        "indicazione del valore di ciascun sinistro; denunce tardive o "
        "contestazioni di copertura da parte degli assicuratori.",
        "List of claims pending or settled over the last 3 years, including "
        "the value of each claim; late notifications or coverage disputes "
        "from insurers.",
        ["sinistro", "denuncia sinistro", "insurance claim"],
        Priority.medium,
    ),
    # ── I. Contenzioso ───────────────────────────────────────────────────
    _item(
        "I.1", "I", "litigation",
        "Elenco, con breve descrizione (ove possibile a cura del legale "
        "incaricato), di tutti i contenziosi pendenti (civili, penali, "
        "amministrativi, tributari, giuslavoristici e arbitrali) che "
        "coinvolgono la Società o i suoi amministratori in relazione alla "
        "carica, con indicazione di parti, petitum, valore, stato del "
        "procedimento, fondi rischi stanziati e coperture assicurative.",
        "List, with a short description, of all pending litigation "
        "(civil, criminal, administrative, tax, labour and arbitration) "
        "involving the Company or its directors in connection with their "
        "office, with parties, claim, value, stage, provisions and "
        "insurance coverage.",
        ["elenco contenziosi", "pending litigation",
         "litigation list"],
        Priority.high,
    ),
    _item(
        "I.2", "I", "litigation",
        "Contenziosi minacciati o probabili; lettere di diffida ricevute "
        "o inviate negli ultimi 3 anni.",
        "Threatened or probable litigation; cease-and-desist letters "
        "received or sent over the last 3 years.",
        ["contenzios minacciat", "lettera di diffida", "cease and desist",
         "demand letter"],
        Priority.high,
    ),
    _item(
        "I.3", "I", "litigation",
        "Transazioni e accordi conciliativi conclusi negli ultimi 5 anni, "
        "con indicazione degli obblighi ancora in essere.",
        "Settlement and conciliation agreements signed over the last 5 "
        "years, with surviving obligations.",
        ["transazione", "accordo conciliativo", "settlement agreement"],
        Priority.medium,
    ),
    _item(
        "I.4", "I", "litigation",
        "Indagini, ispezioni o procedimenti promossi da autorità di "
        "vigilanza o amministrative non già indicati in altre sezioni.",
        "Investigations, inspections or proceedings by supervisory or "
        "administrative authorities not already covered in other sections.",
        ["indagine", "ispezione", "procedimento amministrativo",
         "regulatory investigation"],
        Priority.medium,
    ),
    # ── J. Concorrenza ───────────────────────────────────────────────────
    _item(
        "J.1", "J", "other",
        "Stima delle quote di mercato della Società per gruppo di "
        "prodotto/servizio e per ambito geografico (regionale, nazionale, "
        "europeo, globale), con indicazione dei casi in cui la quota "
        "superi il 30%.",
        "Estimated Company market shares by product/service group and "
        "geography (regional, national, European, global), highlighting "
        "instances where the share exceeds 30%.",
        ["quota di mercato", "market share"],
        Priority.medium,
    ),
    _item(
        "J.2", "J", "other",
        "Indicazione dei principali concorrenti, con stima delle relative "
        "quote di mercato, e descrizione delle barriere all'ingresso nel "
        "settore.",
        "Main competitors, with estimated market shares, and entry "
        "barriers to the sector.",
        ["concorrenti", "barriere all'ingresso", "competitors"],
        Priority.low,
    ),
    _item(
        "J.3", "J", "other",
        "Contratti con concorrenti e intese, anche verticali, che "
        "comportino restrizioni della concorrenza (esclusive, limitazioni "
        "territoriali o di settore, prezzi imposti).",
        "Agreements with competitors and vertical arrangements involving "
        "restrictions of competition (exclusivity, territorial or sector "
        "limitations, resale price maintenance).",
        ["contratto con concorrenti", "intesa restrittiva",
         "antitrust agreement"],
        Priority.medium,
    ),
    _item(
        "J.4", "J", "other",
        "Informazioni sulla partecipazione a gare in raggruppamenti "
        "temporanei o consorzi e sui criteri di selezione delle gare.",
        "Information on participation in tenders through temporary "
        "groupings or consortia and tender selection criteria.",
        ["raggruppamento temporaneo", "rti", "consorzio", "consortium"],
        Priority.low,
    ),
    _item(
        "J.5", "J", "other",
        "Documentazione relativa a procedimenti, indagini, programmi di "
        "clemenza o altri rapporti con l'AGCM e la Commissione europea "
        "negli ultimi 5 anni; aiuti di Stato ricevuti.",
        "Documentation on proceedings, investigations, leniency programmes "
        "or other dealings with AGCM and the European Commission over the "
        "last 5 years; State aid received.",
        ["agcm", "antitrust authority", "leniency"],
        Priority.medium,
    ),
    # ── K. Golden Power ──────────────────────────────────────────────────
    _item(
        "K.1", "K", "other",
        "Indicazione se la Società svolge attività o detiene attivi "
        "rilevanti ai sensi del D.L. 21/2012 (settori difesa e sicurezza "
        "nazionale, energia, trasporti, comunicazioni, 5G e cloud, "
        "tecnologie critiche, salute, agroalimentare, finanziario), anche "
        "ai fini della valutazione degli obblighi di notifica "
        "dell'operazione.",
        "Indication whether the Company carries out activities or holds "
        "relevant assets under Decree-Law 21/2012 (defence, energy, "
        "transport, communications, 5G and cloud, critical technologies, "
        "healthcare, food, financial), also to assess transaction "
        "notification duties.",
        ["golden power", "d.l. 21/2012", "settori strategici",
         "strategic assets"],
        Priority.high,
    ),
    _item(
        "K.2", "K", "other",
        "Notifiche golden power effettuate o valutate in passato; "
        "provvedimenti, prescrizioni o interlocuzioni con la Presidenza "
        "del Consiglio dei Ministri; eventuali procedimenti FDI in altre "
        "giurisdizioni.",
        "Past golden-power notifications or assessments; measures, "
        "conditions or interactions with the Italian Government; FDI "
        "proceedings in other jurisdictions.",
        ["notifica golden power", "presidenza del consiglio", "fdi screening"],
        Priority.medium,
    ),
    # ── L. Proprietà intellettuale ───────────────────────────────────────
    _item(
        "L.1", "L", "ip_it",
        "Elenco dei brevetti della Società, o di terzi utilizzati dalla "
        "Società, con numero e data di domanda e registrazione, status, "
        "inventore, paesi di estensione e relativa documentazione.",
        "List of the Company's or third-party patents used by the "
        "Company, with application/registration number and date, status, "
        "inventor, jurisdictions of extension and related documentation.",
        ["brevetto", "patent", "domanda di brevetto"],
        Priority.high,
    ),
    _item(
        "L.2", "L", "ip_it",
        "Elenco e descrizione dei disegni e modelli registrati o di fatto.",
        "List and description of registered or de facto designs and "
        "models.",
        ["disegno registrato", "modello registrato", "registered design"],
        Priority.low,
    ),
    _item(
        "L.3", "L", "ip_it",
        "Elenco dei marchi registrati e di fatto, con dati di "
        "deposito/registrazione, status e paesi; elenco dei nomi a dominio "
        "della Società o di terzi utilizzati dalla Società.",
        "List of registered and de facto trademarks, with filing/"
        "registration data, status and jurisdictions; list of domain names "
        "owned by the Company or used by it.",
        ["marchio", "trademark", "nome a dominio", "domain name"],
        Priority.high,
    ),
    _item(
        "L.4", "L", "ip_it",
        "Elenco delle opere protette da diritto d'autore e del software "
        "proprietario, con indicazione di autore, data di creazione e "
        "titolarità (sviluppo interno o commissionato a terzi).",
        "List of copyrighted works and proprietary software, with author, "
        "creation date and ownership (in-house or commissioned to third "
        "parties).",
        ["diritto d'autore", "software proprietario", "copyright",
         "proprietary software"],
        Priority.medium,
    ),
    _item(
        "L.5", "L", "ip_it",
        "Descrizione di know-how e segreti commerciali e delle misure "
        "adottate per la loro protezione ai sensi degli artt. 98 e 99 del "
        "Codice della Proprietà Industriale, con indicazione di eventuali "
        "violazioni note.",
        "Description of know-how and trade secrets and the measures "
        "adopted for their protection under arts. 98 and 99 of the Italian "
        "Industrial Property Code, with any known violations.",
        ["know-how", "segreto commerciale", "trade secret"],
        Priority.medium,
    ),
    _item(
        "L.6", "L", "ip_it",
        "Contratti di licenza, attivi e passivi, relativi a diritti di "
        "proprietà industriale e intellettuale, incluse licenze di "
        "know-how e di software.",
        "Inbound and outbound licence agreements on industrial and "
        "intellectual property rights, including know-how and software "
        "licences.",
        ["contratto di licenza", "license agreement",
         "licenza software", "software license"],
        Priority.medium,
    ),
    _item(
        "L.7", "L", "ip_it",
        "Accordi con dipendenti e consulenti sulla titolarità delle "
        "invenzioni e delle opere; atti di cessione di diritti IP da "
        "fondatori, soci o terzi.",
        "Agreements with employees and consultants on ownership of "
        "inventions and works; IP assignment deeds from founders, "
        "shareholders or third parties.",
        ["cessione di diritti ip", "ip assignment",
         "titolarità delle invenzioni"],
        Priority.medium,
    ),
    _item(
        "L.8", "L", "ip_it",
        "Contestazioni, opposizioni, diffide e contenziosi in materia IP, "
        "attivi o passivi.",
        "IP claims, oppositions, cease-and-desist letters and litigation, "
        "inbound or outbound.",
        ["contenzios ip", "opposizione marchio", "ip litigation"],
        Priority.medium,
    ),
    # ── M. IT e cybersecurity ────────────────────────────────────────────
    _item(
        "M.1", "M", "ip_it",
        "Descrizione dei sistemi informativi (hardware e software, "
        "distinti tra prodotti standard e personalizzati), contratti di "
        "manutenzione e assistenza, licenze software in uso e servizi "
        "cloud/SaaS utilizzati.",
        "Description of IT systems (hardware and software, distinguishing "
        "between off-the-shelf and customised products), maintenance and "
        "support agreements, software licences in use and cloud/SaaS "
        "services used.",
        ["sistemi informativi", "contratto di manutenzione", "saas",
         "cloud services"],
        Priority.medium,
    ),
    _item(
        "M.2", "M", "ip_it",
        "Indicazione del software open source incorporato in prodotti o "
        "servizi della Società e delle relative licenze.",
        "Open-source software embedded in the Company's products or "
        "services and the relevant licences.",
        ["open source", "software open source"],
        Priority.medium,
    ),
    _item(
        "M.3", "M", "ip_it",
        "Policy e misure di sicurezza informatica; piani di business "
        "continuity e disaster recovery.",
        "IT security policies and measures; business continuity and "
        "disaster recovery plans.",
        ["business continuity", "disaster recovery",
         "policy di sicurezza", "security policy"],
        Priority.medium,
    ),
    _item(
        "M.4", "M", "ip_it",
        "Incidenti informatici significativi degli ultimi 3 anni; "
        "valutazione di applicabilità della disciplina NIS2 "
        "(D.Lgs. 138/2024) e relativi adempimenti (rinvio alla Sezione H "
        "per le coperture cyber).",
        "Material cyber incidents over the last 3 years; assessment of "
        "applicability of NIS2 (Legislative Decree 138/2024) and related "
        "compliance (reference to Section H for cyber coverage).",
        ["incidente informatico", "nis2", "d.lgs. 138/2024", "cyber incident"],
        Priority.medium,
    ),
    # ── N. Privacy ───────────────────────────────────────────────────────
    _item(
        "N.1", "N", "data_protection",
        "Registro delle attività di trattamento, in qualità di titolare e "
        "di responsabile (art. 30 GDPR).",
        "Records of processing activities, as controller and processor "
        "(art. 30 GDPR).",
        ["registro dei trattamenti", "registro delle attività di trattamento",
         "art. 30 gdpr"],
        Priority.high,
    ),
    _item(
        "N.2", "N", "data_protection",
        "Informative rese a dipendenti, clienti, fornitori e altri "
        "interessati; informativa e cookie policy del sito web.",
        "Privacy notices to employees, customers, suppliers and other "
        "data subjects; website privacy notice and cookie policy.",
        ["informativa privacy", "cookie policy", "privacy notice"],
        Priority.medium,
    ),
    _item(
        "N.3", "N", "data_protection",
        "Indicazione delle basi giuridiche dei trattamenti; consensi per "
        "finalità di marketing e profilazione e relative evidenze di "
        "raccolta.",
        "Legal bases of processing; consents for marketing and profiling "
        "and the related collection evidence.",
        ["base giuridica", "consenso al trattamento", "marketing consent"],
        Priority.medium,
    ),
    _item(
        "N.4", "N", "data_protection",
        "Atto di designazione del DPO e relativa comunicazione al Garante, "
        "ovvero valutazione documentata di non obbligatorietà della "
        "nomina; designazioni degli autorizzati e degli amministratori di "
        "sistema.",
        "DPO appointment deed and notification to the Italian DPA, or "
        "documented assessment of non-mandatory appointment; designation "
        "of authorised personnel and system administrators.",
        ["nomina dpo", "designazione dpo", "data protection officer",
         "amministratore di sistema"],
        Priority.high,
    ),
    _item(
        "N.5", "N", "data_protection",
        "Accordi ex art. 28 GDPR con responsabili e sub-responsabili del "
        "trattamento; elenco dei fornitori che trattano dati personali per "
        "conto della Società.",
        "Art. 28 GDPR agreements with processors and sub-processors; list "
        "of suppliers processing personal data on behalf of the Company.",
        ["art. 28 gdpr", "responsabile del trattamento", "data processing agreement",
         "dpa"],
        Priority.medium,
    ),
    _item(
        "N.6", "N", "data_protection",
        "Trasferimenti di dati extra-UE: meccanismi utilizzati (clausole "
        "contrattuali standard, decisioni di adeguatezza) e relative "
        "valutazioni di impatto sul trasferimento (TIA).",
        "Non-EU data transfers: mechanisms used (standard contractual "
        "clauses, adequacy decisions) and related transfer impact "
        "assessments (TIA).",
        ["trasferimento dati extra-ue", "clausole contrattuali standard",
         "tia ", "standard contractual clauses"],
        Priority.medium,
    ),
    _item(
        "N.7", "N", "data_protection",
        "Valutazioni d'impatto (DPIA) effettuate; valutazioni del "
        "legittimo interesse (LIA), ove applicabili.",
        "Data Protection Impact Assessments (DPIAs) conducted; legitimate "
        "interest assessments (LIAs), where applicable.",
        ["dpia", "data protection impact assessment", "lia ",
         "legitimate interest assessment"],
        Priority.medium,
    ),
    _item(
        "N.8", "N", "data_protection",
        "Procedure di gestione delle violazioni di dati personali e "
        "relativo registro; notifiche al Garante e comunicazioni agli "
        "interessati negli ultimi 3 anni.",
        "Personal data breach management procedures and breach register; "
        "notifications to the Italian DPA and to data subjects over the "
        "last 3 years.",
        ["data breach", "violazione dei dati", "registro dei data breach"],
        Priority.medium,
    ),
    _item(
        "N.9", "N", "data_protection",
        "Procedure di gestione delle richieste di esercizio dei diritti "
        "degli interessati e richieste ricevute negli ultimi 3 anni.",
        "Procedures to handle data subject access requests and requests "
        "received over the last 3 years.",
        ["diritti degli interessati", "data subject rights",
         "richiesta accesso"],
        Priority.low,
    ),
    _item(
        "N.10", "N", "data_protection",
        "Ispezioni, provvedimenti e sanzioni del Garante; impianti di "
        "videosorveglianza e altri strumenti di controllo a distanza, con "
        "i relativi accordi sindacali o autorizzazioni dell'Ispettorato ex "
        "art. 4 dello Statuto dei Lavoratori.",
        "Italian DPA inspections, measures and penalties; CCTV and other "
        "remote-monitoring tools, with the related trade-union agreements "
        "or Labour Inspectorate authorisations under art. 4 of the Workers' "
        "Statute.",
        ["videosorveglianza", "controllo a distanza", "art. 4 statuto",
         "cctv"],
        Priority.low,
    ),
    # ── O. Compliance ────────────────────────────────────────────────────
    _item(
        "O.1", "O", "other",
        "Modello di organizzazione e gestione ex D.Lgs. 231/2001 e codice "
        "etico, con mappatura dei reati presupposto; verbali "
        "dell'Organismo di Vigilanza degli ultimi 3 anni.",
        "Organisation and management model under Legislative Decree "
        "231/2001 and code of ethics, with mapping of predicate offences; "
        "minutes of the Supervisory Body over the last 3 years.",
        ["modello 231", "d.lgs. 231/2001", "organismo di vigilanza",
         "codice etico"],
        Priority.high,
    ),
    _item(
        "O.2", "O", "other",
        "Descrizione dell'assetto di compliance: responsabile, linee di "
        "riporto verso gli organi sociali, risk assessment effettuati e "
        "relativi esiti.",
        "Description of the compliance set-up: head of compliance, "
        "reporting lines to corporate bodies, risk assessments performed "
        "and outcomes.",
        ["compliance officer", "risk assessment", "assetto di compliance"],
        Priority.medium,
    ),
    _item(
        "O.3", "O", "other",
        "Policy in materia di anticorruzione, omaggi e intrattenimento, "
        "donazioni e sponsorizzazioni; programmi di formazione del "
        "personale e relativi destinatari.",
        "Policies on anti-bribery, gifts and entertainment, donations "
        "and sponsorships; training programmes for staff and "
        "participants.",
        ["anticorruzione", "anti-bribery", "policy omaggi"],
        Priority.medium,
    ),
    _item(
        "O.4", "O", "other",
        "Canale di segnalazione whistleblowing ex D.Lgs. 24/2023: "
        "procedura adottata, soggetto gestore e segnalazioni ricevute "
        "negli ultimi 3 anni.",
        "Whistleblowing channel under Legislative Decree 24/2023: "
        "procedure adopted, manager and reports received over the last 3 "
        "years.",
        ["whistleblowing", "d.lgs. 24/2023", "segnalazione illeciti"],
        Priority.medium,
    ),
    _item(
        "O.5", "O", "other",
        "Adempimenti in materia di antiriciclaggio ex D.Lgs. 231/2007, "
        "ove applicabile.",
        "AML compliance under Legislative Decree 231/2007, where "
        "applicable.",
        ["antiriciclaggio", "aml", "d.lgs. 231/2007"],
        Priority.low,
    ),
    _item(
        "O.6", "O", "other",
        "Policy e procedure in materia di sanzioni internazionali ed "
        "export control; operazioni con controparti o paesi soggetti a "
        "misure restrittive.",
        "Policies and procedures on international sanctions and export "
        "controls; transactions with counterparties or countries subject "
        "to restrictive measures.",
        ["sanzioni internazionali", "export control",
         "international sanctions"],
        Priority.medium,
    ),
    _item(
        "O.7", "O", "other",
        "Indicazione di violazioni note o sospette della normativa "
        "applicabile e di procedimenti sanzionatori in corso o conclusi "
        "negli ultimi 5 anni.",
        "Known or suspected breaches of applicable law and sanctioning "
        "proceedings, pending or concluded, over the last 5 years.",
        ["violazione normativa", "procedimento sanzionatorio",
         "regulatory breach"],
        Priority.medium,
    ),
    # ── P. ESG e sostenibilità ───────────────────────────────────────────
    _item(
        "P.1", "P", "other",
        "Politiche e iniziative in materia di tutela dell'ambiente e del "
        "clima e di efficienza energetica (rinvio alla Sezione F per i "
        "profili autorizzativi); audit energetici e KPI di consumo.",
        "Environmental, climate and energy-efficiency policies and "
        "initiatives (reference to Section F for authorisations); energy "
        "audits and consumption KPIs.",
        ["politica ambientale", "efficienza energetica",
         "audit energetico"],
        Priority.low,
    ),
    _item(
        "P.2", "P", "other",
        "Valutazione di assoggettabilità agli obblighi di rendicontazione "
        "di sostenibilità (CSRD – D.Lgs. 125/2024) e copia delle "
        "rendicontazioni eventualmente pubblicate.",
        "Assessment of applicability of sustainability reporting "
        "obligations (CSRD – Legislative Decree 125/2024) and copies of "
        "any published reports.",
        ["csrd", "d.lgs. 125/2024", "rendicontazione di sostenibilità"],
        Priority.low,
    ),
    _item(
        "P.3", "P", "other",
        "Politiche in materia di parità di genere e pari opportunità "
        "(inclusa eventuale certificazione UNI/PdR 125:2022); reclami o "
        "contenziosi per discriminazione negli ultimi 3 anni.",
        "Gender equality and equal-opportunity policies (including any "
        "UNI/PdR 125:2022 certification); discrimination complaints or "
        "litigation over the last 3 years.",
        ["parità di genere", "pari opportunità", "uni/pdr 125",
         "gender equality"],
        Priority.low,
    ),
    _item(
        "P.4", "P", "other",
        "Due diligence sulla catena di fornitura: codici di condotta per "
        "i fornitori, audit svolti e relativi esiti.",
        "Supply-chain due diligence: supplier codes of conduct, audits "
        "performed and outcomes.",
        ["catena di fornitura", "codice di condotta", "supply chain audit"],
        Priority.low,
    ),
    # ── Q. Fiscale (richiamo) ────────────────────────────────────────────
    _item(
        "Q.1", "Q", "other",
        "Dichiarazioni fiscali degli ultimi 5 anni (richiamo, in "
        "coordinamento con la due diligence fiscale).",
        "Tax returns for the last 5 years (reference, in coordination "
        "with tax DD).",
        ["dichiarazione fiscale", "modello unico", "tax return"],
        Priority.medium,
    ),
    _item(
        "Q.2", "Q", "other",
        "Verifiche, accessi, processi verbali di constatazione, avvisi di "
        "accertamento e contenzioso tributario, pendenti o definiti negli "
        "ultimi 5 anni.",
        "Tax audits, on-site inspections, audit findings reports, "
        "assessment notices and tax litigation, pending or settled over "
        "the last 5 years.",
        ["avviso di accertamento", "processo verbale di constatazione",
         "contenzios tributario"],
        Priority.medium,
    ),
    _item(
        "Q.3", "Q", "other",
        "Interpelli, ruling, adesione a regimi opzionali (consolidato "
        "fiscale, IVA di gruppo, patent box) e documentazione in materia "
        "di transfer pricing.",
        "Tax rulings, opt-ins to optional regimes (tax consolidation, "
        "group VAT, patent box) and transfer pricing documentation.",
        ["interpello", "consolidato fiscale", "patent box",
         "transfer pricing"],
        Priority.low,
    ),
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
