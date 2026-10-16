"""Dated Italian rules relevant to a residential property purchase.

Same design as Diligenx's ``tax_rules_registry``: each rule is keyed by a
``rule_id`` and carries the citation, a short neutral gloss in Italian and
English, and the period it is in force — here by **date**, because property
rules change on the day a statute takes effect, not by fiscal year. The
deterministic helpers (``donation_exposure``, ``mortgage_registration_lapsed``,
``chain_coverage``) compute the time windows the specialists and the report
rely on, so the model never has to.

The registry deliberately carries **no amount**: no penalty, no tax rate, no
cost of a regularisation. Those depend on the municipality, the year and the
procedure, and pricing them belongs to the client's notary and technician.
A test asserts the glosses contain no percentage and no euro figure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

LAST_VERIFIED = date(2026, 10, 16)

#: Years after which a title chain is considered covered, and after which a
#: donation can no longer be reclaimed from a later buyer (art. 563 c.c.).
TWENTY_YEARS = 20


@dataclass(frozen=True)
class Rule:
    rule_id: str
    citation: str
    gloss_it: str
    gloss_en: str
    valid_from: date
    valid_to: date | None = None
    superseded_by: str | None = None
    last_verified: date = LAST_VERIFIED

    def applies_on(self, day: date) -> bool:
        if day < self.valid_from:
            return False
        return self.valid_to is None or day <= self.valid_to


RULES: dict[str, list[Rule]] = {
    "donation_restitution": [
        Rule(
            "donation_restitution",
            "Artt. 561 e 563 c.c., come modificati dal D.L. 35/2005 conv. L. 80/2005",
            "Entro vent'anni dalla trascrizione della donazione il legittimario leso, "
            "vittorioso nell'azione di riduzione, può chiedere la restituzione "
            "dell'immobile anche a chi lo ha acquistato dal donatario; il termine è "
            "sospeso dall'atto di opposizione notificato e trascritto dal coniuge o dai "
            "parenti in linea retta del donante. Per le donazioni trascritte prima del "
            "15 maggio 2005 si applica la disciplina transitoria del D.L. 35/2005.",
            "Within twenty years of the transcription of the donation, a forced heir "
            "who succeeds in an action for reduction may reclaim the property even from "
            "a buyer who acquired it from the donee; the term is suspended by a deed of "
            "opposition served and transcribed by the donor's spouse or relatives in the "
            "direct line. Donations transcribed before 15 May 2005 follow the transitional "
            "rules of Decree-Law 35/2005.",
            date(2005, 5, 15),
        ),
    ],
    "cadastral_conformity": [
        Rule(
            "cadastral_conformity",
            "Art. 29, comma 1-bis, L. 52/1985 (introdotto dal D.L. 78/2010 conv. L. 122/2010)",
            "L'atto di trasferimento di un fabbricato esistente deve contenere, a pena di "
            "nullità, l'identificazione catastale, il riferimento alla planimetria "
            "depositata e la dichiarazione degli intestatari che dati catastali e "
            "planimetria sono conformi allo stato di fatto; il notaio verifica che gli "
            "intestatari catastali coincidano con le risultanze dei registri immobiliari.",
            "A deed transferring an existing building must, on pain of nullity, state the "
            "cadastral identification, refer to the filed floor plan and contain the "
            "owners' declaration that the cadastral data and the floor plan match the "
            "actual state; the notary checks that the owners of record match the land "
            "registry.",
            date(2010, 7, 1),
        ),
    ],
    "building_title_mention": [
        Rule(
            "building_title_mention",
            "Art. 40 L. 47/1985",
            "L'atto di trasferimento deve indicare gli estremi della licenza o "
            "concessione edilizia, o della domanda di condono; per le opere iniziate "
            "prima del 1° settembre 1967 basta una dichiarazione sostitutiva.",
            "The deed of transfer must state the details of the building licence or "
            "concession, or of the amnesty application; for works begun before "
            "1 September 1967 a sworn statement is sufficient.",
            date(1985, 3, 17),
            date(2003, 6, 29),
            superseded_by="building_title_mention",
        ),
        Rule(
            "building_title_mention",
            "Art. 46 D.P.R. 380/2001 e art. 40 L. 47/1985 (Cass. S.U. 8230/2019)",
            "L'atto è nullo se non indica gli estremi di un titolo edilizio esistente e "
            "riferibile all'immobile; per le opere iniziate prima del 1° settembre 1967 "
            "basta una dichiarazione sostitutiva. La nullità è testuale: una difformità "
            "dal titolo non invalida l'atto, ma incide sul valore, sulla commerciabilità "
            "e sulla possibilità di sanatoria.",
            "The deed is void if it does not state the details of an existing building "
            "permit referable to the property; for works begun before 1 September 1967 a "
            "sworn statement is sufficient. The nullity is textual: a deviation from the "
            "permit does not void the deed, but it affects value, marketability and the "
            "possibility of regularisation.",
            date(2003, 6, 30),
        ),
    ],
    "condominium_arrears": [
        Rule(
            "condominium_arrears",
            "Art. 63, secondo comma, disp. att. c.c. (testo anteriore alla L. 220/2012)",
            "Chi subentra nei diritti di un condomino è obbligato in solido con questo al "
            "pagamento dei contributi relativi all'anno in corso e a quello precedente.",
            "Whoever acquires a unit is jointly liable with the seller for the "
            "contributions of the current year and of the previous one.",
            date(1942, 4, 21),
            date(2013, 6, 17),
            superseded_by="condominium_arrears",
        ),
        Rule(
            "condominium_arrears",
            "Art. 63, quarto e quinto comma, disp. att. c.c. (L. 220/2012)",
            "Chi subentra nei diritti di un condomino è obbligato in solido con questo al "
            "pagamento dei contributi relativi all'anno in corso e a quello precedente; "
            "chi cede resta obbligato in solido per i contributi maturati fino alla "
            "trasmissione all'amministratore di copia autentica del titolo.",
            "Whoever acquires a unit is jointly liable with the seller for the "
            "contributions of the current year and of the previous one; the seller "
            "remains jointly liable for contributions accrued until a certified copy of "
            "the deed is sent to the administrator.",
            date(2013, 6, 18),
        ),
    ],
    "mortgage_duration": [
        Rule(
            "mortgage_duration",
            "Artt. 2847 e 2850 c.c.; art. 40-bis D.Lgs. 385/1993",
            "L'iscrizione ipotecaria conserva effetto per vent'anni dalla sua data e "
            "cessa se non è rinnovata prima della scadenza. L'ipoteca a garanzia di un "
            "mutuo bancario estinto si cancella con la procedura semplificata dell'art. "
            "40-bis T.U.B.",
            "A mortgage registration remains effective for twenty years from its date "
            "and lapses unless renewed before expiry. A mortgage securing a bank loan "
            "that has been repaid is cancelled through the simplified procedure of "
            "art. 40-bis of the Banking Act.",
            date(1942, 4, 21),
        ),
    ],
    "community_property": [
        Rule(
            "community_property",
            "Artt. 177, 180 e 184 c.c.",
            "I beni acquistati dai coniugi in regime di comunione legale durante il "
            "matrimonio sono comuni; l'atto di disposizione compiuto da un solo coniuge "
            "senza il consenso dell'altro è annullabile su domanda di quest'ultimo.",
            "Property acquired during a marriage under the statutory community regime "
            "is jointly owned; a disposal by one spouse without the other's consent may "
            "be annulled at the other spouse's request.",
            date(1975, 9, 20),
        ),
    ],
    "family_fund": [
        Rule(
            "family_fund",
            "Art. 169 c.c.",
            "I beni costituiti in fondo patrimoniale si alienano con il consenso di "
            "entrambi i coniugi e, se vi sono figli minori, con l'autorizzazione del "
            "giudice, salvo che l'atto costitutivo disponga diversamente.",
            "Property placed in a family fund may be sold only with the consent of both "
            "spouses and, where there are minor children, with the court's authorisation, "
            "unless the deed creating the fund provides otherwise.",
            date(1975, 9, 20),
        ),
    ],
    "inheritance_acceptance": [
        Rule(
            "inheritance_acceptance",
            "Artt. 2648 e 2650 c.c.",
            "L'acquisto per successione e l'accettazione dell'eredità, anche tacita, si "
            "trascrivono; senza la trascrizione dell'accettazione la catena delle "
            "trascrizioni è interrotta e le trascrizioni successive non producono effetto.",
            "An acquisition by succession and the acceptance of the inheritance, even "
            "implied, must be transcribed; without the transcription of the acceptance the "
            "chain of transcriptions is broken and later transcriptions have no effect.",
            date(1942, 4, 21),
        ),
    ],
    "installations_conformity": [
        Rule(
            "installations_conformity",
            "Artt. 7 e 8 D.M. 37/2008",
            "Gli impianti installati dopo il 27 marzo 2008 sono accompagnati dalla "
            "dichiarazione di conformità dell'impresa installatrice; per quelli "
            "precedenti può essere rilasciata una dichiarazione di rispondenza. L'obbligo "
            "di allegarle all'atto è stato abrogato: la garanzia di conformità è oggetto "
            "di accordo tra le parti.",
            "Installations made after 27 March 2008 come with the installer's declaration "
            "of conformity; for earlier ones a declaration of compliance may be issued. "
            "The obligation to attach them to the deed was repealed: the warranty of "
            "conformity is a matter for the parties to agree.",
            date(2008, 3, 27),
        ),
    ],
    "energy_certificate": [
        Rule(
            "energy_certificate",
            "Art. 6 D.Lgs. 192/2005 (come modificato dal D.L. 63/2013 conv. L. 90/2013)",
            "Il venditore mette a disposizione l'attestato di prestazione energetica "
            "dall'avvio delle trattative e lo consegna all'acquirente; l'attestato è "
            "allegato all'atto. Ha validità massima di dieci anni, subordinata al "
            "rispetto dei controlli sugli impianti termici.",
            "The seller makes the energy performance certificate available from the start "
            "of negotiations and delivers it to the buyer; the certificate is attached to "
            "the deed. It is valid for at most ten years, subject to the required "
            "inspections of the heating system.",
            date(2013, 6, 6),
        ),
    ],
}


def resolve(rule_id: str, on: date | None = None) -> Rule | None:
    """Return the version of *rule_id* in force on *on* (default: today)."""
    day = on or date.today()
    for rule in RULES.get(rule_id, ()):
        if rule.applies_on(day):
            return rule
    return None


def citation(rule_id: str, on: date | None = None) -> str | None:
    rule = resolve(rule_id, on)
    return rule.citation if rule is not None else None


def gloss(rule_id: str, on: date | None = None, language: str = "it") -> str | None:
    rule = resolve(rule_id, on)
    if rule is None:
        return None
    return rule.gloss_it if language == "it" else rule.gloss_en


def known_rule_ids() -> list[str]:
    return sorted(RULES)


def rules_context(on: date | None = None) -> str:
    """The rules in force, one block each, for the aggregation prompt."""
    lines = ["APPLICABLE ITALIAN RULES (cite them only where a finding engages them):"]
    for rule_id in known_rule_ids():
        rule = resolve(rule_id, on)
        if rule is not None:
            lines.append(f"- {rule.citation}: {rule.gloss_en}")
    return "\n".join(lines)


# ── Dates ───────────────────────────────────────────────────────────────────

_MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})")
_NUMERIC = re.compile(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})\s*$")
_WORDS = re.compile(r"^\s*(\d{1,2})(?:°|º)?\s+([a-zà-ù]+)\s+(\d{4})\s*$", re.IGNORECASE)


def parse_date(value: object) -> date | None:
    """Parse the date formats an Italian deed or a model answer uses.

    ``2015-03-12``, ``12/03/2015``, ``12.03.2015``, ``12 marzo 2015``.
    Anything else is None: a date that cannot be read is not guessed.
    """
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        if match := _ISO.match(value):
            return date(int(match[1]), int(match[2]), int(match[3]))
        if match := _NUMERIC.match(value):
            return date(int(match[3]), int(match[2]), int(match[1]))
        if match := _WORDS.match(value):
            month = _MONTHS_IT.get(match[2].lower())
            if month:
                return date(int(match[3]), month, int(match[1]))
    except ValueError:
        return None
    return None


def add_years(day: date, years: int) -> date:
    """*day* plus *years*; 29 February becomes 28 February in a common year."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


