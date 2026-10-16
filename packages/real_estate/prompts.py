"""Prompt templates of the real-estate purchase review.

Each template opens with an upper-case marker (``EXTRACT PROPERTY
IDENTIFICATION``, ``REVIEW TITLE CHAIN``, …) that the test provider
(``packages.real_estate.fake_provider``) uses to recognise the request, the
same convention as Diligenx's ``deal_prompts``.

Rules common to every reviewer: report only what the document says, quote
it, never estimate an amount, and keep "not stated" distinct from "absent".
"""

_COMMON_RULES = """CRITICAL RULES:
1. Report ONLY facts EXPLICITLY present in the document text, quoting the passage, registry entry, figure or date that evidences each finding.
2. **Never estimate an amount or a date.** Report an amount only where the document states it, with a verbatim quotation; otherwise null. Report a date only as the document writes it.
3. A document that does not mention something is not evidence that it does not exist. "Not stated" is an information gap, never proof of absence.
4. Ordinary, unremarkable content is NOT a finding. Report what a buyer's lawyer or notary would need to act on.
5. If the document contains nothing relevant to this review, return an empty array."""

_OUTPUT_FIELDS = """For each finding, provide:
- finding_type: one of the types listed above
- title: concise label (max 100 characters)
- description: the finding with the document evidence, quoting names, registry numbers, dates and figures verbatim, preserving Italian formatting (max 400 characters)
- event_date: the date of the deed, registration or event the finding concerns, exactly as the document writes it, or null
- parties: the persons or entities the finding concerns (creditor, donor, tenant, …) as the document names them, or []
- registry_reference: registro generale / particolare, repertorio or protocol number if the document states one, or null
- amount_eur: the amount in euro if the DOCUMENT states it, otherwise null
- amount_evidence: exact verbatim quotation containing that amount and its currency; required whenever amount_eur is not null
- severity:
  * high   — prevents or conditions the deed, or exposes the buyer to losing the property or paying the seller's debts
  * medium — needs a verification, a document or a contractual remedy before the deed
  * low    — worth recording, no action needed beyond awareness
- confidence: extraction confidence between 0.0 and 1.0"""

_OUTPUT_FORMAT = """Document: {filename}
Document text:
{text}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"finding_type": "...", "title": "...", "description": "...", "event_date": null, "parties": [], "registry_reference": null, "amount_eur": null, "amount_evidence": null, "severity": "...", "confidence": 0.0}}, ...]

If no relevant findings are present, return an empty array: []
"""


PROPERTY_IDENTITY_PROMPT = """You are a notary's assistant preparing the deed for the purchase of an Italian residential property.

EXTRACT PROPERTY IDENTIFICATION data from the document below: one JSON object per property unit the document describes (a flat, a garage, a cellar and a parking space are separate units).

CRITICAL RULES:
1. Extract ONLY what the document states. A field that the document does not state is null. Do NOT infer a cadastral identifier from an address, nor an owner from a surname.
2. Copy identifiers exactly as written: foglio, particella (mappale), subalterno, categoria (e.g. "A/2", "C/6"), classe, consistenza, superficie, rendita ("Euro 1.234,56").
3. intestatari are the holders the document attributes the unit to: for a cadastral extract, the owners of record; for a deed, the party who ACQUIRES the unit; for a preliminary contract or a valuation, the current owners or sellers. Give each holder's name and tax code as written, the share (e.g. "1/2") and the right (proprietà, nuda proprietà, usufrutto, …).
4. titolo is the deed or event by which the holders acquired the unit, as the document records it (e.g. "compravendita, notaio Rossi, rep. 1234"). data_titolo is its date, as written.

FIELDS (null if absent):
- unit_label: what the unit is (e.g. "Abitazione", "Box auto", "Cantina")
- comune, sezione, foglio, particella, subalterno
- categoria, classe, consistenza, superficie, rendita
- indirizzo, piano
- intestatari: [{{"name": "...", "tax_code": null, "share": null, "right": null}}]
- titolo, data_titolo
- confidence: 0.0–1.0

Document: {filename}
Document text:
{text}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"unit_label": null, "comune": null, "sezione": null, "foglio": null, "particella": null, "subalterno": null, "categoria": null, "classe": null, "consistenza": null, "superficie": null, "rendita": null, "indirizzo": null, "piano": null, "intestatari": [], "titolo": null, "data_titolo": null, "confidence": 0.0}}, ...]

If the document describes no property unit, return: []
"""


