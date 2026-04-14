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
- description: why this specific clause is a concern and what impact it could have (max 300 characters) — reference the actual clause content
- severity: one of [low, medium, high, critical]
- category: risk category (e.g., "liability", "termination", "payment", "ip", "compliance", etc.)
- confidence: confidence score between 0.0 and 1.0
- source_document_id: always null

Clause Findings:
{findings}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"title": "...", "description": "...", "severity": "...", "category": "...", "confidence": 0.0, "source_document_id": null}}, ...]

If no red flags are found, return an empty array: []
"""

REPORT_GENERATION_PROMPT = """You are a senior M&A legal advisor specialising in Italian corporate law. GENERATE a DUE DILIGENCE REPORT in Markdown for the deal below.

The report MUST contain exactly these five sections (level-2 headings):
## Executive Summary
## Red Flags
## Observations
## Information Requests
## Documents Reviewed

SECTION DEFINITIONS:
• Executive Summary — 3–5 sentences maximum. State what was analysed, the overall risk profile, and the single most critical issue (if any). No filler language.
• Red Flags — Issues that materially affect: (a) transaction validity / completion, (b) the buyer's ability to acquire shares, or (c) material financial liabilities. Each entry: **[SEVERITY] Title** — one or two sentences stating what the provision says and what action is required before or after closing.
• Observations — Noteworthy contractual provisions or facts that do not block the transaction but should be tracked post-closing. Concise bullet points.
• Information Requests — Missing documents, unresolved ambiguities, or items requiring clarification. Numbered list.
• Documents Reviewed — Markdown table: | Document | Language | Pages |

CRITICAL RULES:
1. Ground every statement in the data below. Do NOT add assumptions or general market knowledge.
2. If a section has nothing to report, write: "_None identified based on available documents._"
3. Do NOT flag TFR accruals, holiday balances, CCNL applicability, standard arbitration clauses, share capital vs. deal value differences, or standard Italian Civil Code defaults.
4. For employment documents: if there is no evidence of non-compliance, the Red Flags section must state nothing material was identified.
5. No consulting filler ("it is advisable to", "standard market practice suggests", "we recommend monitoring"). Write for a lawyer who knows Italian M&A.
6. Severity labels: **[CRITICAL]**, **[HIGH]**, **[MEDIUM]**, **[LOW]**.

--- DEAL ---
{deal_info}

--- DOCUMENTS ---
{documents}

--- CLAUSE FINDINGS ---
{clause_findings}

--- RED FLAGS ---
{red_flags}

--- OBSERVATIONS ---
{observations}

--- INFORMATION REQUESTS ---
{information_requests}

Return ONLY the Markdown report. Do NOT wrap it in code fences.
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

RED_FLAG_AGGREGATION_PROMPT = """You are a senior M&A legal advisor specialising in Italian corporate law and transaction risk assessment.

TRIAGE RED FLAGS, OBSERVATIONS AND INFORMATION REQUESTS from the specialist analysis below.
Assign each finding to one of three categories:
  red_flag        — materially affects: (a) transaction validity / completion, (b) the buyer's ability to acquire shares, or (c) creates material financial liabilities.
  observation     — noteworthy provision or fact that does not block the transaction but warrants attention post-closing.
  information_request — information gap, missing document, or item requiring clarification before or after signing.

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
- description: specific factual impact, referencing the source finding (max 250 characters)
- severity: one of [low, medium, high, critical]
  • red_flag: high or critical only (low/medium risks are observations)
  • observation: low or medium
  • information_request: low
- category: e.g. "transfer_restriction", "governance", "change_of_control", "liability", "termination", "employment", "compliance", "missing_document"
- confidence: 0.0–1.0
- source_document_id: integer document ID or null

Priority order: check all PRIORITY RISKS first, then apply SAFE HARBOUR before raising anything else.

{findings_by_document}

Return ONLY a JSON array (no markdown fences, no explanation):
[{{"finding_type": "red_flag", "title": "...", "description": "...", "severity": "high", "category": "...", "confidence": 0.0, "source_document_id": null}}, ...]

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
