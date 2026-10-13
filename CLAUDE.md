# Diligenx — Project Context

## Stack
- **Backend:** FastAPI + SQLAlchemy 2.0 (mapped_column style) + Pydantic v2
- **Database:** PostgreSQL (default) + pgvector extension; SQLite for tests
- **Auth:** JWT via HttpOnly session cookie (browser) or Bearer header (API clients) → `python-jose` + `bcrypt` (no passlib); sign-in with Microsoft / Google over OpenID Connect (code + PKCE, `docs/OAUTH_SETUP.md`); SSE authenticated by short-lived deal-scoped tickets
- **Migrations:** Alembic (`apps/api/alembic/`)
- **Embeddings:** OpenAI `text-embedding-3-small` (1536 dims); `FakeEmbeddingProvider` for tests
- **LLM:** OpenAI GPT-5.6 Luna (`gpt-5.6-luna` by default) for every analysis stage and document Q&A; `FakeLLMProvider` for tests
- **Storage:** S3-compatible (Cloudflare R2 in prod); local disk fallback when `S3_BUCKET` empty
- **Rate limiting:** `slowapi` (in-memory); disabled in tests via autouse fixture
- **Background jobs:** `BackgroundTasks` by default; **Arq + Redis** opt-in via `REDIS_URL` for durable jobs
- **Env:** `.env` via `pydantic-settings`
- **Frontend:** Next.js 15 (App Router, TypeScript) — login + dashboard + insights + deals UI, server-side auth via cookie
- **Frontend design system:** tokens in `apps/web/tailwind.config.ts` — `blue-*` resolves to the brand ultramarine scale, `ink` is the dark surface, Geist / Geist Mono / Instrument Serif (`font-display`) self-hosted via `next/font` (no request to Google from the browser); shared utilities (`bg-grid`, `glass`, `reveal`, `text-gradient`) in `globals.css`; `MainContainer` renders `/` and `/login` full-bleed
- **Frontend tests:** Playwright smoke suite (3 tests) in `apps/web/tests/e2e/`
- **Tests:** pytest + FastAPI TestClient (SQLite), **1607 passing**

## Project Root
```
/home/user/Diligenx/
```

## Structure

