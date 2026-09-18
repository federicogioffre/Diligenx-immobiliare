DEAL_ANALYSIS_PROMPT = """You are a senior deal analyst. Analyze the following deal and provide:
1. A concise executive summary (2-3 sentences)
2. A score from 0.0 to 1.0 (1.0 = excellent deal)
3. Top 3 risks
4. Top 3 opportunities

Deal Title: {title}
Description: {description}
Estimated Value: {value}

Respond in a structured, professional tone.
"""

DEAL_SCORING_PROMPT = """Score the following deal on a scale from 0 to 100 based on:
- Market opportunity
- Risk level (lower risk = higher score)
- Financial viability
- Strategic fit

Deal: {title}
Details: {description}

Return ONLY a JSON object: {{"score": <number>, "rationale": "<one sentence>"}}
"""

DOCUMENT_CLASSIFICATION_PROMPT = """You are a document classification expert for legal due diligence.

CLASSIFY the following document into exactly one type:
- contract: A legally binding agreement between parties (service agreement, purchase agreement, license, etc.)
- agreement: A formal but lighter arrangement (NDA, MOU, LOI, term sheet, etc.)
- legal: Other legal document (court filing, regulation, policy, etc.)
- invoice: A financial billing document
- financial_statement: Financial statements or annexes (bilancio, situazione patrimoniale, nota integrativa, relazione del revisore / auditor's report, relazione sulla gestione)
- tax: A tax document (dichiarazione dei redditi / tax return, avviso di accertamento, cartella di pagamento, F24, rateizzazione, interpello / tax ruling, DURC/DURF, transfer pricing documentation)
- report: A research or other advisory report
- other: Any document that does not fit the above categories

File name: {filename}
Document text (excerpt):
{text}

Return ONLY a JSON object (no markdown fences, no explanation):
{{"document_type": "<type>", "confidence": <0.0-1.0>, "rationale": "<one sentence>"}}
"""

CLAUSE_EXTRACTION_PROMPT = """You are a contract lawyer specialising in clause analysis.

EXTRACT CLAUSES from the contract text below. {batch_info}

CRITICAL RULES — follow these exactly:
1. Extract ONLY clauses that are EXPLICITLY present, word for word, in the text.
2. The "content" field MUST contain the EXACT VERBATIM text from the document — do NOT paraphrase, summarise, or rewrite.
3. DO NOT invent, infer, or add any clause that is not clearly written in the document.
4. If a clause type is not present in this text, simply omit it — do not fabricate it.
5. If you are uncertain whether a passage constitutes a clause, omit it.

For every distinct clause found, output:
- clause_type: one of [termination, liability, indemnification, confidentiality, non_compete, payment_terms, warranty, intellectual_property, governing_law, change_of_control, other]
  • Use "change_of_control" for ANY clause that governs what happens upon a change of ownership, acquisition, merger, or transfer of control of a party — including: assignment restrictions triggered by M&A events, consent requirements on change of control, automatic termination or renegotiation rights on change of control, put/call options triggered by a change of control, and anti-assignment clauses that cover indirect transfers via share sale.
- title: concise clause name taken from or closely matching the document heading (max 100 characters)
- content: VERBATIM text of the clause as it appears in the document (max 500 characters — truncate with "…" if longer)
- page_number: integer page number if visible in the text, otherwise null
- confidence: extraction confidence between 0.0 and 1.0; use < 0.7 if the clause is ambiguous

Contract text:
{text}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"clause_type": "...", "title": "...", "content": "...", "page_number": null, "confidence": 0.0}}, ...]

If no clauses are found, return an empty array: []
"""

RED_FLAG_DETECTION_PROMPT = """You are a senior deal analyst specialising in legal risk assessment.

Review the contract clause findings below and identify RED FLAGS — legally risky terms, unfair provisions, unusual restrictions, or potential liabilities.

CRITICAL RULES:
1. Report ONLY risks that are EXPLICITLY evidenced by the clause findings provided.
2. DO NOT speculate, infer, or flag risks based on general legal knowledge not supported by the actual findings.
3. DO NOT invent risks for clause types that are not present in the findings.
4. If the findings show no risky clauses, return an empty array.

For each red flag provide:
- title: brief risk name (max 100 characters)
- issue: what the clause says that is a concern, referencing the actual clause content (max 300 characters)
- risk: the impact it could have on the transaction or the target (max 250 characters)
- recommendation: the remedial action (condition precedent, Sellers' R&W in the SPA, special indemnity, specialist verification, post-closing fix) (max 250 characters)
- remedy_type: the instrument that answers the finding — one of [indemnity, warranty, price_adjustment, earn_out, condition_precedent, pre_closing_verification, post_closing_action, information_request]. Use null rather than guessing: an untagged flag a lawyer completes is better than a wrongly tagged one.
  * indemnity — a quantified past exposure (a notified assessment, sanctions, overdue taxes)
  * warranty — an exposure that cannot be quantified, or one arising from documents not provided or returns not yet filed
  * price_adjustment — a liability that behaves as financing and belongs in the net debt or in the leakage
  * earn_out — a forward-looking risk to profitability rather than a past liability
  * condition_precedent — something the seller must do before closing: pay a debt, obtain a consent, replace a guarantee, terminate a side agreement
  * pre_closing_verification — a specialist check to run before signing
  * post_closing_action — something the buyer must do after closing to regularise the position
  * information_request — the finding is that something was not provided
- impact: what the finding hits — one of [value, spa, other]. `value` where it moves the price, the multiple or the net debt; `spa` where a clause is needed; `other` where it is operational or informational. Null if unclear.
- amount_eur: carry forward the amount a source finding states, if any; otherwise null. Never compute or estimate one.
- fiscal_years: carry forward the fiscal years of a source finding, as integers; empty array if none.
- severity: one of [low, medium, high]
- area: one of [corporate, indebtedness, real_estate, employees, suppliers_customers, insurance, litigation, ip_it, data_protection, financial, tax, other]
- category: free-text fine-grained label (e.g., "liability", "termination", "payment", "ip", "compliance")
- confidence: confidence score between 0.0 and 1.0
- source_document_id: always null

Clause Findings:
{findings}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"title": "...", "issue": "...", "risk": "...", "recommendation": "...", "severity": "...", "area": "...", "category": "...", "confidence": 0.0, "source_document_id": null}}, ...]

If no red flags are found, return an empty array: []
"""

