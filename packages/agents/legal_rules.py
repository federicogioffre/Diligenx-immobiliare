"""Legal relevance rules for red-flag classification.

This module centralises the jurisdiction-specific knowledge used by the
red-flag aggregation agent.  Rules can be tuned without touching prompt
strings or agent logic.

Structure
---------
SAFE_HARBOR   – provisions that must NOT be raised as red flags unless
                they deviate from the statutory default or are breached.
PRIORITY      – patterns that MUST always be identified if present.
CONTEXT       – general jurisdiction context injected into every prompt.

The public function ``build_legal_rules_context()`` renders the above into
a single prompt-ready string that is injected as ``{legal_rules_context}``
into RED_FLAG_AGGREGATION_PROMPT and REPORT_GENERATION_PROMPT.
"""

# ── Safe harbour ─────────────────────────────────────────────────────────────

SAFE_HARBOR: list[dict] = [
    {
        "id": "italian_law_defaults",
        "title": "Standard Italian Civil Code provisions",
        "description": (
            "Any provision that simply restates or mirrors the Italian Civil Code "
            "(Codice Civile) default — including statutory director duties, standard "
            "liability rules, statutory approval of financial statements, and default "
            "quorum / majority thresholds — is NOT a red flag.  Flag it only if the "
            "statute or contract EXPANDS the statutory rule in a way that is adverse "
            "to the acquirer, or if there is evidence of an actual breach."
        ),
    },
    {
        "id": "director_non_compete",
        "title": "Director non-compete (Art. 2390 c.c.)",
        "description": (
            "The statutory prohibition on directors holding competing positions "
            "(Art. 2390 c.c.) is a legal default.  Do NOT flag it as a risk unless: "
            "(a) the company statute expands the prohibition beyond the statutory scope, "
            "or (b) there is concrete evidence that a director is in breach."
        ),
    },
    {
        "id": "standard_arbitration",
        "title": "Standard Italian arbitration clause (clausola compromissoria)",
        "description": (
            "An arbitration clause in a company statute or agreement that references "
            "standard Italian arbitration (e.g. Camere Arbitrali italiane, arbitrato "
            "rituale under Italian law) is a LOW-relevance governance provision, "
            "not a red flag.  Raise it as a red flag ONLY if: "
            "(a) the seat of arbitration is outside Italy without commercial justification, "
            "(b) the composition rules are unusual or exclude statutory protections, or "
            "(c) the clause removes a right that is mandatory under Italian law."
        ),
    },
    {
        "id": "valuation_differences",
        "title": "Share capital vs. deal enterprise value",
        "description": (
            "A difference between the registered share capital (capitale sociale) and "
            "the deal enterprise value or purchase price is a COMMERCIAL / VALUATION "
            "matter and is NOT a legal risk item.  Do NOT raise it as a red flag."
        ),
    },
    {
        "id": "standard_srl_governance",
        "title": "Standard S.r.l. / S.p.A. governance defaults",
        "description": (
            "Default governance provisions for S.r.l. or S.p.A. entities that simply "
            "follow Civil Code templates — including standard board composition, ordinary "
            "and extraordinary majority thresholds, and statutory withdrawal rights in "
            "the absence of post-closing triggers — are informational observations, "
            "not red flags."
        ),
    },
    {
        "id": "employment_tfr",
        "title": "TFR (Trattamento di Fine Rapporto) accruals",
        "description": (
            "TFR accruals are a statutory obligation under Art. 2120 c.c.  "
            "The mere existence of a TFR liability is NOT a red flag.  "
            "Flag only if: (a) there is specific evidence of underfunding or "
            "non-payment of amounts due, or (b) the TFR fund transfer to INPS "
            "or a pension fund creates a quantified post-closing liability "
            "not reflected in the data room."
        ),
    },
    {
        "id": "employment_holiday_balances",
        "title": "Accrued holiday / leave balances (ferie non godute)",
        "description": (
            "Unused vacation accruals are a normal employment cost and NOT a "
            "red flag.  Flag only if there is specific evidence of systematic "
            "failure to allow mandatory minimum leave under D.Lgs. 66/2003, "
            "or a balance materially understated in the accounts."
        ),
    },
    {
        "id": "ordinary_tax_position",
        "title": "Ordinary, timely-paid taxes",
        "description": (
            "The mere existence of ordinary tax obligations (IRES, IRAP, IVA, "
            "withholding taxes) that appear regularly declared and paid is NOT "
            "a red flag.  Flag only deviations: notified assessments, pending "
            "tax litigation, instalment plans, missed or deferred payments, "
            "credits requiring verification, or special regimes with exposure."
        ),
    },
    {
        "id": "employment_ccnl",
        "title": "CCNL applicability (Contratto Collettivo Nazionale di Lavoro)",
        "description": (
            "The existence or applicability of a CCNL is standard and mandatory "
            "for most Italian employers.  Do NOT flag the mere existence of a "
            "CCNL as a risk.  Flag only if there is specific evidence of: "
            "(a) wrong CCNL category or level applied, (b) pay below CCNL "
            "minimum rates, or (c) super-minimum benefits creating material "
            "undisclosed post-closing obligations."
        ),
    },
]

# ── Priority flags ────────────────────────────────────────────────────────────

