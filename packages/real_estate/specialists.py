"""The four documentary reviewers of a residential purchase.

Each is a :class:`~packages.real_estate.review_agent.DocumentReviewAgent`
that only declares its data. The keyword floors are the matters a buyer's
notary would never let pass unremarked: a foreclosure or a seizure in a
registry search, a donation in the chain, an amnesty application, arrears.
"""
from __future__ import annotations

from datetime import date

from packages.real_estate import prompts
from packages.real_estate import rules_registry as rr
from packages.real_estate.review_agent import DocumentReviewAgent, Heuristic


def _as_of() -> date:
    return date.today()


class TitleChainAgent(DocumentReviewAgent):
    AGENT_NAME = "title_chain_review"
    ROUTED_TYPES = frozenset({"atto_provenienza", "successione", "ispezione_ipotecaria",
                              "documento_venditore", "preliminare", "perizia"})
    DOC_KEYWORDS = (
        "atto di compravendita", "atto di donazione", "donazione", "successione",
        "accettazione dell'eredità", "accettazione di eredità", "relazione notarile",
        "certificazione notarile", "provenienza", "ventennio", "estratto di matrimonio",
        "atto di matrimonio", "procura",
    )
    PROMPT = prompts.TITLE_CHAIN_PROMPT
    VALID_FINDING_TYPES = frozenset({
        "donation_in_chain", "opposition_deed", "inheritance_not_accepted",
        "succession_missing", "marital_regime", "family_fund", "chain_gap_20y",
        "power_of_attorney", "other_title",
    })
    FALLBACK_TYPE = "other_title"
    HEURISTICS = (
        Heuristic("atto di donazione", "donation_in_chain", "Donazione tra i titoli di provenienza", "high",
                  "A donation within twenty years of its transcription can be reclaimed from a later buyer (art. 563 c.c.)."),
        # Low: deeds often mention a donation only to exclude one.
        Heuristic("donazione", "donation_in_chain", "Donazione menzionata nei titoli", "low",
                  "Verify whether a donation appears in the chain of the last twenty years (art. 563 c.c.)."),
        Heuristic("opposizione alla donazione", "opposition_deed", "Atto di opposizione alla donazione", "high",
                  "An opposition deed suspends the twenty-year term of art. 563 c.c."),
        Heuristic("accettazione tacita", "inheritance_not_accepted", "Accettazione tacita dell'eredità", "medium",
                  "Verify that the acceptance of the inheritance has been transcribed (artt. 2648 e 2650 c.c.)."),
        Heuristic("fondo patrimoniale", "family_fund", "Fondo patrimoniale", "high",
                  "Property in a family fund is sold only with both spouses' consent and, with minor children, the court's authorisation (art. 169 c.c.)."),
        Heuristic("comunione legale", "marital_regime", "Regime di comunione legale", "medium",
                  "A disposal by one spouse alone may be annulled (art. 184 c.c.): verify the spouse's participation."),
    )

    def enrich(self, payload: dict) -> dict:
        if payload["finding_type"] == "donation_in_chain":
            day = rr.parse_date(payload.get("event_date"))
            if day is not None:
                exposure = rr.donation_exposure(day, _as_of())
                payload["donation_window_open"] = exposure.open
                payload["donation_window_ends"] = exposure.window_ends.isoformat()
                if exposure.open:
                    payload["severity"] = "high"
        return payload


class EncumbrancesAgent(DocumentReviewAgent):
    AGENT_NAME = "encumbrances_review"
    ROUTED_TYPES = frozenset({"ispezione_ipotecaria", "atto_provenienza", "preliminare", "perizia"})
    DOC_KEYWORDS = (
        "ispezione ipotecaria", "visura ipotecaria", "iscrizione", "trascrizione",
        "ipoteca", "pignoramento", "sequestro", "domanda giudiziale", "servitù",
        "nota di iscrizione", "nota di trascrizione", "relazione notarile",
    )
    PROMPT = prompts.ENCUMBRANCES_PROMPT
    VALID_FINDING_TYPES = frozenset({
        "mortgage", "foreclosure", "seizure", "judicial_claim", "easement",
        "fondo_patrimoniale", "transcribed_preliminary", "tax_lien", "other_encumbrance",
    })
    FALLBACK_TYPE = "other_encumbrance"
    HEURISTICS = (
        Heuristic("pignoramento", "foreclosure", "Pignoramento immobiliare", "high",
                  "A transcribed foreclosure must be cancelled before the deed; the buyer otherwise acquires subject to it."),
        Heuristic("sequestro", "seizure", "Sequestro sull'immobile", "high"),
        Heuristic("domanda giudiziale", "judicial_claim", "Domanda giudiziale trascritta", "high",
                  "A transcribed claim is enforceable against a later buyer if it succeeds."),
        Heuristic("ipoteca giudiziale", "mortgage", "Ipoteca giudiziale", "high"),
        Heuristic("ipoteca volontaria", "mortgage", "Ipoteca volontaria", "medium",
                  "Verify whether the mortgage is to be cancelled at the deed."),
        Heuristic("fondo patrimoniale", "fondo_patrimoniale", "Fondo patrimoniale annotato", "high"),
        Heuristic("agenzia delle entrate-riscossione", "tax_lien", "Ipoteca dell'agente della riscossione", "high"),
    )

    def enrich(self, payload: dict) -> dict:
        if payload["finding_type"] == "mortgage":
            day = rr.parse_date(payload.get("event_date"))
            if day is not None:
                payload["registration_over_twenty_years"] = rr.mortgage_registration_lapsed(day, _as_of())
        return payload