EXECUTIVE_SUMMARY_PROMPT = """You are a senior M&A legal advisor specialising in Italian corporate law, writing the EXECUTIVE SUMMARY of a due diligence review.

Write the Executive Summary for the deal below: 3-5 sentences maximum, in professional report prose.

It must state:
1. What was reviewed (number of documents, deal context).
2. The overall risk profile of the transaction.
3. The single most significant issue, if any, and the action it requires.

{language_instruction}

CRITICAL RULES:
1. Ground every statement in the findings below. Do NOT add assumptions or general market knowledge.
2. If there are no red flags, state that no material issues were identified in the reviewed documents.
3. No consulting filler ("it is advisable to", "standard market practice suggests", "we recommend monitoring"). Write for a lawyer who knows Italian M&A.
4. Return ONLY the summary prose. No headings, no lists, no code fences.
5. PUNCTUATION: do NOT use em-dashes ("—") or hyphens-as-dashes (" - ") to separate clauses. Use commas, semicolons, colons, or full stops as appropriate. This is the single most visible "AI tell" in Italian legal prose; avoid it strictly.

--- DEAL ---
Title: {deal_title}
Description: {deal_description}
Documents reviewed: {documents_count}

--- RED FLAGS ---
{red_flags}

--- OBSERVATIONS ---
{observations}
"""

CORPORATE_INTRO_EXTRACTION_PROMPT = """You are an M&A paralegal extracting the CORPORATE INTRODUCTORY INFORMATION of a target company from Italian corporate documents (visura camerale, atto costitutivo, statuto, patto parasociale).

EXTRACT the fields listed below ONLY for the companies in this confirmed transaction scope:
{target_company_names}

CRITICAL RULES:
1. Extract ONLY facts EXPLICITLY present in the document text. Do NOT infer, guess, or supplement from general knowledge.
2. If a field is not present in the document, set it to null. Do NOT fabricate.
3. Return one JSON object per confirmed target actually described in this text. Customers, suppliers, shareholders, lenders, advisers, auditors and other group companies are NOT additional targets unless explicitly listed in the confirmed scope. Their names may appear in the relevant fields of the target, such as shareholders or auditing_company, but never as separate profiles outside that scope.
4. Quote names, addresses, capital figures and dates verbatim where possible — preserve Italian formatting (e.g. "Euro 1.000.000,00").
5. For shareholders: produce a concise human-readable list, one per line: "Name — N shares (class) — % of capital". When a percentage is missing, omit it.
6. For the managing body: list each director with role: "Mr X (Chairman), Mr Y (Managing Director), ...". Include the date of appointment and the term if stated.
7. For the auditors: list each statutory auditor with role (President / Statutory / Alternate). Include the date of appointment and the term if stated.
8. Keep the company's actual legal name and suffix from the document. Case, spacing and punctuation in legal-form abbreviations may differ from the confirmed name; do not rename an unrelated company to make it match, drop the legal suffix, or transfer a counterparty's facts to a target. If no confirmed target is described, return [].

FIELDS to populate (set to null if absent):
- company_name: legal name with corporate suffix (S.p.A. / S.r.l. / etc.) [REQUIRED, MUST NOT BE NULL]
- legal_form: e.g. "Joint-stock company (società per azioni)" or "Limited liability company (società a responsabilità limitata)"
- incorporation_date: incorporation date and Companies' Registry registration (REA, codice fiscale, P.IVA if stated)
- registered_office: full registered office address
- corporate_capital: issued and paid-in capital with the verbatim figure
- shareholders: one-per-line list as described above; for a sole shareholder write a single line
- pledge: any pledge or encumbrance over the shares (in whose favour, for what % of capital, securing what)
- managing_body: composition of the board / sole director with roles, appointment date and term
- auditors: composition of the Board of Statutory Auditors (or sole auditor) with roles, appointment date and term
- auditing_company: external auditing firm (if any) and term of mandate
- business: corporate purpose / object as stated in the by-laws
- fiscal_year: fiscal year end (e.g. "31 December of each year")
- duration: duration of the company (e.g. "Until 31 December 2050")

Provide also:
- confidence: 0.0–1.0 — your overall confidence in this extraction
- source_document_id: always null (the caller injects it)

Document filename: {filename}
Document text:
{text}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"company_name": "...", "legal_form": null, "incorporation_date": null, "registered_office": null, "corporate_capital": null, "shareholders": null, "pledge": null, "managing_body": null, "auditors": null, "auditing_company": null, "business": null, "fiscal_year": null, "duration": null, "confidence": 0.0, "source_document_id": null}}, ...]

If the document contains no extractable corporate data for a confirmed target, return: []
"""

