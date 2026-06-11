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
- report: A research, financial, or audit report
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
- severity: one of [low, medium, high]
- area: one of [corporate, indebtedness, real_estate, employees, suppliers_customers, insurance, litigation, ip_it, data_protection, other]
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

EXTRACT the fields listed below for EACH distinct company described in the document.

CRITICAL RULES:
1. Extract ONLY facts EXPLICITLY present in the document text. Do NOT infer, guess, or supplement from general knowledge.
2. If a field is not present in the document, set it to null. Do NOT fabricate.
3. The document may describe one company (typical visura) or several (group statute, holding structure). Return one JSON object per distinct company found.
4. Quote names, addresses, capital figures and dates verbatim where possible — preserve Italian formatting (e.g. "Euro 1.000.000,00").
5. For shareholders: produce a concise human-readable list, one per line: "Name — N shares (class) — % of capital". When a percentage is missing, omit it.
6. For the managing body: list each director with role: "Mr X (Chairman), Mr Y (Managing Director), ...". Include the date of appointment and the term if stated.
7. For the auditors: list each statutory auditor with role (President / Statutory / Alternate). Include the date of appointment and the term if stated.

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

If the document is not a corporate document and contains no extractable company data, return: []
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
  high   — affects transfer validity or completion: unreleased pledges on the target's shares; missing share certificates; pre-emption/tag-along/drag-along rights not waived; material unexplained debt exposures; litigation with material quantified exposure; total absence of GDPR/privacy documentation.
  medium — needs action but has a standard remedy: change-of-control consent requirements in loans, leases or key customer contracts ("although unlikely…"); missing corporate minutes; Modello 231 absence with aggravating factors; missing employment agreements; non-compliant contract templates; unverified settlement payments.
  low    — worth recording, limited economic impact: null-and-void clauses with modest exposure (e.g. ISTAT indexation above the legal cap); missing policy copies; unregistered trademarks; unverified domain ownership; generic insurance adequacy.

AREA — assign each finding to exactly one report section:
  corporate | indebtedness | real_estate | employees | suppliers_customers | insurance | litigation | ip_it | data_protection | other

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
- area: one of [corporate, indebtedness, real_estate, employees, suppliers_customers, insurance, litigation, ip_it, data_protection, other]
- category: free-text fine-grained label, e.g. "transfer_restriction", "change_of_control", "pledge", "missing_document"
- confidence: 0.0–1.0
- source_document_id: integer document ID or null

EXAMPLES of correctly structured red_flag entries (synthetic — illustrate format and calibration only):
[
  {{"finding_type": "red_flag", "title": "Pledge over the Target's shares", "issue": "A pledge over shares representing 81% of the corporate capital of the Target exists in favour of a lender, securing bond payment obligations (Bond Subscription Agreement, art. 10).", "risk": "If the secured debt is not repaid before closing, the Purchaser acquires shares that remain encumbered by the pledge.", "recommendation": "As a condition precedent to Closing, the lender should release the pledge.", "severity": "high", "area": "corporate", "category": "pledge", "confidence": 0.92, "source_document_id": 3}},
  {{"finding_type": "red_flag", "title": "Change-of-control clause in loan agreement", "issue": "Article 5 of the loan agreement provides that the lender may terminate in case of any event negatively affecting the financial or corporate situation of the company.", "risk": "Although unlikely, after the Transaction the lender may claim the change of control qualifies and accelerate repayment.", "recommendation": "As a condition precedent to Closing, obtain the lender's consent to the Transaction.", "severity": "medium", "area": "indebtedness", "category": "change_of_control", "confidence": 0.85, "source_document_id": 7}},
  {{"finding_type": "red_flag", "title": "Rent indexation above legal cap", "issue": "The lease agreement provides annual rent indexation at 100% of the ISTAT variation, while the maximum allowed under Italian law is 75%.", "risk": "The company may pay, or may have paid, amounts not due under applicable law.", "recommendation": "Insert specific Sellers' representations and warranties in the SPA; renegotiate the clause.", "severity": "low", "area": "real_estate", "category": "void_clause", "confidence": 0.80, "source_document_id": 12}}
]

Priority order: check all PRIORITY RISKS first, then apply SAFE HARBOUR before raising anything else.

{findings_by_document}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"finding_type": "red_flag", "title": "...", "issue": "...", "risk": "...", "recommendation": "...", "severity": "high", "area": "...", "category": "...", "confidence": 0.0, "source_document_id": null}}, ...]

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