PRIORITY: list[dict] = [
    {
        "id": "transfer_restrictions",
        "title": "Transfer restrictions on quotas / shares",
        "severity_floor": "high",
        "description": (
            "ALWAYS flag: clausola di gradimento (approval mechanism), clausola di "
            "prelazione (pre-emption rights), lock-up periods surviving closing, "
            "drag-along / tag-along absent or asymmetric, and any mechanism that "
            "could block or delay the contemplated transaction."
        ),
    },
    {
        "id": "pre_emption_rights",
        "title": "Pre-emption rights that affect the transaction",
        "severity_floor": "high",
        "description": (
            "ALWAYS flag: existing shareholders' pre-emption rights that have not been "
            "waived, any right of first refusal triggered by the deal structure, and "
            "whether the necessary consents or waivers have been obtained."
        ),
    },
    {
        "id": "minority_veto",
        "title": "Minority veto / reserved matters",
        "severity_floor": "medium",
        "description": (
            "ALWAYS flag: any provision giving a minority shareholder veto power over "
            "decisions material to the business (extraordinary operations, budget, "
            "key contracts, capex above threshold), reserved matters requiring "
            "super-majority or unanimity, and deadlock mechanisms."
        ),
    },
    {
        "id": "post_closing_control",
        "title": "Restrictions on post-closing control",
        "severity_floor": "high",
        "description": (
            "ALWAYS flag: governance structures that prevent the acquirer from "
            "exercising full control after closing, mandatory appointment rights "
            "retained by selling shareholders, and clauses that entrench minority "
            "shareholders post-closing."
        ),
    },
    {
        "id": "recesso",
        "title": "Withdrawal rights (recesso) triggered by post-closing actions",
        "severity_floor": "medium",
        "description": (
            "ALWAYS flag: statutory or contractual withdrawal rights triggered by "
            "post-closing corporate actions that are part of the acquirer's integration "
            "plan (merger, capital increase, change of business purpose, listing).  "
            "Note whether the liquidation value formula could be punitive."
        ),
    },
    {
        "id": "tax_assessments_litigation",
        "title": "Notified tax assessments and pending tax litigation",
        "severity_floor": "high",
        "description": (
            "ALWAYS flag: avvisi di accertamento or cartelle di pagamento "
            "notified to the target, pending proceedings before the tax courts, "
            "PVC (processi verbali di constatazione), and any evidence of unpaid "
            "or deferred taxes or social security contributions.  Quantify the "
            "exposure where the documents state it."
        ),
    },
    {
        "id": "tax_credits_and_losses",
        "title": "Tax credits used or transferred; carried-forward tax losses",
        "severity_floor": "medium",
        "description": (
            "ALWAYS flag: tax credits offset (compensati) or transferred (ceduti) "
            "— including building bonuses (superbonus), R&D and Industria 4.0 "
            "credits — whose validity has not been verified; and carried-forward "
            "tax losses or ACE surpluses whose survival after the change of "
            "control must be verified under artt. 84 and 172-173 TUIR."
        ),
    },
    {
        "id": "going_concern_financials",
        "title": "Auditor qualifications and going-concern doubts",
        "severity_floor": "high",
        "description": (
            "ALWAYS flag: a qualified, adverse or disclaimed auditor's opinion, "
            "going-concern emphasis paragraphs, losses triggering artt. 2446/2447 "
            "or 2482-bis/ter c.c., and covenant breaches or waivers evidenced in "
            "the financial statements or their annexes."
        ),
    },
    {
        "id": "change_of_control_contracts",
        "title": "Change-of-control clauses in material contracts",
        "severity_floor": "high",
        "description": (
            "ALWAYS flag: material supplier, customer, or financing agreements that "
            "terminate automatically or require counterparty consent on change of "
            "control; financing agreements with change-of-control events of default."
        ),
    },
]

# ── Jurisdiction context ──────────────────────────────────────────────────────

JURISDICTION_CONTEXT = (
    "The target company is an Italian entity.  Apply Italian corporate law "
    "(Codice Civile, D.Lgs. 231/2001, TUF where applicable) as the benchmark "
    "for what is standard versus unusual.  Materiality is assessed from the "
    "perspective of a strategic or financial acquirer completing an M&A transaction.\n\n"
    "EMPLOYMENT DOCUMENTS: Apply a cautious standard.  Employment contracts, "
    "payroll records, CCNL schedules, and HR policies rarely contain issues "
    "that materially affect transaction validity or share acquisition.  "
    "When analysing employment documents, default to the conclusion: "
    "'Based on the documents reviewed, no material red flags were identified' "
    "unless there is explicit evidence of: (a) systematic CCNL non-compliance, "
    "(b) significant undisclosed TFR or benefit liabilities, or "
    "(c) restrictive covenants that would prevent the target from operating "
    "normally post-closing."
)


# ── Public builder ────────────────────────────────────────────────────────────

def build_legal_rules_context() -> str:
    """Render the rule set as a prompt-ready string."""

    safe_lines = "\n".join(
        f"  • [{r['id']}] {r['title']}: {r['description']}"
        for r in SAFE_HARBOR
    )
    priority_lines = "\n".join(
        f"  • [{r['id']}] {r['title']} (minimum severity: {r['severity_floor']}): "
        f"{r['description']}"
        for r in PRIORITY
    )

    return (
        f"JURISDICTION CONTEXT:\n{JURISDICTION_CONTEXT}\n\n"
        f"SAFE HARBOUR — Do NOT raise these as red flags unless the provision "
        f"deviates from the statutory default or an actual breach is evidenced:\n"
        f"{safe_lines}\n\n"
        f"PRIORITY RISKS — Always identify and flag these when present in the findings:\n"
        f"{priority_lines}"
    )