```
Diligenx/
├── apps/api/                             # FastAPI backend
│   ├── app/
│   │   ├── main.py                       # App entry, CORS, slowapi, routers
│   │   ├── core/
│   │   │   ├── config.py                 # Settings: DATABASE_URL, SECRET_KEY, S3_*, ANTHROPIC_API_KEY, EMBEDDING_*, ANALYSIS_MODEL
│   │   │   ├── limiter.py                # slowapi Limiter instance (in-memory)
│   │   │   └── security.py               # bcrypt hashing, JWT create/decode
│   │   ├── db/session.py                 # engine, SessionLocal, Base, get_db(); WAL + busy_timeout on SQLite
│   │   ├── models/
│   │   │   ├── base.py                   # TimestampMixin (created_at, updated_at)
│   │   │   ├── user.py                   # User → owns Workspaces; `has_password` false for Microsoft/Google-only accounts
│   │   │   ├── oauth_identity.py         # OAuthIdentity (provider + subject) → User
│   │   │   ├── workspace.py              # Workspace → owner_id FK to User
│   │   │   ├── deal.py                   # Deal + DealStatus(draft|analyzing|reviewed|closed) → workspace_id FK
│   │   │   ├── document.py               # Document + DocumentStatus(pending|processing|processed|failed) + language + raw_text
│   │   │   ├── document_chunk.py         # DocumentChunk + VectorType (pgvector on PG, JSON on SQLite) + EMBEDDING_DIM=1536
│   │   │   ├── clause_finding.py         # ClauseFinding + ClauseType enum
│   │   │   ├── red_flag.py               # RedFlag (issue/risk/recommendation triple) + Severity(low|medium|high) + DueDiligenceArea (11 standard DD report sections, incl. tax + financial) + source_document_id/source_page citation + remedy_type/impact tags + structured_payload_json
│   │   │   ├── report.py                 # Report + ReportType + ReportStatus enums
│   │   │   ├── agent_run.py              # AgentRun (one row per pipeline stage execution)
│   │   │   ├── agent_finding.py          # AgentFinding (intermediate per-doc findings, e.g. routing)
│   │   │   ├── missing_document.py       # MissingDocument (expected categories absent from intake)
│   │   │   ├── open_question.py          # OpenQuestion (items needing human follow-up from red-flag aggregator)
│   │   │   └── __init__.py
│   │   ├── schemas/                      # Pydantic v2 (from_attributes=True)
│   │   │   ├── user.py, workspace.py, deal.py, document.py
│   │   │   ├── clause_finding.py, red_flag.py, report.py
│   │   │   └── agent_run.py
│   │   ├── services/
│   │   │   ├── auth.py                   # get_current_user() / get_current_session() — Bearer or cookie
│   │   │   ├── oauth.py                  # OIDC providers: discovery, PKCE, code exchange, ID-token verification
│   │   │   ├── storage.py                # S3/R2 client + save_file/read_file (local fallback)
│   │   │   ├── jobs.py                   # enqueue_or_run() — Arq pool if REDIS_URL set, else BackgroundTasks
│   │   │   └── report_export.py          # Markdown → PDF (reportlab) / DOCX (python-docx)
│   │   ├── worker.py                     # Arq WorkerSettings; consumes jobs enqueued by the API
│   │   └── api/routes/
│   │       ├── health.py                 # GET /health
│   │       ├── auth.py                   # POST /auth/register, /auth/login
│   │       ├── oauth.py                  # GET /auth/oauth/providers, /{provider}/start, /{provider}/callback
│   │       ├── workspaces.py             # CRUD + /workspaces/{id}/insights aggregate
│   │       ├── deals.py                  # CRUD + /analyze /report /ask /agent-runs /risk-score /open-questions /missing-documents
│   │       └── documents.py              # /upload, /upload-batch, list, delete
│   ├── alembic/versions/                 # 001..007 + language column migration
│   ├── alembic.ini, requirements.txt, pyproject.toml, Dockerfile, .env.example
│
├── apps/web/                             # Next.js 15 frontend (functional)
│   ├── src/app/
│   │   ├── layout.tsx, page.tsx, globals.css
│   │   ├── login/                        # email/password form → cookie
│   │   ├── dashboard/                    # workspace switcher, deal list
│   │   ├── dashboard/insights/           # 4 aggregate widgets (pipeline, severity, top categories, completeness)
│   │   └── deals/[id]/                   # deal detail with severity + follow-up widgets, upload, analyze, report
│   │       └── findings/                 # clause + red-flag lists; red flags filterable by remedy and impact, with the tags and stated figures on each card
│   ├── src/components/                   # shared UI (toasts, modals, upload zone)
│   ├── src/lib/api.ts                    # typed API client
│   ├── src/middleware.ts                 # server-side auth guard via cookie
│   ├── tests/e2e/                        # Playwright smoke suite (run with `pnpm test:e2e`)
│   ├── playwright.config.ts
│   ├── package.json, next.config.ts, Dockerfile
│
├── packages/
│   ├── agents/                           # ★ Multi-agent analysis pipeline (fully wired)
│   │   ├── base.py                       # BaseAgent ABC
│   │   ├── deal_analysis_agent.py        # LLMProvider ABC + AnthropicLLMProvider + FakeLLMProvider, grounding check
│   │   ├── orchestrator.py               # ★ run_deal_analysis_pipeline() — 9 stages, AgentRun tracking
│   │   ├── intake_agent.py               # Stage 1: validates deal, records MissingDocument
│   │   ├── contract_agent.py             # Stage 3: extracts ClauseFinding via grounded LLM
│   │   ├── corporate_agent.py            # Stage 4: corporate governance analysis
│   │   ├── corporate_intro_agent.py      # Stage 4b: CompanyProfile extraction (visure/atti/statuti)
│   │   ├── tax_agent.py                  # Stage 4c: tax documentary review (LLM + deterministic keyword heuristics)
│   │   ├── tax_rules_registry.py         # Year-indexed Italian tax rules: citations + assessment periods, no rates
│   │   ├── financial_agent.py            # Stage 4d: financial documentary review (LLM + deterministic keyword heuristics)
│   │   ├── red_flag_aggregator.py        # Stage 5: produces RedFlag + OpenQuestion
│   │   ├── report_agent.py               # Stage 6: Markdown report → Report row
│   │   ├── deal_qa_agent.py              # RAG Q&A over deal documents
│   │   ├── concurrency.py                # run_llm_tasks() — bounded parallel fan-out for per-doc LLM calls
│   │   ├── stage_tx.py                   # release_connection_before_llm() — no DB transaction across the LLM phase
│   │   ├── scoring_service.py            # compute_risk_score(deal_id)
│   │   ├── legal_rules.py                # CCNL / legal heuristics
│   │   └── deal_agent.py                 # legacy single-shot agent (kept for back-compat)
│   ├── prompts/deal_prompts.py           # All prompt templates (CLASSIFY, EXTRACT CLAUSES, RED FLAGS, etc.)
│   ├── schemas/deal.py                   # Shared Pydantic schemas
│   ├── parsing/                          # Document ingestion
│   │   ├── pdf_parser.py                 # extract_pdf() with OCR fallback for blank/scanned pages
│   │   ├── docx_parser.py, text_parser.py
│   │   ├── language.py                   # detect_language(text) → 'it' | 'en'
│   │   ├── chunker.py                    # 1000 chars, 200 overlap, sentence-aware
│   │   └── ingestion_pipeline.py         # process_document(doc_id, db)
│   └── retrieval/
│       ├── embedding_service.py          # EmbeddingProvider ABC, OpenAI + Fake providers, singleton
│       └── vector_store.py               # cosine similarity over DocumentChunk.embedding
│
├── infra/, scripts/, docker-compose.yml, railway.toml
├── tests/                                # 1607 passing
└── CLAUDE.md                             # ← this file
```

