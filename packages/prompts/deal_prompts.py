"""Prompts of the engine shared with Diligenx: document Q&A and the legacy
single-shot analysis. The property review's prompts are in
``packages.real_estate.prompts``.
"""

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
- amount_eur: carry forward only amounts marked amount_source=document; otherwise null. Never compute or estimate one.
- amount_evidence: copy the source finding's exact evidence quotation for that amount; otherwise null.
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
