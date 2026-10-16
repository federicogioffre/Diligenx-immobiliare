"""Report areas of a real-estate due diligence, in report order.

Each key is a value of the ``dd_area`` enum (``app.models.red_flag.DueDiligenceArea``).
The M&A areas inherited from Diligenx stay in the enum for the stored data
but are neither offered to the model nor rendered in the report.
"""
from __future__ import annotations

AREA_ORDER: tuple[str, ...] = (
    "title_chain",
    "encumbrances",
    "cadastral",
    "building_compliance",
    "condominium",
    "installations_energy",
    "occupancy",
    "tax",
    "litigation",
    "other",
)

AREA_TITLES: dict[str, dict[str, str]] = {
    "en": {
        "title_chain": "Title and Chain of Ownership",
        "encumbrances": "Mortgages, Liens and Encumbrances",
        "cadastral": "Cadastral Records",
        "building_compliance": "Planning and Building Compliance",
        "condominium": "Condominium",
        "installations_energy": "Installations and Energy Performance",
        "occupancy": "Occupancy and Leases",
        "tax": "Tax",
        "litigation": "Litigation",
        "other": "Other Matters",
    },
    "it": {
        "title_chain": "Provenienza e Titolarità",
        "encumbrances": "Ipoteche, Trascrizioni Pregiudizievoli e Gravami",
        "cadastral": "Situazione Catastale",
        "building_compliance": "Conformità Urbanistico-Edilizia",
        "condominium": "Condominio",
        "installations_energy": "Impianti e Prestazione Energetica",
        "occupancy": "Stato di Occupazione e Locazioni",
        "tax": "Fiscale",
        "litigation": "Contenzioso",
        "other": "Altri Aspetti",
    },
}

#: One line per area for the aggregation prompt.
AREA_GUIDE = """  title_chain | encumbrances | cadastral | building_compliance | condominium | installations_energy | occupancy | tax | litigation | other
  • title_chain — the seller's title and the chain of deeds over the last twenty years: donations, successions and acceptance of the inheritance, the seller's marital property regime, powers of attorney.
  • encumbrances — mortgages (ipoteche), attachments and foreclosures (pignoramenti), seizures, transcribed claims (domande giudiziali), easements, fondo patrimoniale, transcribed preliminary contracts.
  • cadastral — cadastral identifiers, owners of record, category, floor plan, and their match with the deed and with the actual state.
  • building_compliance — building permits, amnesties (condoni) and regularisations, certificate of habitability (agibilità), irregular works, Superbonus works.
  • condominium — arrears, approved extraordinary works, by-law restrictions on use, condominium litigation.
  • installations_energy — energy performance certificate (APE), declarations of conformity of the installations.
  • occupancy — leases, loans for use (comodato), occupants without title.
  • tax — registration and transfer tax matters, first-home relief, tax liens on the property.
  • litigation — pending proceedings concerning the property or the seller."""

VALID_AREAS = frozenset(AREA_ORDER)


def parse_area(value: object):
    """Return the ``DueDiligenceArea`` for a raw model value, or None.

    A value outside this vertical's areas (an M&A area the model borrowed)
    becomes None, which the report files under "Other Matters".
    """
    from app.models.red_flag import DueDiligenceArea

    if isinstance(value, str):
        key = value.strip().lower()
        if key in VALID_AREAS:
            return DueDiligenceArea(key)
    return None