## Data Model

```
User 1──* Workspace 1──* Deal 1──* Document 1──* DocumentChunk (embedding VECTOR(1536))
                              │           └──* ClauseFinding
                              ├──* RedFlag (optional source_document_id → Document)
                              ├──* OpenQuestion
                              ├──* MissingDocument
                              ├──* AgentRun (one per pipeline stage)
                              ├──* AgentFinding
                              └──* Report
```

## API Endpoints (all 🔒 except auth & health)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/auth/register` | Register → UserRead |
| POST | `/auth/login` | Login (form) → Token + HttpOnly session cookie |
| POST | `/auth/logout` | Clear session cookies (unauthenticated by design) |
| GET | `/auth/oauth/providers` | Sign-in providers configured (`microsoft`, `google`) |
| GET | `/auth/oauth/{provider}/start` | Redirect to Microsoft/Google (state, nonce and PKCE verifier in a signed 10-min cookie) |
| GET | `/auth/oauth/{provider}/callback` | Verify the ID token, link or create the account, set the session cookie → `/login/complete` |
| GET/POST/PATCH/DELETE | `/workspaces/...` | Workspace CRUD (last workspace and non-empty workspaces protected from deletion) |
| GET/POST | `/deals/?workspace_id=N` | List / create deals in workspace |
| GET/PATCH/DELETE | `/deals/{deal_id}` | Deal CRUD (PATCH also sets `report_language`: it\|en\|auto) |
| POST | `/deals/{deal_id}/analyze` | **202** → queues multi-agent pipeline in BackgroundTask |
| GET | `/deals/{deal_id}/agent-runs` | List AgentRun rows in pipeline order |
| POST | `/deals/{deal_id}/stream-ticket` | Short-lived deal-scoped ticket for the SSE stream |
| GET | `/deals/{deal_id}/analysis-stream` | SSE stream of pipeline progress (`?ticket=` from stream-ticket) |
| POST | `/deals/{deal_id}/report` | Generate Markdown due-diligence report |
| GET | `/deals/{deal_id}/report` | Get current report |
| GET | `/deals/{deal_id}/report/export?format=pdf\|docx` | Branded export |
| POST | `/deals/{deal_id}/ask` | RAG Q&A with citations |
| GET | `/deals/{deal_id}/clause-findings` | List clauses |
| GET | `/deals/{deal_id}/red-flags` | List red flags |
| GET | `/deals/{deal_id}/risk-score` | Computed risk score |
| GET | `/deals/{deal_id}/open-questions` | Follow-up questions raised by the pipeline (priority-ordered) |
| GET | `/deals/{deal_id}/missing-documents` | Document categories expected at intake but absent |
| GET | `/workspaces/{id}/insights` | Aggregate metrics (status mix, severity, top categories, completeness) |
| POST | `/documents/upload?deal_id=N` | **201** → file saved, ingestion runs in BackgroundTask (or Arq if `REDIS_URL` set) |
| POST | `/documents/upload-batch?deal_id=N` | Multi-file upload |
| GET | `/documents/deals/{deal_id}/documents` | List deal's documents |
| DELETE | `/documents/{document_id}` | Delete document |

## Analysis Pipeline (`packages/agents/orchestrator.run_deal_analysis_pipeline`)
Triggered async by `POST /deals/{id}/analyze`. Each stage gets its own `AgentRun`; a failing stage marks itself failed but does not abort the pipeline. All stages are idempotent.