# ── Deterministic windows ───────────────────────────────────────────────────


@dataclass(frozen=True)
class DonationExposure:
    transcription_date: date
    window_ends: date
    open: bool


def donation_exposure(transcription_date: date, as_of: date | None = None) -> DonationExposure:
    """Whether a donation in the chain can still be reclaimed from a later buyer.

    Twenty years from the transcription (art. 563 c.c.). An opposition deed
    suspends the term: the specialist reports one where the documents show it,
    and the window computed here is then a minimum, not a certainty.
    """
    ends = add_years(transcription_date, TWENTY_YEARS)
    return DonationExposure(transcription_date, ends, (as_of or date.today()) < ends)


def mortgage_registration_lapsed(registration_date: date, as_of: date | None = None) -> bool:
    """True when twenty years have passed since the registration (art. 2847 c.c.).

    Only the absence of a renewal makes it lapse; the caller must therefore
    treat the result as "lapsed unless renewed", never as "cancelled".
    """
    return (as_of or date.today()) >= add_years(registration_date, TWENTY_YEARS)


@dataclass(frozen=True)
class ChainCoverage:
    earliest_title: date | None
    required_from: date
    covered: bool


def chain_coverage(title_dates: list[date], as_of: date | None = None) -> ChainCoverage:
    """Whether the deeds on file reach back twenty years before *as_of*."""
    required_from = add_years(as_of or date.today(), -TWENTY_YEARS)
    earliest = min(title_dates) if title_dates else None
    return ChainCoverage(earliest, required_from, earliest is not None and earliest <= required_from)


def format_date(day: date, language: str) -> str:
    if language == "it":
        months = list(_MONTHS_IT)
        return f"{day.day} {months[day.month - 1]} {day.year}"
    return day.strftime("%d %B %Y")