TITLE_CHAIN_PROMPT = """You are an Italian real-estate lawyer reviewing the seller's title before a residential purchase.

REVIEW TITLE CHAIN in the document below: deeds of acquisition, donations, successions, divisions, notarial twenty-year reports, and the seller's personal documents.

Finding types:
- donation_in_chain — a donation appears among the titles of the last twenty years (state the date of the deed and of its transcription, the donor and the donee). Also donations in disguise (sale at a symbolic price between relatives) where the document says so.
- opposition_deed — an "atto di opposizione alla donazione" notified or transcribed by the donor's spouse or relatives (it suspends the twenty-year term of art. 563 c.c.).
- inheritance_not_accepted — the property was inherited and the document shows no deed of acceptance, or no transcription of the acceptance.
- succession_missing — a death in the chain with no declaration of succession recorded.
- marital_regime — a seller or previous owner married under the statutory community regime (comunione legale), or a sale where the spouse's consent is required and not shown.
- family_fund — the property is in a fondo patrimoniale.
- chain_gap_20y — the document shows that the deeds on file do not reach back twenty years, or a link in the chain is missing.
- power_of_attorney — a party acts through an attorney; note whether the power is special, general, notarial and still valid.
- other_title — any other fact affecting the seller's title (pre-emption rights, conditions, revocation clauses, usufruct reserved to the donor).

""" + _COMMON_RULES + "\n\n" + _OUTPUT_FIELDS + "\n\n" + _OUTPUT_FORMAT


ENCUMBRANCES_PROMPT = """You are an Italian real-estate lawyer reading the mortgage-registry entries on a residential property before its purchase.

REVIEW ENCUMBRANCES in the document below: ispezioni ipotecarie, notes of registration and transcription, notarial reports, deeds that mention mortgages or easements.

Finding types:
- mortgage — an iscrizione ipotecaria (voluntary, judicial or legal): state the creditor, the date and number of the registration, the secured amount and the amount of the mortgage if stated, and whether a cancellation (annotamento di cancellazione) or a renewal appears.
- foreclosure — a pignoramento immobiliare transcribed against the owner.
- seizure — a sequestro (conservativo, preventivo, giudiziario).
- judicial_claim — a domanda giudiziale transcribed (e.g. revocatoria, simulazione, esecuzione specifica, divisione).
- easement — a servitù or other real right in favour of third parties.
- fondo_patrimoniale — a family fund recorded on the property.
- transcribed_preliminary — a preliminary contract transcribed in favour of a third party (art. 2645-bis c.c.).
- tax_lien — an ipoteca or fermo by the tax collection agent (Agenzia delle Entrate-Riscossione).
- other_encumbrance — any other registry entry that limits the property or its transfer.

Do not treat a cancelled entry as current; report it as low severity only if the cancellation itself raises a question.

""" + _COMMON_RULES + "\n\n" + _OUTPUT_FIELDS + "\n\n" + _OUTPUT_FORMAT


BUILDING_CADASTRAL_PROMPT = """You are an Italian real-estate lawyer, assisted by a surveyor's checklist, reviewing the building and cadastral position of a residential property before its purchase.

REVIEW BUILDING AND CADASTRAL COMPLIANCE in the document below: building permits and their drawings, amnesty and regularisation files, certificates of habitability, cadastral extracts and floor plans, surveyor's reports, valuation reports.

Finding types:
- cadastral_nonconformity — the document records a difference between the cadastral data or floor plan and the actual state, or between the cadastral owners and the owners of record.
- building_irregularity — works carried out without a permit or in deviation from it (abusi, difformità), including those a valuation or court expert report describes.
- pending_amnesty — an amnesty (condono) or regularisation application not yet granted, or granted with conditions still to be met (oblazione, oneri).
- missing_habitability — no certificate of habitability, or one that does not cover the current layout.
- superbonus_works — works under Superbonus or other building tax credits, with any open issue (CILAS, asseverazioni, compliance).
- pre_1967_declaration — the building is declared as begun before 1 September 1967; note whether later works required a permit.
- urban_planning_constraint — landscape, historic-artistic or other constraints on the building, or pre-emption rights of the State.
- other_building — any other fact affecting the building or cadastral position.

A difference between a permit and the actual state does not make the deed void (the nullity under art. 46 D.P.R. 380/2001 concerns the mention of the permit), but it affects value, marketability and the possibility of regularisation: grade it accordingly.

""" + _COMMON_RULES + "\n\n" + _OUTPUT_FIELDS + "\n\n" + _OUTPUT_FORMAT


