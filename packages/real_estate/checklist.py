"""Documents a buyer should receive before purchasing an Italian residential property.

Same shape and API as Diligenx's M&A checklist (``ChecklistItem``,
``SECTIONS_ORDER``, ``SECTION_NAMES``, ``items_by_key``, ``matched_keys``),
so the intake stage and the report's Information Requests section work
unchanged. Each item is matched against the document's file name plus the
first 1 000 characters of its text; every item that no document matches
becomes a ``MissingDocument`` row and an information request in the report.

Keywords are matched at a word start (``(?<![a-z])``), so a stem such as
"condon" matches "condono" and "condoni"; keywords of four characters or
fewer must match a whole word, so "ape" does not match "apertura" nor
"scia" match "lascia".
"""
from __future__ import annotations

import re
from functools import lru_cache
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


SECTIONS_ORDER: list[str] = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]

SECTION_NAMES: dict[str, dict[str, str]] = {
    "A": {"it": "Provenienza", "en": "Title and chain of ownership"},
    "B": {"it": "Situazione ipotecaria", "en": "Mortgage registry"},
    "C": {"it": "Catasto", "en": "Cadastral records"},
    "D": {"it": "Urbanistica ed edilizia", "en": "Planning and building"},
    "E": {"it": "Condominio", "en": "Condominium"},
    "F": {"it": "Impianti ed energia", "en": "Installations and energy"},
    "G": {"it": "Stato di occupazione", "en": "Occupancy"},
    "H": {"it": "Parte venditrice", "en": "Seller"},
    "I": {"it": "Operazione", "en": "Transaction"},
}


def _item(key, section, area, request_it, request_en, keywords, priority) -> ChecklistItem:
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