1. **Intake** — validate deal, set status → `analyzing`, inventory documents, record `MissingDocument` for absent standard categories (contract / financial / legal / insurance).
2. **Document routing** — classify each processed document → `AgentFinding`.
3. **Contract analysis** (`ContractAgent`) — extract clauses → `ClauseFinding` (with grounding check + min confidence).
4. **Corporate governance** (`CorporateAgent`) — bylaws / shareholder agreement insights.
4b. **Corporate intro extraction** (`CorporateIntroAgent`) — extracts the Corporate Introductory Information for each target company (visure / atti / statuti) → `CompanyProfile` rows. Auto-detects corporate-looking docs via filename + first-1500-chars keyword match. The report view (`packages/agents/company_identity.consolidate_company_profiles`) states **one value per field**, taken from the most authoritative source that carries it (visura → statuto/atto costitutivo → libro soci/patti → verbali → bilanci → everything else) and, within one rank, the most recent document by the date in its filename. Renderings that differ only in accents, case or punctuation are one value, spelled as the best source spells it. Every distinct value survives in `field_sources` with its documents, but only a **corporate record** (visura, statuto/atto costitutivo, libro soci/patti, verbali) can contradict the table: a field is named in `conflicting_fields` (one line under the table naming the fields; the alternatives themselves are no longer listed in the report, they stay in `conflict_sources`/`field_sources` for verification) only when corporate records disagree — or, where no corporate record states the field, sources as authoritative as the one the table relies on. A loan contract's "purpose of the financing", one fiscal year per bilancio or a tax return's heading are not a discrepancy, and listing them filled the introduction with repetitions. Before this the view unioned every line: the introduction carried eight spellings of one legal form and twenty-five of one registered office, and — worse — a `managing_body` merged from minutes of different dates stated a board that never sat.
4c. **Tax documentary review** (`TaxAgent`) — analyses tax documents (avvisi di accertamento, cartelle, rateizzazioni, crediti d'imposta, regimi speciali, TP, DURF) selected by keyword auto-detection ∪ routing classification (`document_type=tax`; data-room numbering such as `7.2.4 Redditi SC 2023` is stripped before matching, and filings that no longer exist — spesometro, comunicazione dati IVA — still select the document, since a closed period is still a finding). LLM findings + deterministic keyword heuristics as a floor (a notified accertamento can never be silently dropped) → `AgentFinding` rows (`agent_name=tax_analysis`) that flow into stage 5 with `area=tax`. The floor covers acts of the authority, collection, litigation, contested/purchased tax credits, loss carry-forwards, transfer pricing, compliance and tax offences; each entry carries its own grade (an *omesso versamento* is `actual`, an interpretative position is not) and an optional note — the four tax-offence keywords append the **D.Lgs. 231/2001** entity-liability consequence, which a share deal inherits. Litigation keywords require evidence of an actual dispute, because every assessment notice names the tax court in its footer. Each finding carries a **`defensibility`** grade (`actual|high|medium|low` — how the position would hold up *if challenged*, the scale real tax advisers use; it is **not** a probability of being audited, which nothing in the pipeline estimates), plus `tax_kind`, `legal_basis`, `fiscal_years`, `mitigating_factors` and an `amount_eur` **only when the document itself states one**. `severity` is derived from the grade in code (`actual` → high, never downgraded). Statutory references and assessment-period expiry per fiscal year come from `tax_rules_registry`. Documentary review only — the report boilerplate states it does not substitute a full tax/financial DD by the client's advisors.
4d. **Financial documentary review** (`FinancialAgent`) — analyses financial statements and their annexes (bilanci, note integrative, relazioni sulla gestione / del collegio sindacale / della società di revisione) selected by keyword auto-detection ∪ routing classification (`document_type=financial_statement`). Findings cover the statutory shapes (auditor_opinion, going_concern, capital_loss, covenant, related_party, guarantee, subsequent_event, equity_position) **and** the shapes every real FDD produces that a purely accounting reading would lose: `debt_like_item` (liabilities that behave as financing — overdue tax and social-security debts, overdue payables, leasing, factoring with recourse, cash that is not really available, untaken holiday, agents' indemnity), `receivables_at_risk`, `accounting_irregularity`, `concentration`, `public_funding`, `prior_deal_claim` (warranty positions under the target's *own* earlier acquisitions) and `information_limitation` (what the document records as not provided, not reconciled or still in draft). Deterministic keyword heuristics act as a floor (a going-concern paragraph or an art. 2446/2482-bis c.c. loss can never be silently dropped; article numbers match only with an `art.` prefix or `c.c.` suffix, so amounts in the accounts don't false-positive) and may carry a note where a keyword has a legal consequence the accounts do not state — negative equity points at the dissolution cause (art. 2484 c.c.), **overdue tax and social-security debts oblige the qualified public creditors to report the company under art. 25-novies CCII**, and "unaudited" is a finding only where an audit was required (art. 2477 c.c. thresholds). `amount_eur` is populated only where the document states a figure (`amount_source` records which case); covenant findings carry `change_of_control_clause` and `financial_covenant` as **tri-state** flags, so "not stated" stays distinct from "stated as false". The prompt also states the **TFR rule per entity** (the 2007 reform splits on the 50-employee test, so within one group a subsidiary's TFR can be fully debt-like while another's is a rolling non-cash liability). → `AgentFinding` rows (`agent_name=financial_analysis`) flowing into stage 5 with `area=financial`. A **legal** review of financial documents, not an accounting analysis: no ratios, no valuation.
5. **Red-flag aggregation** — the corpus is the specialists' findings about documents, never the pipeline's own bookkeeping: `RedFlagAggregationAgent.BOOKKEEPING_CATEGORIES` (today `clause_extraction_summary`) is excluded alongside `document_router`, because a line such as "Contract analysis of 'X.pdf' found 0 clause(s)" reads to the model as a fact about the target, becomes a draft, and is then rejected by the source-fidelity review for citing a sentence that appears in no document — three model calls to produce an open question about the tooling. Coverage gaps keep their own channels (`MissingDocument`, the per-stage unanalysed-document `OpenQuestion`s). The stage produces `RedFlag` rows (Issue/Risk/Recommendation triple, severity low|medium|high, DD area, `source_document_id` + validated `source_page` pinpoint citation) + `OpenQuestion` items for high-severity flags. A cited `source_page` is kept only if it matches a real page of that document's ClauseFindings (guards against hallucinated citations). Each flag is tagged on **two independent axes**, because the two professions tag differently: `remedy_type` — the instrument that answers it (indemnity, warranty, price_adjustment, earn_out, condition_precedent, pre_closing_verification, post_closing_action, information_request), the tag a law firm's risk memo assigns — and `impact` (value | spa | other), the tag a financial adviser's key-findings page assigns. An unrecognised value becomes **null rather than a guess**. The context handed to the LLM now carries the specialists' structured fields (defensibility, tax kind, amount stated by the document, fiscal years, time-barred years, mitigating factors, covenant flags) so the aggregation consolidates what was already established instead of re-deriving it, and `amount_eur`/`fiscal_years` are carried onto the flag's `structured_payload_json`. A deterministic **severity floor** raises — never lowers — any flag whose category matches a source finding graded `defensibility=actual` (an omission with no available defence) or a `capital_loss`/`going_concern`; it is a safety net behind the prompt instruction, and the raise is recorded as `severity_floored` in the payload. Every draft then passes a **source-fidelity (grounding) review** (`packages/agents/grounding_review.py`): an independent LLM pass must return verbatim, locally verified quotations for each factual field, with one correction attempt. The verdict is **per draft, never per deal**: a draft that stays unsupported after the correction is dropped from the `RedFlag` output and recorded as a medium-priority `OpenQuestion` carrying the reviewer's reason (`grounding_rejected` in the stage result), so one doubtful finding cannot discard the verified flags of a whole data room. A review request that fails at transport level (output truncated at the token limit, refusal, malformed JSON after the format retry) is isolated the same way: the batch is halved until the failing draft stands alone and only that draft is rejected, with the transport error as its reason. Quotations are compared accent-, quote- and hyphenation-insensitively (OCR and model output disagree on `è`/`e'`, curly quotes and line-end hyphens). For a long source (a ledger, a partitario) the reviewer sees windows located from the draft's own names, amounts and dates (`_draft_locators`), not the first 40k characters. Article references are locators too (`_article_references`: "art. 8", "articolo 21", "artt. 8 e 9", "art. 2482-bis c.c."), because names do not locate a clause of a statuto: the company name is in every article, so on the Arcari run the windows stopped in the first articles and five statuto findings (pre-emption, consent clause, withdrawal value, arbitration) were rejected with "the available extract does not contain art. 8". An article heading at the start of a line gets a window running forward over the whole clause, a citation elsewhere the usual symmetric one, and `_article_pattern` keeps 8 apart from 80, 8-bis and 2482; when a document still has to be swept window by window, one window can add evidence or correct the text but can never reject the draft on its own, since it may simply not hold the passage. The stage still fails closed only when *every* draft is rejected. **Documents** are the unit of fan-out (`run_llm_tasks`, `LLM_MAX_CONCURRENCY`): reviewing them one at a time on the judgment model took a 169-draft data room past the worker's job timeout, while the batches *within* one document run in order, since they share their whole source block and the second then reads what the first put in the provider's prompt cache. Verdicts are persisted on the caller's thread in input order. The corrective and window instructions follow the payload instead of being spliced into the template, so the cached instruction and source blocks survive a correction pass; `review_payload()` decodes the JSON up to its closing brace. A structured form or return is citable: the prompt allows the shortest passage carrying a field label with its value, since a tax return holds no narrative sentence and every draft from one was otherwise rejected as uncitable.
6. **Report generation** (`report_agent.generate_due_diligence_report`) — bilingual (IT/EN — explicit `deal.report_language` or majority language of processed documents, fallback EN; LLM prose follows, boilerplate localized faithfully to studio practice: title/Executive Summary/Key Findings stay English) deterministic template (Introduction / Corporate Introductory Information from `CompanyProfile` / Executive Summary via LLM / Key Findings tabellari per DD area / Observations / Information Requests / Appendix Documents); stored as Markdown in `Report` table. Key Findings rows carry the **amount and fiscal years** a finding states (rendered in the report's own conventions — `EUR 240,000 · FY 2022` / `Euro 240.000 · es. 2022`) and end the recommendation cell with the **remedy tag** (`[Indemnity]` / `[Indennizzo]`), the way a consolidated risk memo tags its lines. The scope paragraph states the **assessable period computed from `tax_rules_registry`** rather than a fixed number of years, and discloses that quantifying taxes, penalties and interest is left to the client's tax advisers.

## Ingestion Pipeline (on upload)
```
POST /documents/upload → save to storage (S3/R2 or local) → create Document(status=pending) → 201 response
  → BackgroundTask: process_document(doc_id):
      1. status → processing
      2. Extract text per-page (PDF/DOCX/TXT, with OCR fallback for blank PDF pages)
      3. Detect language (IT or EN)
      4. Chunk text (1000 chars, 200 overlap, sentence boundaries)
      5. Persist DocumentChunk rows
      6. generate_embeddings_for_document() → OpenAI or FakeProvider
      7. status → processed   (failure → status=failed)
```

## Running (dev)

```bash
cd apps/api
pip install -r requirements.txt
cp .env.example .env          # set DATABASE_URL, SECRET_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY
alembic upgrade head          # needs PostgreSQL + pgvector extension
uvicorn app.main:app --reload # http://localhost:8000/docs

# Frontend
cd ../web
pnpm install && pnpm dev      # http://localhost:3000
```

## Running Tests

```bash
cd apps/api
python -m pytest ../../tests -q   # 1607 passed
```

## Key Design Decisions
- **PostgreSQL + pgvector** for prod embeddings; **SQLite + JSON** in tests via custom `VectorType` TypeDecorator
- **bcrypt** used directly (not passlib) — compatible with Python 3.14
- `DocumentChunk.embedding` column: `VECTOR(1536)` on PG, `TEXT` (JSON-serialized list) on SQLite
- `EmbeddingProvider` and `LLMProvider` are both pluggable singletons: `set_*_provider()` injects Fake stubs in tests
- Analysis and ingestion pipelines are **idempotent** — re-running clears previous outputs before writing new ones
- LLM output is **grounded**: contract clauses are dropped if their content doesn't appear in the source text (substring + word-overlap check)
- `/analyze` and `/upload` return immediately; actual work runs in FastAPI `BackgroundTasks` using a fresh `SessionLocal` (not the request's DB session)
- Rate limiting via `slowapi` (5/min on `/analyze`, 30/min on `/documents/upload`, etc.) — disabled in tests via autouse fixture in `tests/conftest.py`
- MIME types allowed: `application/pdf`, `text/plain`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- **Durable jobs**: when `REDIS_URL` is set, `/analyze` and `/upload` enqueue jobs to an Arq pool (managed via FastAPI lifespan); a separate worker process consumes them (`arq app.worker.WorkerSettings`). When unset, jobs run in-process via FastAPI `BackgroundTasks` — same behaviour as before. Enqueue failures fall back transparently.
- **Tax rules are versioned, never prompted**: `packages/agents/tax_rules_registry.py` holds Italian tax rules keyed by `rule_id` with `valid_from`/`valid_to` in **fiscal years**, a citation and a short bilingual gloss, plus `assessment_period(fiscal_year)` (four years up to FY2015, five from FY2016, longer where no return was filed) and `open_fiscal_years()`. It deliberately carries **no penalty rate, interest rate or reduction fraction** — those depend on the year *and* the procedure and have been amended repeatedly (D.Lgs. 158/2015, D.Lgs. 87/2024), so quantification is left to the client's tax advisers and the report prints a provision rather than arithmetic. `TAX_ANALYSIS_PROMPT` forbids the model from computing taxes, penalties or interest; a test asserts the registry's glosses contain no percentages or fractions.
- **GPT-5.6 Luna migration**: the default is `gpt-5.6-luna` for all analysis and document Q&A. OpenAI Responses requests set `reasoning.effort=none`, `store=false` and `truncation=disabled`. Structured extraction uses one forced function call; grounding reviews use strict schemas. Refusals, incomplete responses and malformed data are failures, not analysis evidence. `ANALYSIS_MODEL` overrides take precedence on both API and worker; an explicit `claude-*` override selects Anthropic. A missing selected API key never silently switches providers.
- **Two models, by role** (`get_llm_provider` / `get_judgment_provider`): about 90% of a run's tokens are bulk reading (a ledger chunk that yields nothing, a classification), where the cheapest capable model wins; the 10% that decide the report — consolidating a thousand specialist findings into flags, verifying quotations, writing the summary — run on `JUDGMENT_MODEL` (production: `claude-sonnet-5`, measured at roughly $7 per 66-document run on top of Luna's $3). The orchestrator hands the judgment provider to the aggregation and report stages, `generate_due_diligence_report` and `RedFlagAggregationAgent` default to it, and an explicitly injected provider serves every stage so tests never reach a vendor.
- **Anthropic prompt caching follows the prompt's segments**: a prompt is either a plain string (one unmarked block, base price: a one-shot request has nothing to reuse, and marking it only paid the 125% cache-write premium) or a sequence of `PromptSegment`s, each becoming one content block, with `cache_control={"type":"ephemeral"}` on the segments marked `cache=True` (at most four). Caching is prefix-based, so stable content goes first: the source-fidelity review sends *instructions* (marked), then the JSON head with `kind`, `language` and `documents` (marked), then the tail with `items` and `validation_feedback` (unmarked), joined byte-for-byte into the same JSON as before. The correction pass and the later batches of the same document then read the sources at 10% of the input price instead of writing them again — before this, every review request wrote its whole prompt to the cache and none ever read it back, because the drafts came before the sources. `DealContextProvider` prepends the transaction context as a first unmarked segment, so the first marked segment covers it too. Providers without `supports_prompt_segments` (OpenAI, the test fakes) receive the flattened string from `_complete_json`; Luna relies on OpenAI's automatic prefix caching, which the same ordering serves. Usage logs expose cached input tokens for both providers.
- **Anthropic SDK 1.x**: `requirements.txt` pins `anthropic>=1,<2`. The 1.x SDK removed `temperature`/`top_p`/`top_k` from the `messages.create()` signature (passing them is a `TypeError`), so `AnthropicLLMProvider` sends `temperature=0` through `extra_body`, and only for model families that still accept sampling parameters (Claude 4.6/4.5 line and older — `_accepts_sampling_params`). Opus 4.7+, Sonnet 5 and the Claude 5 family reject sampling parameters with a 400, so for those the request carries none.
- **Parallel LLM fan-out**: per-document LLM work inside each pipeline stage (routing, contract, corporate, corporate-intro) runs on a bounded thread pool via `packages/agents/concurrency.run_llm_tasks` (`LLM_MAX_CONCURRENCY`, default 4). Worker functions are pure (LLM + parse only — no `Session` access); persistence happens on the caller's thread in input order. Contract analysis now inserts only the clauses that survive filtering (no insert-then-delete churn). **One document's failed request never discards the stage** (`isolate_failures=True`, also on `document_coverage.collect_documents_payloads` for the financial batch queue): a document whose model request fails (output truncated at the token limit after the single compact retry, refusal, malformed JSON) comes back as a `TaskFailure` in its slot, the stage persists the other documents, records the gap through `packages/agents/stage_failures.record_unanalysed_documents` (a medium-priority `OpenQuestion` per document in the report language, replaced on every run of the stage, plus `failed_documents` in the stage result) and completes. A stage still fails when *every* document failed, so a systemic fault (credentials, a broken prompt) stays loud. A truncated answer (`LLMTruncatedError`) is retried once by `_complete_json` with a compactness instruction, since a runaway generation is stochastic; the partial records of a truncated answer are never used. Clause extraction caps its output budget at the batch length (min 3072 tokens), because clauses are quotations of the batch and a runaway on a two-page contract must stop early.
- **No DB transaction across the LLM phase** (`packages/agents/stage_tx.release_connection_before_llm`): every fan-out stage (routing, contract, corporate, corporate-intro, tax, financial) opens its running `AgentRun`, copies the worker inputs out of the ORM into plain values, **commits** (connection back to the pool, running row visible to the SSE stream), fans out, and only then — in a fresh transaction — deletes the previous outputs and persists the new ones. Before this, the contract stage held an idle transaction for 925 s on a 66-document data room; the managed Postgres proxy closed the connection and the first write failed with `SSL connection has been closed unexpectedly`, rolling back the whole stage. A failed stage still rolls its deletes back (previous outputs survive). Worker lambdas must never touch ORM instances (expired after the commit). Belt and braces: `db/session.py` sets TCP keepalives + `pool_recycle=1800` on Postgres connections.

- **Sign-in with Microsoft and Google** (`app/services/oauth.py`, `app/api/routes/oauth.py`): OpenID Connect authorization code + PKCE; both browser legs go through the frontend's `/api` proxy, so the redirect URI is `{FRONTEND_URL}/api/auth/oauth/{provider}/callback` and the session cookie lands on the frontend origin like the password login's. State, nonce and PKCE verifier travel in a signed 10-minute HttpOnly cookie (`dm_oauth`), nothing server-side. The ID token is the only identity evidence: RS256 signature against the provider's JWKS (one refetch on an unknown `kid`), issuer (Microsoft's `{tenantid}` template filled from the token's `tid`), audience, expiry, nonce. An identity is keyed by provider + subject; a first sign-in links to the account with the same email, or creates one, **only when the provider vouches for the address** (Google `email_verified`; Microsoft `xms_edov` or the consumer tenant), since a Microsoft tenant admin can put any address on a work account. Accounts created this way store an unusable marker (`!` + random) as `hashed_password`, so the session/reset fingerprints keep working, no password matches, and "Password dimenticata?" gives them one. Deleting such an account needs a session issued in the last ten minutes (`iat`, `reauth_required`) instead of the password; the account page sends the person through the provider again with `?confirm=delete`. `oauth_identities` is not under RLS (read before a tenant is known), like `users`. Migration `022` grants it to every role that has DML on `users` (the production API runs as a non-owner role, and 021 left the table unreadable to it: the first sign-in failed with `permission denied`), and sets default privileges so tables created by later migrations are granted too.

- **Postgres Row-Level Security (RLS)** — defense-in-depth on top of the application-level filters. Migration `012` enables RLS + `FORCE` + tenant-isolation policies on every workspace/deal/document-scoped table (incl. `company_profiles`). The auth dependency and every fresh `SessionLocal` (HTTP request, BackgroundTask, Arq worker, SSE stream) bind the tenant via `set_tenant_context(db, user_id)`, which writes the `app.current_user_id` GUC. A pool `checkin` event clears the GUC when a connection is returned. SQLite (test env) and superuser Postgres connections are no-ops — see "Enforcing RLS in production" below.

### Enforcing RLS in production
Postgres superusers (and roles with `BYPASSRLS`) ignore RLS unconditionally. Railway's default `postgres` user is a superuser, so out of the box the policies installed by migration `012` are inert. To actually enforce them:

```sql
-- One-time setup (run as superuser on the production DB)
CREATE ROLE diligenx_app WITH LOGIN PASSWORD '<strong-random-pw>';
GRANT CONNECT ON DATABASE diligenx TO diligenx_app;
GRANT USAGE ON SCHEMA public TO diligenx_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO diligenx_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO diligenx_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO diligenx_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO diligenx_app;
```

Then on Railway, change `DATABASE_URL` on the API service to use `diligenx_app` instead of `postgres`, and set `MIGRATIONS_DATABASE_URL` to the original `postgres` connection string: the container start command runs `alembic upgrade head` before uvicorn, and `alembic/env.py` migrates `MIGRATIONS_DATABASE_URL` when set (falling back to `DATABASE_URL`), so the app role never needs DDL privileges.

To verify RLS is active in production, run from the API container:
```sql
SELECT current_user, current_setting('is_superuser'), current_setting('app.current_user_id', true);
-- Expect: diligenx_app | off | <some int after a request>
```

Enforcement tests live in `tests/test_rls_isolation.py` (opt-in: set `RLS_TEST_DATABASE_URL` to a non-superuser Postgres role).


## Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/diligenx` | Database connection |
| `MIGRATIONS_DATABASE_URL` | _(empty)_ | Optional DDL-capable URL used only by Alembic (`alembic/env.py`); falls back to `DATABASE_URL`. Set it to the `postgres` owner when `DATABASE_URL` uses the RLS role `diligenx_app` |
| `SECRET_KEY` | `change-me-in-production` | JWT signing key (startup guard refuses the default in production) |
| `AUTH_COOKIE_SECURE` | `true` | Secure attribute on auth cookies; set `false` only for local http dev |
| `MICROSOFT_CLIENT_ID` / `MICROSOFT_CLIENT_SECRET` | _(empty)_ | Entra ID app registration; both set → "Accedi con Microsoft" on the login page. ID tokens need the optional claims `email` and `xms_edov` |
| `MICROSOFT_TENANT` | `organizations` | `organizations` (work accounts), `common` (also personal) or one tenant id |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | _(empty)_ | Google OAuth web client; both set → "Accedi con Google" |
| `ALLOWED_ORIGINS` | `["http://localhost:3000"]` | CORS origins |
| `UPLOAD_DIR` | `uploads` | Local file upload directory (when `S3_BUCKET` empty) |
| `MAX_UPLOAD_SIZE_MB` | `50` | Max upload size |
| `S3_BUCKET` | _(empty)_ | If set, files go to S3/R2 instead of local disk |
| `S3_ENDPOINT_URL` | _(empty)_ | R2: `https://<account_id>.r2.cloudflarestorage.com` |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | _(empty)_ | S3 credentials |
| `S3_REGION` | `auto` | `auto` for R2, `eu-west-1` for AWS |
| `OPENAI_API_KEY` | _(empty)_ | Required for Luna analysis/Q&A and real embeddings; required in beta |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI model name |
| `EMBEDDING_DIMENSION` | `1536` | Vector dimension |
| `ANTHROPIC_API_KEY` | _(empty)_ | Required only for an explicit `claude-*` analysis model |
| `ANALYSIS_MODEL` | `gpt-5.6-luna` | Model for the bulk-reading stages (routing, contract, corporate, corporate-intro, tax, financial) and document Q&A, shared by API and worker |
| `JUDGMENT_MODEL` | _(empty = `ANALYSIS_MODEL`)_ | Model for the judgment stages: red-flag aggregation, source-fidelity review, executive summary. Production runs `claude-sonnet-5` (needs `ANTHROPIC_API_KEY` on worker and API). A `set_llm_provider` test stub covers both roles |
| `LLM_MAX_CONCURRENCY` | `4` | Max parallel per-document LLM calls within an analysis stage (`1` = sequential) |
| `WORKER_JOB_TIMEOUT_SECONDS` | `10800` | Arq job timeout for one whole analysis run (every stage, including the aggregation and its source-fidelity review); the child process gets the same deadline. A 66-document data room needs well over the previous default of one hour |
| `REDIS_URL` | _(empty)_ | If set, `/analyze` and `/upload` enqueue jobs to Arq instead of FastAPI BackgroundTasks. Run a worker alongside the API: `arq app.worker.WorkerSettings`. Format: `redis://default:<pw>@host:port` or `rediss://...` (TLS, recommended on Upstash). |