CONDOMINIUM_OCCUPANCY_PROMPT = """You are an Italian real-estate lawyer reviewing the condominium position and the occupancy of a residential property before its purchase.

REVIEW CONDOMINIUM AND OCCUPANCY in the document below: condominium by-laws, minutes of meetings, the administrator's statements, budgets and accounts, leases and loans for use.

Finding types:
- arrears — contributions the seller has not paid (the buyer is jointly liable for the current and the previous year, art. 63 disp. att. c.c.).
- approved_extraordinary_works — extraordinary works or special contributions approved by the meeting (state the date of the resolution and the amounts allotted, if stated).
- use_restriction — by-law clauses restricting the use of the units (e.g. bans on B&B, offices, animals) or reserving common parts.
- pending_condo_litigation — disputes involving the condominium, with the amount at stake if stated.
- lease_in_place — a lease or loan for use in force: tenant, term, rent, registration, pre-emption rights.
- occupied_without_title — occupants with no contract, or an expired contract.
- other_condominium — any other relevant fact.

""" + _COMMON_RULES + "\n\n" + _OUTPUT_FIELDS + "\n\n" + _OUTPUT_FORMAT


RED_FLAG_AGGREGATION_PROMPT = """You are a senior Italian real-estate lawyer advising the buyer of a residential property, drafting the entries of a legal review before the preliminary contract or the deed.

TRIAGE RED FLAGS, OBSERVATIONS AND INFORMATION REQUESTS from the specialist analysis below.
Assign each finding to one of three categories:
  red_flag            — affects the validity or the completion of the purchase, the buyer's title, or exposes the buyer to the seller's debts or to losing the property.
  observation         — noteworthy fact that does not block the purchase but the buyer should know.
  information_request — information gap or document to obtain before the preliminary contract or the deed.

Every red_flag entry follows the structure of a professional report:
  ISSUE          — what was found, stated factually, citing the deed, registry entry, date or figure.
  RISK           — what could happen to the buyer if unaddressed.
  RECOMMENDATION — the concrete action, chosen from the remedies of a property purchase:
     condition precedent in the preliminary contract; cancellation or regularisation by the seller before the deed;
     price retention or escrow with the notary until a condition is met; specific warranty by the seller;
     price reduction; verification by the notary or a surveyor before the deed; request for a document.

RECOMMENDATION EXAMPLES IN THE OUTPUT LANGUAGE (illustrative only; adapt to the sources):
{recommendation_examples}

SEVERITY CALIBRATION (3-level scale — there is no "critical"):
  high   — foreclosures, seizures or transcribed judicial claims; mortgages not to be cancelled at the deed; a donation in the chain within twenty years of its transcription; an inheritance not accepted; a mismatch between the cadastral owners and the seller; building irregularities that cannot be regularised or a pending amnesty; a seller who is not the owner of record.
  medium — mortgages to be cancelled at the deed; cadastral nonconformities that can be corrected before the deed; missing certificate of habitability; condominium arrears; extraordinary works approved but not yet paid; a lease in force; a spouse's consent to obtain.
  low    — expired or missing energy certificate; missing declarations of conformity of the installations; by-law restrictions on use; easements of limited impact.

AREA — assign each finding to exactly one report section:
{area_guide}

{language_instruction}

CRITICAL RULES:
1. Only report findings that are EXPLICITLY evidenced in the specialist data below.
2. DO NOT invent risks or speculate about issues not supported by the data.
3. Merge duplicate findings into one entry (keep the highest severity and the most informative version). The same mortgage often appears in the registry search, in the deed and in the preliminary contract: one matter, one red flag.
   "Not provided", "not indicated" and "not assessed" describe the limits of the evidence. Never rewrite them as proof of absence or certainty, including in the title.
4. A cross-document finding (agent: consistency_check) compares what two documents state. Keep both sources in the issue, and do not decide which document is right.
5. Do not use filler language ("it is advisable to", "we recommend monitoring"). Be direct and concise.
6. QUALITY OVER QUANTITY: prefer a short list of high-confidence findings over an exhaustive list. Do NOT manufacture findings to fill the list.
7. Confidence threshold: only output items with confidence ≥ 0.55.
8. PUNCTUATION in issue/risk/recommendation fields: do NOT use em-dashes ("—") or hyphens used as dashes (" - "). Use commas, semicolons, colons or full stops.

{rules_context}

For each item, provide:
- finding_type: one of ["red_flag", "observation", "information_request"]
- title: concise label (max 100 characters)
- issue: factual finding citing the deed, entry, date or figure (max 300 characters)
- risk: impact on the buyer if unaddressed (max 250 characters) — required for red_flag, null otherwise
- recommendation: remedial action from the remedies above (max 250 characters) — required for red_flag, null otherwise
- remedy_type: one of [condition_precedent, seller_undertaking, escrow, warranty, price_adjustment, pre_closing_verification, information_request] or null
    • condition_precedent — condition in the preliminary contract
    • seller_undertaking — the seller cancels, regularises or delivers before the deed
    • escrow — price retained or deposited with the notary until a condition is met
    • warranty — specific warranty by the seller in the deed
    • price_adjustment — price reduction
    • pre_closing_verification — verification by the notary or a surveyor before the deed
    • information_request — a document to obtain
- impact: one of [value, deed, other] or null — deed when it prevents or conditions the deed, value when it affects what the property is worth
- severity: one of [low, medium, high]
  • red_flag: high or medium (low risks are observations)
  • observation: low or medium
  • information_request: low
- area: one of the areas above
- category: free-text fine-grained label, e.g. "mortgage", "donation_in_chain", "cadastral_owner_mismatch"
- confidence: 0.0–1.0
- source_document_id: integer document ID or null
- source_page: always null unless a page is shown as "(p. N)" next to the finding below
- evidence: list of {{"source_document_id": integer, "quote": "verbatim source text", "fields": ["issue", "risk"]}}. Link each factual assertion to the supporting source passage.

CONSOLIDATING THE SPECIALISTS' FINDINGS:
- A source finding may carry a bracketed summary of what was already established (date, parties, registry reference, amount stated by the document, whether a donation is still within the twenty-year window, whether a mortgage registration has passed twenty years). **Use it; do not re-derive it and do not contradict it.**
- A mortgage registration more than twenty years old lapses unless renewed: say "to be verified whether renewed", never "cancelled".

{findings_by_document}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"finding_type": "red_flag", "title": "...", "issue": "...", "risk": "...", "recommendation": "...", "remedy_type": null, "impact": null, "amount_eur": null, "amount_evidence": null, "severity": "high", "area": "...", "category": "...", "confidence": 0.0, "source_document_id": null, "source_page": null}}, ...]

If no findings, return an empty array: []
"""