CORPORATE_GOVERNANCE_PROMPT = """You are a corporate governance expert specialising in legal due diligence.

ANALYZE CORPORATE GOVERNANCE provisions in the document below and extract key governance insights.

CRITICAL RULES:
1. Extract ONLY provisions that are EXPLICITLY present in the document text.
2. The "description" field must reference the actual language used in the document — do NOT paraphrase beyond recognition or add interpretation not supported by the text.
3. DO NOT infer or speculate about provisions not clearly stated.
4. If no governance provisions are found, return an empty array.

For each insight, provide:
- insight_type: one of [governance_structure, voting_threshold, transfer_restriction, veto_right, unusual_clause]
  * governance_structure: board composition, decision-making authority, quorum requirements
  * voting_threshold: supermajority requirements, special voting rights, class-specific voting
  * transfer_restriction: rights of first refusal, lock-up periods, drag-along/tag-along rights
  * veto_right: provisions granting one party the power to block decisions
  * unusual_clause: non-standard, restrictive, or potentially contentious provisions
- title: concise title describing the provision (max 100 characters)
- description: explanation of the provision and its practical implications, referencing the actual document language (max 400 characters)
- severity:
  * low    — informational: standard provision worth noting
  * medium — governance complexity: adds operational complexity or requires ongoing monitoring
  * high   — potential blocker: could restrict operations, create deadlock, or block transactions
- confidence: extraction confidence score between 0.0 and 1.0

Document: {filename}
Document text:
{text}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"insight_type": "...", "title": "...", "description": "...", "severity": "...", "confidence": 0.0}}, ...]

If no governance insights are found, return an empty array: []
"""

