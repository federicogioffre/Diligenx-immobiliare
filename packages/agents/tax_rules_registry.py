"""Year-indexed registry of Italian tax rules referenced by the tax agent.

Why this module exists
----------------------
Real tax due-diligence reports bake statutory rates into their findings
("penalties equal to 30% reduced to 1/8", "the four-year expiration term",
"higher than €50k"). Every one of those numbers has since changed — the
sanctions regime was rewritten twice (D.Lgs. 158/2015 and D.Lgs. 87/2024),
the assessment period moved from four years to five and lost the criminal
doubling, and criminal thresholds were raised. A report written by
specialists goes stale on the numbers in under four years while staying
accurate on the structure.

So the pipeline splits the two:

* the **LLM extracts facts** — what the document says, for which fiscal
  years, with which amount if the document states one. It is explicitly
  forbidden to compute penalties or interest (see
  ``packages.prompts.deal_prompts.TAX_ANALYSIS_PROMPT``);
* this **registry resolves the law** for the fiscal year of the finding,
  and the report prints the citation rather than arithmetic the model
  invented.

What the registry carries, and what it deliberately does not
------------------------------------------------------------
It carries **citations**, a short neutral gloss in both report languages,
and the **structural durations** that drive computation (the length of the
assessment period). It does **not** carry penalty percentages, interest
rates or reduction fractions: those produce numbers that belong to the
client's tax advisors, and a wrong one in a client-facing report is worse
than no number at all. Where a finding needs quantification, the correct
output is an Information Request, not an estimate.

Every entry carries ``valid_from`` / ``valid_to`` expressed in **fiscal
years** and a ``last_verified`` date, so a rule that changes again is a
one-line edit rather than a prompt rewrite.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)

# Date on which the entries below were last checked against the statutes.
LAST_VERIFIED = date(2026, 9, 6)

# The registry stores no penalty rate, interest rate or reduction fraction
# by design. This string is the reason, surfaced in the report when a
# finding carries no amount.
QUANTIFICATION_POLICY_EN = (
    "Quantification of higher taxes, penalties and interest is left to the "
    "client's tax advisors: the applicable rates depend on the fiscal year "
    "and on the procedure followed, and have been amended repeatedly."
)
QUANTIFICATION_POLICY_IT = (
    "La quantificazione di maggiori imposte, sanzioni e interessi è rimessa "
    "ai consulenti fiscali del cliente: le misure applicabili dipendono dal "
    "periodo d'imposta e dalla procedura seguita, e sono state più volte "
    "modificate."
)


# ── Rule entries ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaxRule:
    """One statutory rule, valid for a range of fiscal years."""

    rule_id: str
    citation: str
    gloss_en: str
    gloss_it: str
    valid_from: int              # first fiscal year the rule applies to
    valid_to: int | None = None  # last fiscal year, None = still in force
    superseded_by: str | None = None
    last_verified: date = LAST_VERIFIED

    def applies_to(self, fiscal_year: int) -> bool:
        if fiscal_year < self.valid_from:
            return False
        return self.valid_to is None or fiscal_year <= self.valid_to


def _rule(*args, **kwargs) -> TaxRule:
    return TaxRule(*args, **kwargs)


# Keyed by rule_id; each value is the ordered list of successive versions.
RULES: dict[str, list[TaxRule]] = {
    # ── Assessment period and procedure ──────────────────────────────────
    "assessment_period": [
        _rule(
            "assessment_period",
            "Art. 43 D.P.R. 600/1973 and art. 57 D.P.R. 633/1972 (text in "
            "force before L. 208/2015)",
            "Assessment could be served by 31 December of the fourth year "
            "following the year the return was filed (fifth year if no "
            "return was filed).",
            "L'accertamento poteva essere notificato entro il 31 dicembre "
            "del quarto anno successivo a quello di presentazione della "
            "dichiarazione (quinto anno in caso di omessa dichiarazione).",
            valid_from=1974,
            valid_to=2015,
            superseded_by="assessment_period",
        ),
        _rule(
            "assessment_period",
            "Artt. 43 D.P.R. 600/1973 and 57 D.P.R. 633/1972, as amended by "
            "art. 1 co. 130-132 L. 208/2015",
            "Assessment may be served by 31 December of the fifth year "
            "following the year the return was filed (seventh year if no "
            "return was filed). An amended return reopens the term only "
            "for the items amended.",
            "L'accertamento può essere notificato entro il 31 dicembre del "
            "quinto anno successivo a quello di presentazione della "
            "dichiarazione (settimo anno in caso di omessa dichiarazione). "
            "La dichiarazione integrativa riapre i termini limitatamente "
            "agli elementi oggetto di integrazione.",
            valid_from=2016,
        ),
    ],
    "assessment_period_doubling": [
        _rule(
            "assessment_period_doubling",
            "Art. 43 co. 3 D.P.R. 600/1973 (text in force before L. 208/2015)",
            "The assessment term was doubled where a criminal report for a "
            "tax offence was filed within the ordinary term.",
            "I termini di accertamento erano raddoppiati in caso di denuncia "
            "per reato tributario presentata entro il termine ordinario.",
            valid_from=1974,
            valid_to=2015,
        ),
        # Deliberately no entry from 2016: the doubling was abolished.
    ],
    "preliminary_cross_examination": [
        _rule(
            "preliminary_cross_examination",
            "Art. 6-bis L. 212/2000, introduced by D.Lgs. 219/2023 "
            "(acts issued from 30 April 2024)",
            "Before issuing most assessments the authority must serve a "
            "draft act and allow the taxpayer 60 days to reply; an act "
            "issued in breach is invalid.",
            "Prima di emettere la generalità degli atti impositivi "
            "l'amministrazione deve comunicare uno schema di atto e "
            "concedere 60 giorni per le controdeduzioni; l'atto emesso in "
            "violazione è annullabile.",
            valid_from=2024,
        ),
    ],
    "tax_litigation_courts": [
        _rule(
            "tax_litigation_courts",
            "D.Lgs. 546/1992 (text before L. 130/2022)",
            "First and second instance before the Provincial and Regional "
            "Tax Commissions.",
            "Primo e secondo grado davanti alle Commissioni tributarie "
            "provinciali e regionali.",
            valid_from=1993,
            valid_to=2021,
            superseded_by="tax_litigation_courts",
        ),
        _rule(
            "tax_litigation_courts",
            "D.Lgs. 546/1992 as amended by L. 130/2022 and D.Lgs. 220/2023",
            "First and second instance before the Tax Justice Courts; the "
            "burden of proof rests on the authority (art. 7 co. 5-bis); "
            "the mandatory complaint/mediation stage was abolished.",
            "Primo e secondo grado davanti alle Corti di giustizia "
            "tributaria; l'onere della prova grava sull'amministrazione "
            "(art. 7 co. 5-bis); abolito il reclamo-mediazione.",
            valid_from=2022,
        ),
    ],
    # ── Sanctions: citations only, never rates ───────────────────────────
    "unfaithful_return_penalty": [
        _rule(
            "unfaithful_return_penalty",
            "Art. 1 D.Lgs. 471/1997, as amended by D.Lgs. 158/2015",
            "Penalty for a return showing lower taxes than due. Rates are "
            "not reproduced here — see the quantification policy.",
            "Sanzione per dichiarazione infedele. Le misure non sono "
            "riportate — si veda la politica di quantificazione.",
            valid_from=2016,
            valid_to=2023,
            superseded_by="unfaithful_return_penalty",
        ),
        _rule(
            "unfaithful_return_penalty",
            "Art. 1 D.Lgs. 471/1997, as amended by D.Lgs. 87/2024 "
            "(violations committed from 1 September 2024)",
            "Penalty for a return showing lower taxes than due, restated by "
            "the 2024 reform. Rates are not reproduced here.",
            "Sanzione per dichiarazione infedele, rideterminata dalla "
            "riforma del 2024. Le misure non sono riportate.",
            valid_from=2024,
        ),
    ],
    "late_payment_penalty": [
        _rule(
            "late_payment_penalty",
            "Art. 13 D.Lgs. 471/1997",
            "Penalty for omitted or late payment of a tax resulting from a "
            "return. Rates are not reproduced here.",
            "Sanzione per omesso o tardivo versamento delle imposte "
            "risultanti dalla dichiarazione. Le misure non sono riportate.",
            valid_from=1998,
            valid_to=2023,
            superseded_by="late_payment_penalty",
        ),
        _rule(
            "late_payment_penalty",
            "Art. 13 D.Lgs. 471/1997, as amended by D.Lgs. 87/2024 "
            "(violations committed from 1 September 2024)",
            "Penalty for omitted or late payment, reduced by the 2024 "
            "reform. Rates are not reproduced here.",
            "Sanzione per omesso o tardivo versamento, ridotta dalla "
            "riforma del 2024. Le misure non sono riportate.",
            valid_from=2024,
        ),
    ],
    "formal_violation_not_punishable": [
        _rule(
            "formal_violation_not_punishable",
            "Art. 6 co. 5-bis D.Lgs. 472/1997",
            "Violations that neither obstruct controls nor affect the tax "
            "due are merely formal and are not punishable.",
            "Le violazioni che non arrecano pregiudizio ai controlli né "
            "incidono sull'imposta dovuta sono meramente formali e non "
            "punibili.",
            valid_from=2000,
        ),
    ],
    "voluntary_correction": [
        _rule(
            "voluntary_correction",
            "Art. 13 D.Lgs. 472/1997 (ravvedimento operoso)",
            "Voluntary regularisation before assessment reduces the "
            "penalty by a fraction depending on when it occurs. The "
            "fractions are not reproduced here.",
            "Il ravvedimento operoso prima dell'accertamento riduce la "
            "sanzione in misura variabile secondo il momento in cui "
            "interviene. Le frazioni non sono riportate.",
            valid_from=1998,
            valid_to=2023,
            superseded_by="voluntary_correction",
        ),
        _rule(
            "voluntary_correction",
            "Art. 13 D.Lgs. 472/1997, as restated by D.Lgs. 87/2024",
            "Ravvedimento operoso, with the reduction tiers restructured "
            "around the preliminary cross-examination procedure.",
            "Ravvedimento operoso, con le riduzioni riarticolate intorno "
            "al contraddittorio preventivo.",
            valid_from=2024,
        ),
    ],
    "tax_crimes_entity_liability": [
        _rule(
            "tax_crimes_entity_liability",
            "Art. 25-quinquiesdecies D.Lgs. 231/2001, introduced by "
            "L. 157/2019 and extended by D.Lgs. 75/2020",
            "Certain tax offences trigger the company's own liability "
            "under the corporate criminal-liability regime, with pecuniary "
            "and disqualifying sanctions and confiscation.",
            "Determinati reati tributari fanno scattare la responsabilità "
            "amministrativa da reato dell'ente, con sanzioni pecuniarie e "
            "interdittive e confisca.",
            valid_from=2020,
        ),
    ],
    # ── Direct taxes ─────────────────────────────────────────────────────
    "tax_losses_carry_forward": [
        _rule(
            "tax_losses_carry_forward",
            "Art. 84 T.U.I.R.",
            "Losses carry forward without time limit but offset only part "
            "of the taxable income; start-up losses offset it in full.",
            "Le perdite sono riportabili senza limiti di tempo ma "
            "compensano solo una quota del reddito imponibile; le perdite "
            "dei primi esercizi lo compensano integralmente.",
            valid_from=2011,
        ),
    ],
    "tax_losses_change_of_control": [
        _rule(
            "tax_losses_change_of_control",
            "Art. 84 co. 3 T.U.I.R.",
            "Carried-forward losses are forfeited where a transfer of the "
            "majority of voting rights coincides with a change of the main "
            "activity within the statutory window, unless the vitality "
            "tests are met.",
            "Le perdite riportate non sono utilizzabili se al "
            "trasferimento della maggioranza dei diritti di voto si "
            "accompagna la modifica dell'attività principale nella "
            "finestra di legge, salvo il superamento dei test di vitalità.",
            valid_from=2011,
        ),
    ],
    "tax_losses_merger": [
        _rule(
            "tax_losses_merger",
            "Art. 172 co. 7 T.U.I.R.",
            "In mergers and demergers the losses carried over are capped by "
            "the company's equity and subject to vitality tests.",
            "Nelle fusioni e scissioni il riporto delle perdite è limitato "
            "dal patrimonio netto della società e subordinato ai test di "
            "vitalità.",
            valid_from=2004,
            valid_to=2023,
            superseded_by="tax_losses_merger",
        ),
        _rule(
            "tax_losses_merger",
            "Art. 172 co. 7 T.U.I.R., as rewritten by D.Lgs. 192/2024",
            "The vitality test and the equity cap on losses carried over in "
            "mergers and demergers were restated by the 2024 corporate-tax "
            "reform; analyses predating it must be redone.",
            "Il test di vitalità e il limite del patrimonio netto per il "
            "riporto delle perdite in fusioni e scissioni sono stati "
            "riscritti dalla riforma IRES del 2024; le analisi anteriori "
            "vanno rifatte.",
            valid_from=2024,
        ),
    ],
    "interest_carry_forward": [
        _rule(
            "interest_carry_forward",
            "Art. 96 T.U.I.R. (text before D.Lgs. 142/2018)",
            "Net interest expense deductible within a share of accounting "
            "EBITDA, with unlimited carry-forward of the excess.",
            "Interessi passivi netti deducibili entro una quota del ROL "
            "contabile, con riporto illimitato dell'eccedenza.",
            valid_from=2008,
            valid_to=2018,
            superseded_by="interest_carry_forward",
        ),
        _rule(
            "interest_carry_forward",
            "Art. 96 T.U.I.R., as rewritten by D.Lgs. 142/2018 (ATAD)",
            "Net interest expense deductible within a share of tax EBITDA; "
            "spare capacity carries forward for a limited number of years; "
            "grandfathering applies to loans signed before 17 June 2016.",
            "Interessi passivi netti deducibili entro una quota del ROL "
            "fiscale; l'eccedenza di ROL è riportabile per un numero "
            "limitato di esercizi; regime transitorio per i finanziamenti "
            "stipulati prima del 17 giugno 2016.",
            valid_from=2019,
        ),
    ],
    "ace": [
        _rule(
            "ace",
            "Art. 1 D.L. 201/2011 (aiuto alla crescita economica)",
            "Notional deduction on equity increases.",
            "Deduzione figurativa sugli incrementi di patrimonio netto.",
            valid_from=2011,
            valid_to=2023,
            superseded_by="ace_repeal",
        ),
    ],
    "ace_repeal": [
        _rule(
            "ace_repeal",
            "Art. 5 D.Lgs. 216/2023",
            "The notional equity deduction is repealed; surpluses accrued "
            "up to the last year of application remain usable.",
            "L'ACE è abrogata; le eccedenze maturate fino all'ultimo "
            "esercizio di applicazione restano utilizzabili.",
            valid_from=2024,
        ),
    ],
    "shareholder_waiver": [
        _rule(
            "shareholder_waiver",
            "Art. 88 co. 4-bis T.U.I.R., introduced by D.Lgs. 147/2015",
            "A shareholder's waiver of a receivable is untaxed for the "
            "company only up to the tax basis of the receivable, which the "
            "shareholder must certify by a sworn self-declaration; absent "
            "it the basis is presumed nil and the waiver is fully taxable.",
            "La rinuncia del socio al credito non è tassata in capo alla "
            "società solo entro il valore fiscale del credito, che il socio "
            "deve attestare con dichiarazione sostitutiva di atto notorio; "
            "in mancanza il valore si presume nullo e la rinuncia è "
            "integralmente tassata.",
            valid_from=2016,
        ),
    ],
    "directors_fees": [
        _rule(
            "directors_fees",
            "Art. 95 co. 5 T.U.I.R.",
            "Directors' fees are deductible in the year of payment and to "
            "the extent they are resolved by the shareholders' meeting.",
            "I compensi agli amministratori sono deducibili nell'esercizio "
            "di pagamento e nei limiti di quanto deliberato dall'assemblea.",
            valid_from=2004,
        ),
    ],
    "maintenance_expenses": [
        _rule(
            "maintenance_expenses",
            "Art. 102 co. 6 T.U.I.R.",
            "Ordinary maintenance is deductible in the year within a share "
            "of the cost of depreciable assets, the excess over the "
            "following years; expenses that extend an asset's useful life "
            "must instead be capitalised and depreciated with it.",
            "Le manutenzioni ordinarie sono deducibili nell'esercizio entro "
            "una quota del costo dei beni ammortizzabili, l'eccedenza nei "
            "periodi successivi; le spese che accrescono la vita utile del "
            "bene vanno capitalizzate e ammortizzate con esso.",
            valid_from=2004,
        ),
    ],
    "inventory_valuation": [
        _rule(
            "inventory_valuation",
            "Art. 92 T.U.I.R.",
            "Statutory minimum criteria for the valuation of inventory; the "
            "closing balance of one year is the opening balance of the "
            "next, so an adjustment reverses in the following period.",
            "Criteri minimi di valutazione delle rimanenze; il valore "
            "finale di un esercizio è il valore iniziale del successivo, "
            "sicché una rettifica si riversa nel periodo seguente.",
            valid_from=2004,
        ),
    ],
    "presumption_of_sale": [
        _rule(
            "presumption_of_sale",
            "D.P.R. 441/1997",
            "Goods not found on the premises are presumed sold, and goods "
            "found but not accounted for are presumed purchased, for VAT "
            "purposes.",
            "I beni non rinvenuti si presumono ceduti e quelli rinvenuti "
            "ma non contabilizzati si presumono acquistati, ai fini IVA.",
            valid_from=1998,
        ),
    ],
    "transformation_reserves": [
        _rule(
            "transformation_reserves",
            "Art. 170 T.U.I.R.",
            "A change of legal form is tax neutral; on conversion of a "
            "partnership into a company the fiscal year splits in two and "
            "reserves already taxed on the partners must be booked and "
            "disclosed as such, or they are taxed again on distribution.",
            "La trasformazione è fiscalmente neutrale; nella trasformazione "
            "di società di persone in società di capitali il periodo "
            "d'imposta si divide in due e le riserve già tassate per "
            "trasparenza vanno iscritte e indicate come tali, altrimenti "
            "sono tassate nuovamente all'atto della distribuzione.",
            valid_from=2004,
        ),
    ],
    "domestic_related_parties": [
        _rule(
            "domestic_related_parties",
            "Art. 109 T.U.I.R. (no domestic transfer-pricing rule)",
            "Italy imposes no arm's-length requirement between resident "
            "related parties; the authority may nonetheless challenge a "
            "transaction shown to be economically inconsistent.",
            "Non esiste un obbligo di applicare condizioni di mercato tra "
            "parti correlate residenti; l'amministrazione può tuttavia "
            "contestare l'operazione manifestamente antieconomica.",
            valid_from=2004,
        ),
    ],
    "transfer_pricing": [
        _rule(
            "transfer_pricing",
            "Art. 110 co. 7 T.U.I.R. and Circ. 32/1980",
            "Cross-border intercompany transactions valued at normal value.",
            "Operazioni infragruppo transfrontaliere valutate al valore "
            "normale.",
            valid_from=2004,
            valid_to=2016,
            superseded_by="transfer_pricing",
        ),
        _rule(
            "transfer_pricing",
            "Art. 110 co. 7 T.U.I.R. as amended by D.L. 50/2017, D.M. "
            "14 May 2018 and Provv. Ag. Entrate 23 November 2020",
            "Cross-border intercompany transactions valued at arm's length; "
            "master file and local file, signed and time-stamped by the "
            "return deadline, give penalty protection.",
            "Operazioni infragruppo transfrontaliere valutate secondo il "
            "principio di libera concorrenza; masterfile e documentazione "
            "nazionale, firmati e marcati temporalmente entro il termine "
            "della dichiarazione, danno accesso alla penalty protection.",
            valid_from=2017,
        ),
    ],
    "black_list_costs": [
        _rule(
            "black_list_costs",
            "Art. 110 co. 10-12-bis T.U.I.R. (text before L. 208/2015)",
            "Costs from suppliers in privileged-tax jurisdictions "
            "deductible only on proof of the statutory conditions, with a "
            "separate disclosure requirement in the return.",
            "Costi da fornitori in Stati a fiscalità privilegiata "
            "deducibili solo alle condizioni di legge, con obbligo di "
            "separata indicazione in dichiarazione.",
            valid_from=2004,
            valid_to=2015,
            superseded_by="black_list_costs_repeal",
        ),
    ],
    "black_list_costs_repeal": [
        _rule(
            "black_list_costs_repeal",
            "L. 208/2015",
            "The special regime for costs from privileged-tax "
            "jurisdictions is repealed.",
            "È abrogata la disciplina speciale dei costi da Stati a "
            "fiscalità privilegiata.",
            valid_from=2016,
            valid_to=2022,
            superseded_by="black_list_costs_reintroduced",
        ),
    ],
    "black_list_costs_reintroduced": [
        _rule(
            "black_list_costs_reintroduced",
            "Art. 110 co. 9-bis T.U.I.R., reintroduced by art. 1 "
            "co. 84-86 L. 197/2022",
            "Costs from counterparties in non-cooperative jurisdictions are "
            "deductible only up to normal value, with separate disclosure "
            "in the return.",
            "I costi verso controparti in Paesi non cooperativi sono "
            "deducibili nel limite del valore normale, con separata "
            "indicazione in dichiarazione.",
            valid_from=2023,
        ),
    ],
    # ── Compliance obligations that came and went ────────────────────────
    "periodic_vat_communication": [
        _rule(
            "periodic_vat_communication",
            "Art. 21-bis D.L. 78/2010 (LIPE)",
            "Periodic communication of VAT settlements.",
            "Comunicazione delle liquidazioni periodiche IVA.",
            valid_from=2017,
        ),
    ],
    "spesometro": [
        _rule(
            "spesometro",
            "Art. 21 D.L. 78/2010",
            "Communication of VAT-relevant transactions; superseded by "
            "mandatory electronic invoicing.",
            "Comunicazione delle operazioni rilevanti ai fini IVA; "
            "superata dall'obbligo di fatturazione elettronica.",
            valid_from=2011,
            valid_to=2018,
            superseded_by="electronic_invoicing",
        ),
    ],
    "black_list_communication": [
        _rule(
            "black_list_communication",
            "D.M. 30 March 2010; repealed by D.L. 193/2016",
            "Periodic communication of transactions with counterparties in "
            "privileged-tax jurisdictions.",
            "Comunicazione periodica delle operazioni con controparti in "
            "Stati a fiscalità privilegiata.",
            valid_from=2010,
            valid_to=2016,
        ),
    ],
    "electronic_invoicing": [
        _rule(
            "electronic_invoicing",
            "D.Lgs. 127/2015",
            "Mandatory electronic invoicing through the exchange system; "
            "cross-border transactions reported through the same channel.",
            "Fatturazione elettronica obbligatoria tramite il Sistema di "
            "Interscambio; operazioni transfrontaliere comunicate con lo "
            "stesso canale.",
            valid_from=2019,
        ),
    ],
    "reliability_indexes": [
        _rule(
            "reliability_indexes",
            "Sector studies (studi di settore), D.L. 331/1993",
            "Sector-based estimate of minimum revenue for taxpayers below a "
            "turnover threshold.",
            "Stima settoriale dei ricavi minimi per i contribuenti sotto "
            "una soglia di ricavi.",
            valid_from=1994,
            valid_to=2017,
            superseded_by="reliability_indexes",
        ),
        _rule(
            "reliability_indexes",
            "Art. 9-bis D.L. 50/2017 (indici sintetici di affidabilità "
            "fiscale — ISA)",
            "Statistical reliability score; a low score grants no benefits "
            "and is an audit-risk indicator, not an exposure in itself.",
            "Punteggio statistico di affidabilità; un punteggio basso non "
            "dà accesso ai benefici premiali ed è un indicatore di rischio "
            "di controllo, non un'esposizione in sé.",
            valid_from=2018,
        ),
    ],
    "withholding_in_procurement": [
        _rule(
            "withholding_in_procurement",
            "Art. 17-bis D.Lgs. 241/1997",
            "In labour-intensive contracts above the statutory threshold "
            "the principal must control the contractor's withholding "
            "payments unless a compliance certificate (DURF) is produced.",
            "Negli appalti ad alta intensità di manodopera sopra soglia il "
            "committente deve controllare i versamenti delle ritenute "
            "dell'appaltatore, salvo rilascio del DURF.",
            valid_from=2020,
        ),
    ],
    "transferee_liability_asset_deal": [
        _rule(
            "transferee_liability_asset_deal",
            "Art. 14 D.Lgs. 472/1997",
            "In a business transfer the transferee is jointly liable for "
            "the transferor's tax debts, capped by the amounts shown in the "
            "certificate issued by the authority. It does not apply to a "
            "transfer of shares or quotas.",
            "Nella cessione d'azienda il cessionario è responsabile in "
            "solido per i debiti tributari del cedente, nei limiti "
            "risultanti dal certificato rilasciato dall'amministrazione. "
            "Non si applica alla cessione di partecipazioni.",
            valid_from=1998,
        ),
    ],
}


# ── Lookup ───────────────────────────────────────────────────────────────────


def resolve(rule_id: str, fiscal_year: int) -> TaxRule | None:
    """Return the version of *rule_id* in force for *fiscal_year*.

    Returns ``None`` when the rule is unknown, or when it was not in force
    for that fiscal year (which is itself meaningful: an obligation that no
    longer exists must not be cited as current).
    """
    for rule in RULES.get(rule_id, ()):
        if rule.applies_to(fiscal_year):
            return rule
    return None


def citation(rule_id: str, fiscal_year: int) -> str | None:
    """Convenience wrapper returning only the citation string."""
    rule = resolve(rule_id, fiscal_year)
    return rule.citation if rule is not None else None


def gloss(rule_id: str, fiscal_year: int, language: str = "en") -> str | None:
    """Return the short neutral gloss for the report, in ``it`` or ``en``."""
    rule = resolve(rule_id, fiscal_year)
    if rule is None:
        return None
    return rule.gloss_it if language == "it" else rule.gloss_en


def known_rule_ids() -> list[str]:
    """All rule identifiers held by the registry, sorted."""
    return sorted(RULES)


# ── Assessment period ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AssessmentPeriod:
    """When the tax authority's power to assess *fiscal_year* expires."""

    fiscal_year: int
    filing_year: int
    years_from_filing: int
    expiry: date
    return_filed: bool
    citation: str
    notes: list[str] = field(default_factory=list)

    def is_time_barred(self, as_of: date | None = None) -> bool:
        return (as_of or date.today()) > self.expiry