CHECKLIST: list[ChecklistItem] = [
    # ── A. Provenienza ───────────────────────────────────────────────────
    _item(
        "A.1", "A", "title_chain",
        "Copia dell'atto di provenienza a favore della parte venditrice "
        "(compravendita, donazione, divisione, permuta o decreto di trasferimento), "
        "con la nota di trascrizione.",
        "Copy of the deed by which the seller acquired the property (sale, "
        "donation, division, exchange or transfer decree), with its transcription note.",
        ["atto di provenienza", "atto di compravendita", "atto di donazione",
         "atto di divisione", "atto di permuta", "decreto di trasferimento"],
        Priority.high,
    ),
    _item(
        "A.2", "A", "title_chain",
        "Atti di provenienza precedenti fino a coprire almeno il ventennio "
        "anteriore alla data prevista per il rogito, oppure relazione notarile "
        "ventennale.",
        "Earlier title deeds covering at least the twenty years before the "
        "expected date of the deed, or a notarial twenty-year report.",
        ["relazione notarile", "certificazione notarile", "certificato notarile",
         "relazione ventennale", "ventennio"],
        Priority.high,
    ),
    _item(
        "A.3", "A", "title_chain",
        "Ove l'immobile sia pervenuto per successione: dichiarazione di successione, "
        "atto di accettazione dell'eredità e relativa trascrizione.",
        "Where the property was inherited: declaration of succession, deed of "
        "acceptance of the inheritance and its transcription.",
        ["dichiarazione di successione", "certificato di successione", "accettazione dell'eredità",
         "accettazione di eredità", "accettazione tacita", "testamento"],
        Priority.medium,
    ),
    # ── B. Situazione ipotecaria ─────────────────────────────────────────
    _item(
        "B.1", "B", "encumbrances",
        "Ispezione ipotecaria aggiornata a nome della parte venditrice e dei danti "
        "causa del ventennio (elenco sintetico delle formalità e note).",
        "Up-to-date mortgage-registry search against the seller and the previous "
        "owners of the last twenty years (list of entries and notes).",
        ["ispezione ipotecaria", "visura ipotecaria", "elenco sintetico delle formalità",
         "ispezione ordinaria", "ispezione telematica"],
        Priority.high,
    ),
    _item(
        "B.2", "B", "encumbrances",
        "Per ogni ipoteca in essere: contratto di mutuo, conteggio estintivo "
        "della banca e impegno alla cancellazione contestuale al rogito.",
        "For each outstanding mortgage: loan agreement, the bank's payoff "
        "statement and the undertaking to cancel it at the deed.",
        ["contratto di mutuo", "atto di mutuo", "conteggio estintivo",
         "cancellazione dell'ipoteca", "cancellazione ipoteca", "estinzione del mutuo"],
        Priority.medium,
    ),
    # ── C. Catasto ───────────────────────────────────────────────────────
    _item(
        "C.1", "C", "cadastral",
        "Visura catastale storica dell'immobile e delle pertinenze.",
        "Historical cadastral extract of the property and its appurtenances.",
        ["visura catastale", "visura storica", "visura per immobile",
         "catasto fabbricati", "catasto terreni", "dati catastali"],
        Priority.high,
    ),
    _item(
        "C.2", "C", "cadastral",
        "Planimetria catastale in atti, per l'immobile e per ciascuna pertinenza.",
        "Cadastral floor plan on file, for the property and each appurtenance.",
        ["planimetria"],
        Priority.high,
    ),
    _item(
        "C.3", "C", "cadastral",
        "Elaborato planimetrico ed estratto di mappa, ove l'edificio ne sia dotato.",
        "Site plan (elaborato planimetrico) and cadastral map extract, where available.",
        ["elaborato planimetrico", "estratto di mappa", "mappa catastale"],
        Priority.low,
    ),
    # ── D. Urbanistica ed edilizia ───────────────────────────────────────
    _item(
        "D.1", "D", "building_compliance",
        "Titoli edilizi dell'edificio e dell'unità (licenza o concessione edilizia, "
        "permesso di costruire, DIA, SCIA, CILA) con gli elaborati grafici "
        "assentiti, oppure dichiarazione che la costruzione è iniziata prima del "
        "1° settembre 1967.",
        "Building permits for the building and the unit (licence, concession, "
        "building permit, DIA, SCIA, CILA) with the approved drawings, or a "
        "statement that construction began before 1 September 1967.",
        ["licenza edilizia", "concessione edilizia", "permesso di costruire",
         "titolo edilizio", "pratica edilizia", "denuncia di inizio attività",
         "dia", "scia", "cila", "segnalazione certificata di inizio attività",
         "comunicazione di inizio lavori", "1° settembre 1967", "ante 1967"],
        Priority.high,
    ),
    _item(
        "D.2", "D", "building_compliance",
        "Pratiche di condono o di sanatoria, con il relativo provvedimento di "
        "rilascio o lo stato della domanda.",
        "Amnesty (condono) or regularisation filings, with the decision granting "
        "them or the status of the application.",
        ["condon", "sanatoria", "accertamento di conformità", "permesso in sanatoria"],
        Priority.medium,
    ),
    _item(
        "D.3", "D", "building_compliance",
        "Certificato di agibilità (o abitabilità) oppure segnalazione certificata "
        "per l'agibilità.",
        "Certificate of habitability, or the certified filing for habitability.",
        ["agibilità", "abitabilità", "agibilita", "abitabilita"],
        Priority.high,
    ),
    _item(
        "D.4", "D", "building_compliance",
        "Certificato di destinazione urbanistica, ove la vendita comprenda terreni "
        "non pertinenziali.",
        "Certificate of urban-planning use, where the sale includes land that is "
        "not an appurtenance.",
        ["certificato di destinazione urbanistica", "destinazione urbanistica", "cdu"],
        Priority.low,
    ),
    # ── E. Condominio ────────────────────────────────────────────────────
    _item(
        "E.1", "E", "condominium",
        "Regolamento di condominio con le tabelle millesimali.",
        "Condominium by-laws with the ownership tables.",
        ["regolamento di condominio", "regolamento condominiale",
         "tabelle millesimali", "tabella millesimale"],
        Priority.medium,
    ),
    _item(
        "E.2", "E", "condominium",
        "Verbali delle assemblee condominiali degli ultimi due anni, con evidenza "
        "dei lavori straordinari deliberati.",
        "Minutes of the condominium meetings of the last two years, showing any "
        "extraordinary works approved.",
        ["verbale di assemblea", "verbale dell'assemblea", "verbale assemblea",
         "assemblea condominiale", "assemblea ordinaria", "assemblea straordinaria"],
        Priority.medium,
    ),
    _item(
        "E.3", "E", "condominium",
        "Dichiarazione dell'amministratore sullo stato dei pagamenti della parte "
        "venditrice, sulle spese deliberate e sulle liti pendenti.",
        "The administrator's statement of the seller's payments, of the expenses "
        "approved and of pending disputes.",
        ["dichiarazione dell'amministratore", "stato dei pagamenti", "liberatoria",
         "situazione contabile", "morosità", "consuntivo", "preventivo", "rendiconto"],
        Priority.medium,
    ),
    # ── F. Impianti ed energia ───────────────────────────────────────────
    _item(
        "F.1", "F", "installations_energy",
        "Attestato di prestazione energetica in corso di validità.",
        "Valid energy performance certificate.",
        ["attestato di prestazione energetica", "prestazione energetica", "ape",
         "a.p.e.", "classe energetica", "attestato di certificazione energetica"],
        Priority.medium,
    ),
    _item(
        "F.2", "F", "installations_energy",
        "Dichiarazioni di conformità o di rispondenza degli impianti (D.M. 37/2008) "
        "e libretto dell'impianto termico.",
        "Declarations of conformity or of compliance of the installations "
        "(Ministerial Decree 37/2008) and the heating system logbook.",
        ["dichiarazione di conformità", "dichiarazione di rispondenza",
         "37/2008", "libretto di impianto", "libretto dell'impianto"],
        Priority.medium,
    ),
    # ── G. Stato di occupazione ──────────────────────────────────────────
    _item(
        "G.1", "G", "occupancy",
        "Contratti di locazione o di comodato in essere sull'immobile, con gli "
        "estremi di registrazione.",
        "Leases or loan-for-use contracts in force on the property, with their "
        "registration details.",
        ["contratto di locazione", "contratto di comodato", "canone di locazione"],
        Priority.medium,
    ),
    _item(
        "G.2", "G", "occupancy",
        "Dichiarazione della parte venditrice sullo stato di occupazione "
        "dell'immobile alla data del rogito.",
        "The seller's statement on whether the property will be vacant at the deed.",
        ["stato di occupazione", "libero da persone", "immobile libero"],
        Priority.low,
    ),
    # ── H. Parte venditrice ──────────────────────────────────────────────
    _item(
        "H.1", "H", "title_chain",
        "Documento d'identità e codice fiscale di ciascun venditore.",
        "Identity document and tax code of each seller.",
        ["carta d'identità", "carta di identità", "documento d'identità",
         "documento di identità", "passaporto"],
        Priority.low,
    ),
    _item(
        "H.2", "H", "title_chain",
        "Estratto per riassunto dell'atto di matrimonio con le annotazioni, o "
        "certificato di stato civile, di ciascun venditore persona fisica.",
        "Marriage certificate extract with its annotations, or civil-status "
        "certificate, of each individual seller.",
        ["estratto per riassunto", "estratto dell'atto di matrimonio", "estratto di matrimonio",
         "certificato di stato civile", "certificato di stato libero",
         "convenzione matrimoniale"],
        Priority.medium,
    ),
    _item(
        "H.3", "H", "title_chain",
        "Procura, ove un venditore intervenga a mezzo di procuratore.",
        "Power of attorney, where a seller acts through an attorney.",
        ["procura speciale", "procura generale"],
        Priority.low,
    ),
    # ── I. Operazione ────────────────────────────────────────────────────
    _item(
        "I.1", "I", "other",
        "Proposta d'acquisto accettata o contratto preliminare.",
        "Accepted purchase offer or preliminary contract.",
        ["proposta di acquisto", "proposta d'acquisto", "contratto preliminare",
         "preliminare di compravendita", "compromesso"],
        Priority.low,
    ),
    _item(
        "I.2", "I", "other",
        "Perizia di stima (della banca o, per le vendite giudiziarie, del CTU) e "
        "avviso di vendita.",
        "Valuation report (the bank's or, for judicial sales, the court expert's) "
        "and notice of sale.",
        ["perizia", "relazione di stima", "consulenza tecnica d'ufficio", "ctu",
         "avviso di vendita"],
        Priority.low,
    ),
]


@lru_cache(maxsize=None)
def _pattern(keyword: str) -> re.Pattern:
    escaped = re.escape(keyword)
    if len(keyword) <= 4:
        return re.compile(rf"(?<![a-zà-ù]){escaped}(?![a-zà-ù])")
    return re.compile(rf"(?<![a-zà-ù]){escaped}")


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
        if any(_pattern(kw).search(needle) for kw in item["keywords"])
    }