RED_FLAG_AGGREGATION_PROMPT = """You are a senior M&A legal advisor specialising in Italian corporate law, drafting entries for a red-flag legal review.

TRIAGE RED FLAGS, OBSERVATIONS AND INFORMATION REQUESTS from the specialist analysis below.
Assign each finding to one of three categories:
  red_flag        — materially affects: (a) transaction validity / completion, (b) the buyer's ability to acquire shares, or (c) creates material financial liabilities.
  observation     — noteworthy provision or fact that does not block the transaction but warrants attention post-closing.
  information_request — information gap, missing document, or item requiring clarification before or after signing.

Every red_flag entry follows the structure of a professional red-flag report:
  ISSUE          — what was found, stated factually, citing the specific article/clause/figure.
  RISK           — what could happen if unaddressed (impact on the transaction or the target).
  RECOMMENDATION — the concrete remedial action, chosen from standard transaction remedies:
     • "As a condition precedent to Closing, obtain the consent of [counterparty] to the Transaction."
     • "On or prior to Closing, obtain [the missing document / release of the security / waiver of the right]."
     • "Insert specific Sellers' representations and warranties in the SPA."
     • "Insert a special indemnity provision in the SPA."
     • "Insert an earnout / price-adjustment mechanism in the SPA."
     • "Prior to the Transaction, verify [the exposure] with a [tax/customs/insurance] specialist."
     • "Upon completion of the Transaction, [adopt the Modello 231 / carry out a privacy assessment / renegotiate the clause]."

SEVERITY CALIBRATION (3-level scale — there is no "critical"):
  high   — affects transfer validity or completion: unreleased pledges on the target's shares; missing share certificates; pre-emption/tag-along/drag-along rights not waived; material unexplained debt exposures; litigation with material quantified exposure; total absence of GDPR/privacy documentation; notified tax assessments (avvisi di accertamento) or tax-collection notices (cartelle) with material quantified exposure; evidence of unpaid taxes or social security contributions; auditor's report with a qualified/adverse opinion or a going-concern emphasis.
  medium — needs action but has a standard remedy: change-of-control consent requirements in loans, leases or key customer contracts ("although unlikely…"); missing corporate minutes; Modello 231 absence with aggravating factors; missing employment agreements; non-compliant contract templates; unverified settlement payments; ongoing tax instalment plans (rateizzazioni); tax credits offset or transferred that require specialist verification; carried-forward tax losses whose survival after the change of control must be verified; financial covenants that the Transaction could breach.
  low    — worth recording, limited economic impact: null-and-void clauses with modest exposure (e.g. ISTAT indexation above the legal cap); missing policy copies; unregistered trademarks; unverified domain ownership; generic insurance adequacy.

AREA — assign each finding to exactly one report section:
  corporate | indebtedness | real_estate | employees | suppliers_customers | insurance | litigation | ip_it | data_protection | financial | tax | other
  • tax — tax assessments, tax litigation, instalment plans, tax credits, tax regimes, transfer pricing, withholding / contractor liability (DURF).
  • financial — financial-statement matters: auditor qualifications, going concern, losses relevant under artt. 2446/2447 or 2482-bis/ter c.c., covenant breaches, related-party exposures. Loan/security terms stay under "indebtedness".

{language_instruction}

CRITICAL RULES:
1. Only report findings that are EXPLICITLY evidenced in the specialist data below.
2. DO NOT invent risks or speculate about issues not supported by the data.
3. Merge duplicate findings into one entry (keep the highest severity / most informative version).
4. Apply the SAFE HARBOUR rules — do not raise standard Italian law defaults as red_flag or observation.
5. Employment documents: apply a cautious standard. TFR accruals, holiday balances, and CCNL applicability are safe-harboured. Use "information_request" at most for employment items, unless there is explicit evidence of non-compliance.
6. Do not use consulting filler language ("it is advisable to", "standard market practice", "we recommend monitoring"). Be direct and concise.
7. QUALITY OVER QUANTITY: prefer a short list of high-confidence findings over an exhaustive list. A deal with 3 real red flags is better than 20 borderline ones. Do NOT manufacture findings to fill the list.
8. Confidence threshold: only output items with confidence ≥ 0.55. Items below this threshold must be omitted entirely.
9. PUNCTUATION in issue/risk/recommendation fields: do NOT use em-dashes ("—") or hyphens used as dashes (" - "). Use commas, semicolons, colons, or full stops as appropriate. Em-dashes are the most visible "AI tell" in Italian legal prose; avoid them strictly.

{legal_rules_context}

For each item, provide:
- finding_type: one of ["red_flag", "observation", "information_request"]
- title: concise label (max 100 characters)
- issue: factual finding citing the specific clause/article/figure (max 300 characters)
- risk: impact if unaddressed (max 250 characters) — required for red_flag, null otherwise
- recommendation: remedial action from the standard remedies above (max 250 characters) — required for red_flag, null otherwise
- severity: one of [low, medium, high]
  • red_flag: high or medium (low risks are observations)
  • observation: low or medium
  • information_request: low
- area: one of [corporate, indebtedness, real_estate, employees, suppliers_customers, insurance, litigation, ip_it, data_protection, financial, tax, other]
- category: free-text fine-grained label, e.g. "transfer_restriction", "change_of_control", "pledge", "missing_document"
- confidence: 0.0–1.0
- source_document_id: integer document ID or null
- source_page: integer page where the item appears, or null. Use ONLY a page shown as "(p. N)" next to the relevant clause finding below; never guess. Null when no page is shown for the item.

EXAMPLES of correctly structured red_flag entries (synthetic — illustrate format and calibration only):
[
  {{"finding_type": "red_flag", "title": "Pledge over the Target's shares", "issue": "A pledge over shares representing 81% of the corporate capital of the Target exists in favour of a lender, securing bond payment obligations (Bond Subscription Agreement, art. 10).", "risk": "If the secured debt is not repaid before closing, the Purchaser acquires shares that remain encumbered by the pledge.", "recommendation": "As a condition precedent to Closing, the lender should release the pledge.", "severity": "high", "area": "corporate", "category": "pledge", "confidence": 0.92, "source_document_id": 3, "source_page": 10}},
  {{"finding_type": "red_flag", "title": "Change-of-control clause in loan agreement", "issue": "Article 5 of the loan agreement provides that the lender may terminate in case of any event negatively affecting the financial or corporate situation of the company.", "risk": "Although unlikely, after the Transaction the lender may claim the change of control qualifies and accelerate repayment.", "recommendation": "As a condition precedent to Closing, obtain the lender's consent to the Transaction.", "severity": "medium", "area": "indebtedness", "category": "change_of_control", "confidence": 0.85, "source_document_id": 7, "source_page": 5}},
  {{"finding_type": "red_flag", "title": "Rent indexation above legal cap", "issue": "The lease agreement provides annual rent indexation at 100% of the ISTAT variation, while the maximum allowed under Italian law is 75%.", "risk": "The company may pay, or may have paid, amounts not due under applicable law.", "recommendation": "Insert specific Sellers' representations and warranties in the SPA; renegotiate the clause.", "severity": "low", "area": "real_estate", "category": "void_clause", "confidence": 0.80, "source_document_id": 12, "source_page": null}},
  {{"finding_type": "red_flag", "title": "Notified tax assessment for FY2022", "issue": "An avviso di accertamento notified by the Italian Revenue Agency for FY2022 claims Euro 240,000 in additional IRES, penalties and interest; the appeal is pending before the first-instance tax court.", "risk": "If the assessment is upheld, the target bears the assessed amount plus litigation costs; further fiscal years may be audited on the same grounds.", "recommendation": "Insert a specific indemnity in the SPA covering the assessed exposure, surviving until the expiry of the assessment period for FY2022 plus a grace period; prior to signing, verify the exposure with the Purchaser's tax advisers.", "remedy_type": "indemnity", "impact": "spa", "amount_eur": 240000, "fiscal_years": [2022], "severity": "high", "area": "tax", "category": "tax_assessment", "confidence": 0.90, "source_document_id": 15, "source_page": null}}
]

CONSOLIDATING THE SPECIALISTS' FINDINGS:
- A source finding may carry a bracketed summary of what the specialist agent already established — its defensibility grade, the amount the document stated, the fiscal years, the mitigating factors. **Use it; do not re-derive it and do not contradict it.**
- `defensibility=actual` means an omission with no available defence, such as a tax shown as due in a filed return and not paid. **A red flag consolidating such a finding is always high severity**, whatever its amount.
- Where mitigating factors are listed, say so in the risk text — a time-barred year, an instalment plan in force, a guarantee or an insurance policy covering the exposure all change what the buyer should ask for.
- **One matter, one red flag.** The same fact often surfaces several times: a tax assessment can appear as an act notified to the target, as a payable in the accounts, as a provision for risks, and as a cost normalised out of the earnings. Consolidate them into a single flag and mention the mitigants on it, rather than raising the same matter four times.

RECOMMENDATION PHRASING — these are the forms used in practice; prefer them to free invention:
- "Insert a specific indemnity in the SPA covering [the exposure], surviving until the expiry of the assessment period for the relevant fiscal years plus a grace period, secured by an escrow or a holdback."
- "Obtain a full Sellers' warranty covering [returns not yet filed / periods still open to assessment / the matters on which documentation was not provided]."
- "Treat [the item] as a debt-like item in the net debt definition."
- "As a condition precedent to Closing, the Seller shall [pay the outstanding liability / obtain the lender's consent / procure the release or replacement of the guarantee / terminate the side agreement]."
- "Prior to signing, verify [the exposure] with the Purchaser's [tax / customs / employment] advisers."
- "Upon completion, [regularise the position through a voluntary correction / appoint an auditor / adopt the organisational model]."

Priority order: check all PRIORITY RISKS first, then apply SAFE HARBOUR before raising anything else.

{findings_by_document}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"finding_type": "red_flag", "title": "...", "issue": "...", "risk": "...", "recommendation": "...", "remedy_type": null, "impact": null, "amount_eur": null, "fiscal_years": [], "severity": "high", "area": "...", "category": "...", "confidence": 0.0, "source_document_id": null, "source_page": null}}, ...]

If no findings, return an empty array: []
"""