def assessment_period(
    fiscal_year: int,
    *,
    return_filed: bool = True,
) -> AssessmentPeriod:
    """Compute the assessment deadline for a calendar-year *fiscal_year*.

    The return for a fiscal year is filed in the following calendar year;
    the term runs from that filing year. Up to fiscal year 2015 the term was
    four years (five if no return was filed); from fiscal year 2016 it is
    five years (seven if no return was filed), and the doubling that applied
    where a criminal tax report had been filed no longer exists.

    The result is a *deterministic baseline*. It does not apply the
    emergency extensions granted for individual years, nor the reopening
    produced by an amended return: both are recorded in ``notes`` for the
    reader instead of being silently baked into the date.
    """
    filing_year = fiscal_year + 1

    if fiscal_year <= 2015:
        years = 4 if return_filed else 5
    else:
        years = 5 if return_filed else 7

    rule = resolve("assessment_period", fiscal_year)
    notes: list[str] = []

    if fiscal_year <= 2015:
        notes.append(
            "Up to fiscal year 2015 the term could be doubled where a "
            "criminal report for a tax offence had been filed within the "
            "ordinary term; the doubling was abolished from fiscal year 2016."
        )
        notes.append(
            "Emergency legislation extended the notification term for some "
            "of these years; verify the position for the specific year."
        )
    if not return_filed:
        notes.append(
            "Term computed on the assumption that no return was filed for "
            "this fiscal year."
        )
    notes.append(
        "An amended return reopens the term only for the items amended."
    )

    return AssessmentPeriod(
        fiscal_year=fiscal_year,
        filing_year=filing_year,
        years_from_filing=years,
        expiry=date(filing_year + years, 12, 31),
        return_filed=return_filed,
        citation=rule.citation if rule is not None else "",
        notes=notes,
    )


def open_fiscal_years(as_of: date | None = None) -> list[int]:
    """Fiscal years still open to assessment at *as_of*, oldest first.

    Used to scope a tax review and to phrase the report's scope sentence,
    so that neither is hard-coded to a fixed number of years.
    """
    today = as_of or date.today()
    years = [
        y
        for y in range(today.year - 12, today.year + 1)
        if not assessment_period(y).is_time_barred(today)
    ]
    return years


def describe_scope(as_of: date | None = None, language: str = "en") -> str:
    """One sentence stating the review period, computed rather than fixed."""
    years = open_fiscal_years(as_of)
    if not years:  # pragma: no cover — cannot happen with the rules above
        return ""
    first, last = years[0], years[-1]
    if language == "it":
        return (
            f"L'analisi copre i periodi d'imposta ancora accertabili "
            f"(dal {first} al {last}), salvo diversa indicazione."
        )
    return (
        f"The review covers the fiscal years still open to assessment "
        f"({first} to {last}), unless stated otherwise."
    )