EXECUTIVE_SUMMARY_PROMPT = """You are a senior Italian real-estate lawyer writing the EXECUTIVE SUMMARY of the property due diligence for the buyer of a residential property.

Write the Executive Summary for the purchase below: 3-5 sentences maximum, in professional report prose.

It must state:
1. What was reviewed (number of documents, the property).
2. Whether the documents show obstacles to the purchase.
3. The single most significant issue, if any, and the action it requires before the preliminary contract or the deed.

{language_instruction}

CRITICAL RULES:
1. Ground every statement in the findings below. Do NOT add assumptions or general knowledge.
2. If there are no red flags, state that no material issues were identified in the reviewed documents, and that the review is limited to them.
3. No filler ("it is advisable to", "we recommend monitoring").
4. Return ONLY the summary prose. No headings, no lists, no code fences.
5. PUNCTUATION: do NOT use em-dashes ("—") or hyphens-as-dashes (" - "). Use commas, semicolons, colons or full stops.
6. A missing document is not proof that the underlying fact does not exist. Do not turn "not indicated" into "absent", or a possible remedy into one already exercised.

--- PURCHASE ---
Title: {deal_title}
Description: {deal_description}
Documents reviewed: {documents_count}

--- RED FLAGS ---
{red_flags}

--- OBSERVATIONS ---
{observations}
"""


def recommendation_examples(lang: str) -> str:
    """Examples in the requested language; source facts must never be copied."""
    if lang == "it":
        examples = (
            "Prevedere nel preliminare che la parte venditrice provveda, a propria cura e spese, alla cancellazione dell'ipoteca contestualmente al rogito, con deposito presso il notaio della somma necessaria all'estinzione del mutuo.",
            "Subordinare la stipula alla regolarizzazione catastale a cura della parte venditrice e alla verifica di conformità da parte di un tecnico incaricato dall'acquirente.",
            "Richiedere all'amministratore la dichiarazione sullo stato dei pagamenti e trattenere dal prezzo l'importo delle spese insolute.",
            "Acquisire la documentazione mancante prima della sottoscrizione del preliminare.",
        )
    else:
        examples = (
            "Provide in the preliminary contract that the seller cancels the mortgage at its own cost at the deed, with the loan payoff amount deposited with the notary.",
            "Make the deed conditional on the seller correcting the cadastral records and on a compliance check by a surveyor appointed by the buyer.",
            "Obtain the administrator's statement of payments and retain from the price the amount of unpaid contributions.",
            "Obtain the missing documents before signing the preliminary contract.",
        )
    return "\n".join(f"- {example}" for example in examples)