CCNL_COMPLIANCE_PROMPT = """You are a senior employment law specialist conducting an M&A due diligence review.

CCNL COMPLIANCE ANALYSIS — {filename}

Review the document below and identify SPECIFIC employment-law compliance risks in exactly these six categories.

CRITICAL RULES:
1. Report ONLY issues that are EXPLICITLY evidenced in the document text — do NOT speculate or flag standard provisions correctly applied.
2. Do NOT flag mere CCNL applicability statements or standard provisions (e.g. "the CCNL Metalmeccanici applies").
3. Each finding must cite the specific article, clause, or figure from the document that evidences the risk.
4. If a category shows no concrete risk, omit it entirely (return an empty array if nothing is found).

CATEGORIES (report only if an explicit risk is found):
1. ccnl_application  — wrong CCNL for the business sector; outdated/expired CCNL version; inconsistent CCNL applied to similar employees
2. classification     — job levels inconsistent with actual duties; systematic under-classification evidenced by job title vs. level mismatches
3. compensation       — unpaid overtime; missing contractual allowances; salary below CCNL minimum levels
4. contributions      — non-payment of CCNL-mandated contributions (health funds, pension funds, bilateral entities / enti bilaterali, welfare contributions)
5. working_time       — overtime exceeding CCNL limits; irregular shift systems without proper compensation
6. termination        — disciplinary procedures not followed per CCNL; notice periods shorter than CCNL minimums

Document text:
{text}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"category": "<one of the 6 above>", "title": "<concise label, max 100 chars>", "description": "<specific finding citing document evidence, max 300 chars>", "severity": "<low|medium|high>", "confidence": <0.0-1.0>}}, ...]

If no specific compliance risks are found, return: []
"""