class BuildingCadastralAgent(DocumentReviewAgent):
    AGENT_NAME = "building_cadastral_review"
    ROUTED_TYPES = frozenset({"titolo_edilizio", "agibilita", "cdu", "visura_catastale",
                              "planimetria", "perizia", "atto_provenienza"})
    DOC_KEYWORDS = (
        "licenza edilizia", "concessione edilizia", "permesso di costruire", "dia", "scia",
        "cila", "condono", "sanatoria", "agibilità", "abitabilità", "difformità", "abuso",
        "visura catastale", "planimetria", "superbonus", "1° settembre 1967", "vincolo",
        "conformità urbanistica", "conformità catastale",
    )
    PROMPT = prompts.BUILDING_CADASTRAL_PROMPT
    VALID_FINDING_TYPES = frozenset({
        "cadastral_nonconformity", "building_irregularity", "pending_amnesty",
        "missing_habitability", "superbonus_works", "pre_1967_declaration",
        "urban_planning_constraint", "other_building",
    })
    FALLBACK_TYPE = "other_building"
    HEURISTICS = (
        Heuristic("abuso edilizio", "building_irregularity", "Abuso edilizio", "high"),
        Heuristic("difformità", "building_irregularity", "Difformità rispetto al titolo", "medium",
                  "A deviation from the permit does not void the deed but affects value and marketability."),
        Heuristic("non conforme", "cadastral_nonconformity", "Non conformità segnalata", "medium",
                  "The deed requires the owners' declaration that cadastral data and floor plan match the actual state (art. 29, comma 1-bis, L. 52/1985)."),
        Heuristic("domanda di condono", "pending_amnesty", "Domanda di condono", "high",
                  "Verify whether the amnesty was granted and its conditions met."),
        Heuristic("in sanatoria", "pending_amnesty", "Pratica in sanatoria", "medium"),
        Heuristic("superbonus", "superbonus_works", "Interventi Superbonus", "medium",
                  "Verify the compliance filings of the works and any open position on the tax credit."),
    )


class CondominiumOccupancyAgent(DocumentReviewAgent):
    AGENT_NAME = "condominium_occupancy_review"
    ROUTED_TYPES = frozenset({"regolamento_condominiale", "verbale_assemblea",
                              "situazione_condominiale", "locazione", "preliminare", "perizia"})
    DOC_KEYWORDS = (
        "condominio", "condominiale", "assemblea", "amministratore", "millesim",
        "contratto di locazione", "locazione", "comodato", "conduttore", "inquilino",
        "morosità",
    )
    PROMPT = prompts.CONDOMINIUM_OCCUPANCY_PROMPT
    VALID_FINDING_TYPES = frozenset({
        "arrears", "approved_extraordinary_works", "use_restriction",
        "pending_condo_litigation", "lease_in_place", "occupied_without_title",
        "other_condominium",
    })
    FALLBACK_TYPE = "other_condominium"
    HEURISTICS = (
        Heuristic("morosità", "arrears", "Morosità condominiale", "medium",
                  "The buyer is jointly liable for the contributions of the current and the previous year (art. 63 disp. att. c.c.)."),
        Heuristic("lavori straordinari", "approved_extraordinary_works", "Lavori straordinari deliberati", "medium",
                  "Agree in the preliminary contract who bears the works approved before the deed."),
        Heuristic("contratto di locazione", "lease_in_place", "Contratto di locazione", "medium"),
        Heuristic("senza titolo", "occupied_without_title", "Occupazione senza titolo", "high"),
    )


SPECIALISTS: tuple[type[DocumentReviewAgent], ...] = (
    TitleChainAgent,
    EncumbrancesAgent,
    BuildingCadastralAgent,
    CondominiumOccupancyAgent,
)