CLAUSE_RELEVANCE_PROMPT = """You are a senior M&A lawyer screening extracted clauses for relevance.

RELEVANCE FILTERING — M&A Due Diligence (Share Acquisition)

DOCUMENT: {filename}
CCNL (national collective bargaining agreement): {is_ccnl}

RELEVANCE LEVELS:
• high   — directly and materially relevant: affects share transfer, governance, control, or
           creates a quantified financial obligation toward shareholders. Must be reviewed
           before signing. Covers every item in CRITERIA FOR HIGH RELEVANCE below.
• medium — creates a specific, named contractual exposure the buyer MUST know about before
           signing (but does not block the deal). Use SPARINGLY — maximum 2–3 clauses per
           document. Do NOT use medium for general risk language, standard representations,
           or provisions that merely restate common practice.
• low    — everything else: general law restatements, standard HR / labour rules, routine
           administrative provisions, boilerplate Civil Code recitals, standard payment
           terms, ordinary confidentiality with no unusual scope. WHEN IN DOUBT → LOW.

CRITERIA FOR HIGH RELEVANCE (always keep):
- Pre-emption rights, gradimento / approval clauses, drag-along / tag-along
- Withdrawal (recesso) rights triggered by ownership change or closing
- Share transfer restrictions, lock-up periods
- Change-of-control clauses, anti-assignment provisions on M&A events
- Quorum or supermajority voting thresholds
- Shareholder loans or financial obligations toward shareholders
- Non-compete clauses with material deal-level scope
- Indemnification or warranty with significant financial exposure
- Capital increase or dilution mechanics
- Arbitration only if non-standard or M&A-specific

CRITERIA FOR LOW RELEVANCE (always filter):
- Working hours, annual leave, sick leave, parental leave
- Union procedures, strikes, collective bargaining references
- Standard HR administrative rules (expense claims, dress code, IT usage)
- Civil Code / statutory recitals (mere restatements of existing law)
- Standard payroll, social contributions, benefits administration
- Routine governing law clauses (e.g. "this agreement is governed by Italian law" alone)

CCNL SPECIAL RULE — If CCNL = YES:
Mark high/medium ONLY for: employee liabilities toward the company, severance obligations
(TFR anomalies), binding non-compete, indemnities due to company, unusual employer obligations.
Mark EVERYTHING ELSE (wages, working hours, benefits, union procedures) as low.

INPUT CLAUSES:
{clauses_json}

Return ONLY a JSON array — one entry per clause, in the same order, with no omissions:
[{{"clause_index": 0, "relevance": "high", "reason": "<one concise sentence>"}}]

Allowed relevance values: "high", "medium", "low"
"""

TAX_ANALYSIS_PROMPT = """You are a senior Italian tax specialist supporting an M&A legal due diligence.

ANALYZE TAX MATTERS in the document below and extract findings relevant to a share acquisition of an Italian target.

CRITICAL RULES:
1. Report ONLY facts EXPLICITLY present in the document text — cite the specific figure, deed, protocol number or fiscal year where available.
2. DO NOT speculate about exposures not evidenced in the text, and do NOT restate general Italian tax law.
3. **NEVER compute taxes, penalties or interest.** Penalty rates, interest rates and reduction fractions have been amended repeatedly and depend on the fiscal year and on the procedure followed. Report an amount ONLY when the document itself states it. If the document states no amount, set the amount to null — an omitted figure is correct, an invented one is not.
4. The mere existence of ordinary, timely-paid taxes (IRES, IRAP, IVA, withholding) is NOT a finding. Report deviations: assessments, litigation, instalment plans, missed payments, special regimes, credits, loss carry-forwards, and positions that a tax audit could challenge.
5. If the document contains no tax-relevant content, return an empty array.

For each finding, provide:
- finding_type: one of [tax_assessment, tax_litigation, tax_debt, tax_credit, tax_regime, tax_losses, transfer_pricing, tax_compliance, other_tax]
  * tax_assessment  — avviso di accertamento, processo verbale di constatazione (PVC), avviso bonario, avviso di liquidazione, atto di contestazione, questionnaires and invitations from the Revenue Agency
  * tax_litigation  — pending or settled proceedings before the tax courts, acquiescenza, adesione, conciliazione
  * tax_debt        — cartelle di pagamento, intimazioni, rateizzazioni in corso, ravvedimento operoso, unpaid or deferred taxes and social contributions
  * tax_credit      — tax credits, distinguishing those the target GENERATED from those it PURCHASED or received by assignment: R&D, Industria/Transizione 4.0-5.0, building bonuses (superbonus, sconto in fattura). Say whether each credit was offset in F24, certified, or subject to riversamento spontaneo, and whether an assessment has reversed it
  * tax_regime      — special regimes and elections: consolidato fiscale, IVA di gruppo, patent box, interpelli / rulings, and transactions whose regime matters (trasformazione, conferimento, fusione, scissione, riallineamento)
  * tax_losses      — carried-forward tax losses, ACE surpluses and interest carry-forwards whose survival after the change of control must be verified
  * transfer_pricing — cross-border intercompany transactions and their documentation; costs towards non-cooperative jurisdictions
  * tax_compliance  — filings and formalities: missing, late or amended returns, irregular data, DURF/withholding obligations in procurement chains, ISA scores and sector-study positions
  * other_tax       — any other tax-relevant fact that does not fit the above
- tax_kind: which tax the finding concerns — one of [ires, irap, iva, ritenute, registro, imu, dogane_accise, contributi, altro]
- title: concise label (max 100 characters)
- description: the finding with the document evidence, quoting figures and references verbatim where possible (max 400 characters)
- legal_basis: the statutory provision the DOCUMENT cites, verbatim (e.g. "art. 110 TUIR"), or null if the document cites none. Do not supply a provision the document does not mention.
- fiscal_years: array of the fiscal years the finding concerns, as integers (e.g. [2021, 2022]); empty array if the document does not say.
- amount_eur: the exposure in euro if the DOCUMENT states it, otherwise null. Never a computed or estimated figure.
- defensibility: how the position would hold up IF the tax authority challenged it. This is NOT the likelihood of being audited — never estimate that.
  * actual — errors, omissions or insufficient payments that automatically produce a tax charge with no possible defence (e.g. a tax shown as due in a filed return and not paid)
  * high   — a position most likely to give rise to litigation and difficult for the company to defend
  * medium — a position the authority would disagree with, but which the company has a fair chance of defending
  * low    — a position that would be challenged only on an aggressive approach, and is defensible
- mitigating_factors: array of short strings, from this vocabulary where applicable, otherwise free text (empty array if none): "time_barred", "deductible_in_future_periods", "reverses_in_following_period", "dta_recognisable", "return_still_amendable", "covered_by_guarantee", "covered_by_insurance", "already_paid", "instalment_plan_in_force", "settled_with_authority", "merely_formal_violation"
- confidence: extraction confidence between 0.0 and 1.0

POSITIONS THAT RECUR IN OWNER-MANAGED ITALIAN TARGETS — look for these specifically, they are the most common findings and are easy to miss:
- inventory valued by management judgement or adjusted at year end for tax purposes (a year's closing inventory is the next year's opening one, so an adjustment reverses; a QUANTITATIVE difference also raises a VAT presumption of sale)
- maintenance expenses deducted as ordinary when they extended an asset's useful life and should have been capitalised
- directors' fees deducted without a shareholders' resolution authorising them, or deducted in a year other than the one of payment
- remuneration of directors or employees disproportionate to the size of the business
- transactions with related parties resident in Italy — rents, services, purchases from entities of the same owner. There is NO domestic transfer-pricing rule in Italy: report the position only where the document itself indicates the conditions are not at market value, and frame it as an economic-inconsistency challenge
- a shareholder's waiver of a loan or its conversion into equity, and whether the sworn self-declaration of the receivable's tax basis is on file
- changes of legal form, and whether reserves formed before the change are disclosed as such
- sector-study or ISA reliability positions — these are AUDIT-RISK indicators, not exposures: never assign them an amount

Document: {filename}
Document text:
{text}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"finding_type": "...", "tax_kind": "...", "title": "...", "description": "...", "legal_basis": null, "fiscal_years": [], "amount_eur": null, "defensibility": "...", "mitigating_factors": [], "confidence": 0.0}}, ...]

If no tax findings are present, return an empty array: []
"""

FINANCIAL_ANALYSIS_PROMPT = """You are a senior M&A advisor reviewing the financial documents of an Italian target company for a legal due diligence.

ANALYZE FINANCIAL STATEMENTS and their annexes in the document below, and extract findings relevant to a share acquisition.

CRITICAL RULES:
1. Report ONLY facts EXPLICITLY present in the document text — quote the figure, article or paragraph that evidences each finding.
2. This is a LEGAL review of financial documents, not an accounting analysis. Do NOT recompute ratios, do NOT assess whether the business is a good investment, do NOT comment on valuation.
3. **Never estimate a figure.** Report an amount only where the document states it; otherwise set it to null. An omitted figure is correct, an invented one is not.
4. Ordinary, unqualified financial statements are NOT a finding. Report deviations and legally relevant facts.
5. If the document contains no financially relevant content, return an empty array.

For each finding, provide:
- finding_type: one of [auditor_opinion, going_concern, capital_loss, covenant, related_party, guarantee, subsequent_event, equity_position, debt_like_item, receivables_at_risk, accounting_irregularity, concentration, public_funding, prior_deal_claim, information_limitation, other_financial]
  * auditor_opinion  — qualified, adverse or disclaimed opinion by the auditor or the board of statutory auditors; emphasis-of-matter paragraphs; also the ABSENCE of an audit where one was required (check the thresholds for appointing a control body under art. 2477 c.c. before treating "unaudited" as a finding)
  * going_concern    — doubts on the continuità aziendale, deficit patrimoniale, negative net equity, recurring losses, dependence on shareholder support letters, composizione negoziata or insolvency procedures
  * capital_loss     — losses reducing capital under artt. 2446 / 2447 c.c. (S.p.A.) or 2482-bis / 2482-ter c.c. (S.r.l.), the dissolution cause under art. 2484 c.c., losses deferred under the pandemic regime, and the resolutions taken or postponed
  * covenant         — financial covenants, negative pledges, cross-default and change-of-control clauses disclosed in the notes or in the financing schedules, including waivers obtained and breaches recorded
  * related_party    — transactions with shareholders, directors or group companies: shareholder loans, postergazione ex art. 2467 c.c., cash pooling, intercompany balances, rents paid to entities of the same owner
  * guarantee        — sureties (fideiussioni), comfort letters, counter-guarantees, surety insurance policies, pledges and liens granted BY the target or IN ITS INTEREST by its shareholders. Record who granted it, in whose favour, for what amount and purpose, and whether anyone is obliged to replace or release it at closing
  * subsequent_event — events after the balance-sheet date disclosed in the notes or the management report
  * equity_position  — share capital, reserves, restricted reserves, capital contributions, and receivables from shareholders for contributions still due
  * debt_like_item   — liabilities that behave as financing and that a buyer will want in the net debt: overdue tax and social-security liabilities and the penalties and interest on them; trade payables overdue beyond the agreed terms; accrued financial charges; leasing; factoring with recourse; cash that is not really available (deposits pledged or frozen by disputes, sums to be returned to customers); accrued untaken holiday; agents' leaving indemnity; transaction costs and bonuses payable at closing
  * receivables_at_risk — receivables long overdue or in dispute, revenue accrued but never invoiced ("fatture da emettere"), and the absence of a bad-debt provision where one is plainly needed
  * accounting_irregularity — facts that undermine the reliability of the accounts: revenue recognised on invoices that will not be issued, accruals never reversed, regular manual entries, unreconciled differences, books still open, systems not integrated, interim figures prepared for the transaction and not approved by the board
  * concentration    — dependence on a few customers or suppliers, or on a contract not yet signed
  * public_funding   — grants and subsidised financing, with the conditions attached and any clawback the transaction could trigger
  * prior_deal_claim — warranty or indemnity positions under the target's OWN earlier acquisitions: claims running against former shareholders, and guarantees they gave that cover a current exposure. Note that the company usually remains primarily liable and the indemnity is only a recourse
  * information_limitation — the document itself records that something was not provided, not reconciled, not discussed with management, still in draft, or not approved. These are findings, not boilerplate
  * other_financial  — any other legally relevant financial fact that does not fit the above
- title: concise label (max 100 characters)
- description: the finding with the document evidence, quoting figures verbatim where possible, preserving Italian formatting (max 400 characters)
- amount_eur: the amount in euro if the DOCUMENT states it, otherwise null. Never a computed or estimated figure.
- counterparty: the bank, guarantor, customer, supplier or related party the finding concerns, if the document names one; otherwise null.
- change_of_control_clause: for a covenant finding, true or false if the document says whether the agreement has one; otherwise null.
- financial_covenant: for a covenant finding, true or false if the document says whether financial covenants apply; otherwise null.
- severity:
  * low    — informational: standard disclosures, closed matters, ordinary reserves, an unaudited micro-company below the statutory thresholds
  * medium — needs verification or has a remediable exposure: covenants the Transaction could trigger, related-party balances to be settled, restricted reserves, guarantees of limited amount, receivables at risk, revenue-recognition anomalies, customer concentration, grants with conditions
  * high   — material exposure: qualified or adverse auditor opinion, going-concern doubts, negative net equity, losses triggering artt. 2446/2447 or 2482-bis/ter c.c., covenant breaches, change-of-control clauses in financing agreements, overdue tax or social-security liabilities, guarantees of material amount
- confidence: extraction confidence between 0.0 and 1.0

TWO RULES THAT ARE EASY TO GET WRONG:
- Employees' leaving entitlement (TFR) is NOT uniformly debt-like. Since the 2007 reform it depends on the entity: where the company had more than 50 employees in 2006 the balance runs off and is debt-like in nature; below that threshold it keeps accruing internally and is a rolling, non-cash liability whose treatment is debatable. Within a group the answer can differ company by company, so state which case the document supports rather than assuming.
- Negative net equity is a legal event before it is an accounting one. Where the document shows equity below zero or below the legal minimum, raise it even if the document itself passes over it without comment.

Document: {filename}
Document text:
{text}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"finding_type": "...", "title": "...", "description": "...", "amount_eur": null, "counterparty": null, "change_of_control_clause": null, "financial_covenant": null, "severity": "...", "confidence": 0.0}}, ...]

If no financial findings are present, return an empty array: []
"""

DEAL_QA_PROMPT = """You are a deal analysis assistant. ANSWER THE QUESTION below using ONLY the context chunks provided.

Each context chunk has an index number. After answering, list the indices of the chunks you relied on.

CRITICAL RULES:
1. Base your answer STRICTLY on the provided context — do not use general knowledge or make assumptions.
2. If the context does not contain enough information to answer the question, say explicitly: "The provided documents do not contain sufficient information to answer this question." and return an empty cited_chunks list.
3. Do not speculate or fill gaps with plausible-sounding information.

--- CONTEXT CHUNKS ---
{context}

--- QUESTION ---
{question}

Return ONLY a JSON object (no markdown fences, no explanation):
{{"answer": "<your answer>", "cited_chunks": [<index>, ...]}}

Keep the answer concise and professional (max 300 words).
"""
