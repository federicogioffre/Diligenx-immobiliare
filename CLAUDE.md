# Diligenx Immobiliare — Project Context

Due diligence assisted by AI for the **purchase of an Italian residential property**:
the documents of the purchase (deed, cadastral extract and floor plan, registry
search, building permits, condominium papers, leases) go in; a report of the
issues to settle before the preliminary contract or the deed comes out.

## Relationship with Diligenx (upstream)

This repository was created from Diligenx (M&A due diligence) **with its git
history**: `upstream` → `https://github.com/federicogioffre/diligenx`. The engine
is shared; the domain is not.

- **Engine — keep identical to upstream** so its fixes port with
  `git fetch upstream && git cherry-pick <sha>` (or `git merge upstream/main`):
  `apps/api/app/core|db|services`, auth/OAuth, credits, RLS, SSE, Arq,
  `packages/parsing`, `packages/retrieval`, and in `packages/agents`:
  `concurrency`, `stage_tx`, `stage_failures` (except its stage labels),
  `document_coverage`, `grounding_review`, `deal_context`, `deal_analysis_agent`
  (providers, JSON transport), `output_language`, `evidence`, `deal_qa_agent`.
  New code goes in new files; a change the engine needs is better made upstream first.
- **Domain — this repository's own**: `packages/real_estate/` and the files
  wired to it (`orchestrator`, `analysis_checkpoint.STAGES`, `intake_agent`,
  `red_flag_aggregator`, `report_agent`, the deal page and findings page).
- **Migrations**: this repository's revisions are `r025`, `r026`, … after
  upstream's `024`. A migration ported from upstream is renumbered at the end
  of the `r` chain (new `revision`, `down_revision` = the current head), so the
  history stays linear.

## Stack
- **Backend:** FastAPI + SQLAlchemy 2.0 (mapped_column style) + Pydantic v2
- **Database:** PostgreSQL (default) + pgvector extension; SQLite for tests
- **Auth:** JWT via HttpOnly session cookie (browser) or Bearer header (API clients) → `python-jose` + `bcrypt` (no passlib); sign-in with Microsoft / Google over OpenID Connect (code + PKCE, `docs/OAUTH_SETUP.md`); SSE authenticated by short-lived deal-scoped tickets
- **Migrations:** Alembic (`apps/api/alembic/`)
- **Embeddings:** OpenAI `text-embedding-3-small` (1536 dims); `FakeEmbeddingProvider` for tests
- **LLM:** OpenAI GPT-5.6 Luna (`gpt-5.6-luna` by default) for every analysis stage and document Q&A; `FakeLLMProvider` for tests
- **Storage:** S3-compatible (Cloudflare R2 in prod); local disk fallback when `S3_BUCKET` empty
- **Rate limiting:** `slowapi` (in-memory); disabled in tests via autouse fixture. Keyed on the browser's address, which the frontend middleware forwards on every `/api` call in `x-diligenx-client-ip` with `PROXY_SHARED_SECRET` (`app/core/limiter.client_ip`; without the secret the key is the TCP peer, i.e. the proxy — one bucket for every user). Failed password logins are also counted per account and reset emails per mailbox (`LOGIN_FAILURES_PER_ACCOUNT`, `PASSWORD_RESETS_PER_ACCOUNT`)
- **Background jobs:** `BackgroundTasks` by default; **Arq + Redis** opt-in via `REDIS_URL` for durable jobs
- **Env:** `.env` via `pydantic-settings`
- **Frontend:** Next.js 15 (App Router, TypeScript) — login + dashboard + insights + deals UI, server-side auth via cookie
- **Frontend design system:** tokens in `apps/web/tailwind.config.ts` — `blue-*` resolves to the brand ultramarine scale, `ink` is the dark surface, Geist / Geist Mono / Instrument Serif (`font-display`) self-hosted via `next/font` (no request to Google from the browser); shared utilities (`bg-grid`, `glass`, `reveal`, `text-gradient`) in `globals.css`; `MainContainer` renders `/` and `/login` full-bleed. **Dark mode** (signed-in area only): every palette (`slate`, `blue`, `red`, `amber`, `emerald`, `orange`, `violet`, `indigo`) and `surface` (cards/inputs — use `bg-surface`, not `bg-white`) read `--c-*` RGB variables redefined under `.dark` in `globals.css`, so most classes need no `dark:` twin; only dark-filled buttons (`bg-slate-800/900`, `bg-ink`) and `prose` (`dark:prose-invert`) do. `components/theme/ThemeProvider` sets `.dark` from the `dm_theme` localStorage preference (light | dark | absent = system), never on `/` and `/login`; an inline boot script in `<head>` applies it before first paint
- **Frontend tests:** Playwright suite in `apps/web/tests/e2e/` (the 3 `smoke.spec.ts` tests need the API on :8000 and still expect `/` to redirect to `/login`, which upstream changed: they fail identically upstream)
- **Tests:** pytest + FastAPI TestClient (SQLite), **1165 passing**

## Project Root
```
/home/user/diligenx-immobiliare/
```

## Structure

```
diligenx-immobiliare/
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
│   │   │   ├── credit_transaction.py     # CreditTransaction ledger (grant/charge/refund) behind users.credit_balance
│   │   │   ├── workspace.py              # Workspace → owner_id FK to User
│   │   │   ├── deal.py                   # Deal + DealStatus(draft|analyzing|reviewed|closed) → workspace_id FK
│   │   │   ├── document.py               # Document + DocumentStatus(pending|processing|processed|failed) + language + raw_text
│   │   │   ├── document_chunk.py         # DocumentChunk + VectorType (pgvector on PG, JSON on SQLite) + EMBEDDING_DIM=1536
│   │   │   ├── clause_finding.py         # ClauseFinding + ClauseType enum
│   │   │   ├── red_flag.py               # RedFlag (issue/risk/recommendation triple) + Severity(low|medium|high) + DueDiligenceArea (property areas from r025; the M&A values stay for stored data) + source_document_id/source_page citation + remedy_type/impact tags + structured_payload_json
│   │   │   ├── property_profile.py       # PropertyProfile: what one document states about one unit (cadastral ids, holders, title)
│   │   │   ├── company_profile.py        # legacy M&A table, no longer written
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
│   │   │   ├── credits.py                # prepaid credits: analysis_cost (pages), atomic charge (402), refund, signup grant
│   │   │   ├── jobs.py                   # enqueue_or_run() — Arq pool if REDIS_URL set, else BackgroundTasks
│   │   │   └── report_export.py          # Markdown → PDF (reportlab) / DOCX (python-docx)
│   │   ├── credits_cli.py                # `python -m app.credits_cli list|balance|grant` — top up credits
│   │   ├── worker.py                     # Arq WorkerSettings; consumes jobs enqueued by the API
│   │   └── api/routes/
│   │       ├── health.py                 # GET /health
│   │       ├── auth.py                   # POST /auth/register, /auth/login
│   │       ├── oauth.py                  # GET /auth/oauth/providers, /{provider}/start, /{provider}/callback
│   │       ├── workspaces.py             # CRUD + /workspaces/{id}/insights aggregate
│   │       ├── admin.py                  # /admin/users, /admin/credits — credit administration (ADMIN_EMAILS)
│   │       ├── deals.py                  # CRUD + /analyze /report /ask /agent-runs /risk-score /open-questions /missing-documents /property-profiles /pipeline-stages
│   │       └── documents.py              # /upload, /upload-batch, list, delete
│   ├── alembic/versions/                 # 001..024 from upstream, then r025 (property dd_area values), r026 (property_profiles under RLS)
│   ├── alembic.ini, requirements.txt, pyproject.toml, Dockerfile, .env.example
│
├── apps/web/                             # Next.js 15 frontend (functional)
│   ├── src/app/
│   │   ├── layout.tsx, page.tsx, globals.css
│   │   ├── login/                        # email/password form → cookie
│   │   ├── dashboard/                    # workspace switcher, deal list
│   │   ├── dashboard/insights/           # 4 aggregate widgets (pipeline, severity, top categories, completeness)
│   │   └── deals/[id]/                   # purchase detail: property card, severity + follow-up widgets, upload, analyze, report
│   │       └── findings/                 # red-flag list filterable by remedy and impact (clauses only for legacy analyses)
│   ├── src/components/                   # shared UI (toasts, modals, upload zone)
│   ├── src/lib/api.ts                    # typed API client
│   ├── src/lib/pipeline.ts               # stage list + labels (mirrors packages/real_estate/pipeline.py; tests/test_re_frontend_contract.py)
│   ├── src/middleware.ts                 # server-side auth guard via cookie
│   ├── tests/e2e/                        # Playwright smoke suite (run with `pnpm test:e2e`)
│   ├── playwright.config.ts
│   ├── package.json, next.config.ts, Dockerfile
│
├── packages/
│   ├── real_estate/                      # ★ The property domain
│   │   ├── pipeline.py                   # STAGE_LIST: the ten stages, labels, progress-reporting stages
│   │   ├── checklist.py                  # documents a buyer should receive (sections A–I) → MissingDocument
│   │   ├── document_types.py             # routing vocabulary + classification prompt; unknown type → "other"
│   │   ├── areas.py                      # report areas, titles it/en, area guide for the aggregation prompt
│   │   ├── rules_registry.py             # dated Italian rules + donation / mortgage / twenty-year chain windows, no amounts
│   │   ├── prompts.py                    # identity, four reviewers, aggregation, executive summary
│   │   ├── stage_support.py              # AgentRun lifecycle, routed ∪ keyword document selection
│   │   ├── property_identity_agent.py    # stage 3: PropertyProfile rows, identifiers grounded in the text
│   │   ├── property_identity.py          # consolidation: one value per field per unit, conflicts among authoritative sources
│   │   ├── review_agent.py               # DocumentReviewAgent: batching, keyword floor, amount grounding, persistence
│   │   ├── specialists.py                # stages 4–7: title chain, encumbrances, building/cadastral, condominium/occupancy
│   │   ├── consistency.py                # stage 8: deterministic cross-document checks
│   │   └── fake_provider.py              # FakeRealEstateLLMProvider for tests (answers from the fixture text)
│   ├── agents/                           # Engine shared with Diligenx + the wired domain stages
│   │   ├── deal_analysis_agent.py        # LLMProvider ABC + Anthropic/OpenAI/Fake providers, JSON transport
│   │   ├── orchestrator.py               # ★ run_deal_analysis_pipeline() — runs real_estate.pipeline, AgentRun tracking
│   │   ├── intake_agent.py               # inventory + checklist gaps
│   │   ├── red_flag_aggregator.py        # RedFlag + OpenQuestion, property vocabularies and severity floors
│   │   ├── grounding_review.py           # source-fidelity review of every draft flag and of the summary
│   │   ├── report_agent.py               # Markdown report → Report row
│   │   ├── deal_qa_agent.py              # RAG Q&A over deal documents
│   │   ├── concurrency.py, stage_tx.py, stage_failures.py, document_coverage.py, analysis_checkpoint.py
│   │   ├── scoring_service.py            # compute_risk_score(deal_id)
│   │   └── deal_agent.py                 # legacy single-shot agent (kept for back-compat)
│   ├── prompts/deal_prompts.py           # engine prompts: Q&A and the legacy single-shot analysis
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
├── tests/                                # test_re_* for the property domain; the rest pins the engine
└── CLAUDE.md                             # ← this file
```

## Data Model

```
User 1──* Workspace 1──* Deal 1──* Document 1──* DocumentChunk (embedding VECTOR(1536))
                              │           └──* ClauseFinding (legacy, not written)
                              ├──* PropertyProfile (one per unit per document; source_document_id → Document)
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
| POST | `/deals/{deal_id}/analyze` | **202** → queues multi-agent pipeline in BackgroundTask (**402** `insufficient_credits` when credits are on and the balance is short) |
| GET | `/deals/{deal_id}/analysis-cost` | Credits the analysis would cost now (pages of processed documents) vs. balance |
| GET | `/users/me/credits` | Credit balance + last 50 ledger movements |
| GET | `/admin/users?q=` | Admin only: accounts with their credit balance |
| POST | `/admin/credits` | Admin only: grant (or, negative, remove) credits for an email |
| GET | `/deals/{deal_id}/agent-runs` | List AgentRun rows in pipeline order |
| POST | `/deals/{deal_id}/stream-ticket` | Short-lived deal-scoped ticket for the SSE stream |
| GET | `/deals/{deal_id}/analysis-stream` | SSE stream of pipeline progress (`?ticket=` from stream-ticket) |
| POST | `/deals/{deal_id}/report` | Generate Markdown due-diligence report |
| GET | `/deals/{deal_id}/report` | Get current report |
| GET | `/deals/{deal_id}/report/export?format=pdf\|docx` | Branded export |
| POST | `/deals/{deal_id}/ask` | RAG Q&A with citations |
| GET | `/deals/{deal_id}/clause-findings` | List clauses (legacy analyses only) |
| GET | `/deals/{deal_id}/red-flags` | List red flags |
| GET | `/deals/{deal_id}/risk-score` | Computed risk score |
| GET | `/deals/{deal_id}/open-questions` | Follow-up questions raised by the pipeline (priority-ordered) |
| GET | `/deals/{deal_id}/missing-documents` | Checklist items expected at intake but absent |
| GET | `/deals/{deal_id}/property-profiles` | Property units consolidated across documents, with sources and conflicting fields |
| GET | `/deals/pipeline-stages` | The analysis stages in order, with their labels |
| GET | `/workspaces/{id}/insights` | Aggregate metrics (status mix, severity, top categories, completeness) |
| POST | `/documents/upload?deal_id=N` | **201** → file saved, ingestion runs in BackgroundTask (or Arq if `REDIS_URL` set) |
| POST | `/documents/upload-batch?deal_id=N` | Multi-file upload |
| GET | `/documents/deals/{deal_id}/documents` | List deal's documents |
| DELETE | `/documents/{document_id}` | Delete document |

## Analysis Pipeline (`packages/agents/orchestrator.run_deal_analysis_pipeline`)
Triggered async by `POST /deals/{id}/analyze`. The stages are listed once, in `packages/real_estate/pipeline.STAGE_LIST`; the orchestrator, the resume checkpoint, the SSE stream and `GET /deals/pipeline-stages` all read it. Each stage gets its own `AgentRun`; a failing stage marks itself failed, independent stages continue, dependent ones are blocked, and aggregation and report require every earlier stage. All stages are idempotent and follow the engine's contract: commit the running `AgentRun` before the LLM phase, delete previous outputs and write new ones in a fresh transaction, and a document whose request fails keeps its previous outputs and becomes a medium-priority `OpenQuestion`.

1. **Intake** — validate, status → `analyzing`, inventory, `MissingDocument` for every item of `real_estate/checklist.py` no document matches (file name + first 1 000 characters; keywords match at a word start, short ones as whole words, so "ape" does not match "apertura"). Sections: A provenienza, B ipotecaria, C catasto, D urbanistica-edilizia, E condominio, F impianti ed energia, G occupazione, H parte venditrice, I operazione.
2. **Document routing** — classify into the property vocabulary (`document_types.py`: atto_provenienza, successione, ispezione_ipotecaria, visura_catastale, planimetria, titolo_edilizio, agibilita, cdu, ape, conformita_impianti, regolamento_condominiale, verbale_assemblea, situazione_condominiale, locazione, preliminare, perizia, documento_venditore, other). An unknown answer becomes `other` instead of failing the stage: the reviewers also select by keyword.
3. **Property identification** (`PropertyIdentityAgent`) — one `PropertyProfile` per unit per document (deeds, cadastral extracts, floor plans, successions, preliminaries, valuations). A foglio/particella/subalterno the model returns is kept only if it appears in the text it read. `property_identity.consolidate_property_profiles` groups rows by cadastral identifiers and states one value per field from the most authoritative source (deed → cadastral extract → floor plan → succession → registry search → preliminary → valuation), recording every alternative and naming a field as conflicting only when authoritative sources disagree.
4–7. **Reviewers** (`specialists.py`, all `DocumentReviewAgent`s) — **title chain** (donations, oppositions, successions and acceptance, marital regime, family fund, twenty-year gap, powers of attorney), **encumbrances** (mortgages, foreclosures, seizures, transcribed claims, easements, family fund, transcribed preliminaries, tax liens), **building and cadastral** (cadastral nonconformity, building irregularities, pending amnesties, habitability, Superbonus, pre-1967, constraints), **condominium and occupancy** (arrears, approved works, use restrictions, condominium litigation, leases, occupants without title). Each selects documents by routing ∪ keyword, batches them on one bounded queue, grounds amounts on a verbatim quotation, and adds a **keyword floor** for matters that must never be dropped (a "pignoramento" in a registry search is always a high finding). Dates are never judged by the model: the title-chain reviewer computes whether a donation is still within the twenty-year window of art. 563 c.c. and raises it to high if so, the encumbrances reviewer whether a mortgage registration has passed twenty years (art. 2847 c.c.: "lapsed unless renewed", never "cancelled").
8. **Consistency check** (`consistency.py`, no model) — compares the profiles across documents: a unit the deed or floor plan identifies that the cadastral extract does not list or lists under another subalterno; owners of record against the deed's acquirers and against the sellers in a preliminary or valuation (high without any overlap, medium with partial overlap; name order and case ignored, tax code preferred); category; surface beyond 10 %; twenty-year chain coverage of the dated titles. Each discrepancy names both documents and both values and never decides which is right.
9. **Red-flag aggregation** — the engine's aggregation with the property vocabularies: areas (`areas.py`), remedies `condition_precedent | seller_undertaking | escrow | warranty | price_adjustment | pre_closing_verification | information_request`, impacts `value | deed | other` (unknown → null), dated rules from `rules_registry.rules_context()` in the prompt, and a severity floor that raises — never lowers — foreclosures, seizures, transcribed claims, owner mismatches and donations within the window. Every draft passes the source-fidelity review; a rejected draft becomes an `OpenQuestion`.
10. **Report** — "Relazione di Due Diligence Immobiliare / Real Estate Due Diligence Report": introduction (purpose, areas, the twenty-year coverage computed from the titles on file, exclusion of inspection and municipal records, costs left to notary and technician), **Identificazione dell'Immobile** (one table per unit), Executive Summary (grounded), Key Findings per property area with the remedy tag, Observations, Information Requests by checklist section, Appendix.

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
python -m pytest ../../tests -q   # 1165 passed
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
- **Worker waits for the API's migrations**: a deploy starts API and worker together and only the API runs `alembic upgrade head`, so under `BETA_MODE` the worker's startup retries `validate_beta_database` every 5 s for up to 5 min while it raises `PendingMigrationsError` (any other beta check still stops it at once). Before this, the deploy of migration 023 crashed the worker: it checked the revision before the API had migrated, and Railway had already removed the previous worker.
- **Durable jobs**: when `REDIS_URL` is set, `/analyze` and `/upload` enqueue jobs to an Arq pool (managed via FastAPI lifespan); a separate worker process consumes them (`arq app.worker.WorkerSettings`). When unset, jobs run in-process via FastAPI `BackgroundTasks` — same behaviour as before. Enqueue failures fall back transparently.
- **Property rules are dated, never prompted**: `packages/real_estate/rules_registry.py` holds the rules by `rule_id` with `valid_from`/`valid_to` **dates**, a citation and a bilingual gloss (art. 563 c.c., art. 29 c. 1-bis L. 52/1985, art. 46 D.P.R. 380/2001 and art. 40 L. 47/1985, art. 63 disp. att. c.c. before and after L. 220/2012, artt. 2847/2850 c.c., artt. 177/180/184 c.c., art. 169 c.c., artt. 2648/2650 c.c., D.M. 37/2008, art. 6 D.Lgs. 192/2005), plus the deterministic windows. It carries **no amount** — no penalty, tax or regularisation cost; a test asserts the glosses contain no percentage and no euro figure.
- **GPT-5.6 Luna migration**: the default is `gpt-5.6-luna` for all analysis and document Q&A. OpenAI Responses requests set `reasoning.effort=none`, `store=false` and `truncation=disabled`. Structured extraction uses one forced function call; grounding reviews use strict schemas. Refusals, incomplete responses and malformed data are failures, not analysis evidence. `ANALYSIS_MODEL` overrides take precedence on both API and worker; an explicit `claude-*` override selects Anthropic. A missing selected API key never silently switches providers.
- **Two models, by role** (`get_llm_provider` / `get_judgment_provider`): about 90% of a run's tokens are bulk reading (a ledger chunk that yields nothing, a classification), where the cheapest capable model wins; the 10% that decide the report — consolidating a thousand specialist findings into flags, verifying quotations, writing the summary — run on `JUDGMENT_MODEL` (production: `claude-sonnet-5`, measured at roughly $7 per 66-document run on top of Luna's $3). The orchestrator hands the judgment provider to the aggregation and report stages, `generate_due_diligence_report` and `RedFlagAggregationAgent` default to it, and an explicitly injected provider serves every stage so tests never reach a vendor.
- **Anthropic prompt caching follows the prompt's segments**: a prompt is either a plain string (one unmarked block, base price: a one-shot request has nothing to reuse, and marking it only paid the 125% cache-write premium) or a sequence of `PromptSegment`s, each becoming one content block, with `cache_control={"type":"ephemeral"}` on the segments marked `cache=True` (at most four). Caching is prefix-based, so stable content goes first: the source-fidelity review sends *instructions* (marked), then the JSON head with `kind`, `language` and `documents` (marked), then the tail with `items` and `validation_feedback` (unmarked), joined byte-for-byte into the same JSON as before. The correction pass and the later batches of the same document then read the sources at 10% of the input price instead of writing them again — before this, every review request wrote its whole prompt to the cache and none ever read it back, because the drafts came before the sources. `DealContextProvider` prepends the transaction context as a first unmarked segment, so the first marked segment covers it too. Providers without `supports_prompt_segments` (OpenAI, the test fakes) receive the flattened string from `_complete_json`; Luna relies on OpenAI's automatic prefix caching, which the same ordering serves. Usage logs expose cached input tokens for both providers.
- **Anthropic SDK 1.x**: `requirements.txt` pins `anthropic>=1,<2`. The 1.x SDK removed `temperature`/`top_p`/`top_k` from the `messages.create()` signature (passing them is a `TypeError`), so `AnthropicLLMProvider` sends `temperature=0` through `extra_body`, and only for model families that still accept sampling parameters (Claude 4.6/4.5 line and older — `_accepts_sampling_params`). Opus 4.7+, Sonnet 5 and the Claude 5 family reject sampling parameters with a 400, so for those the request carries none.
- **Parallel LLM fan-out**: per-document LLM work inside each pipeline stage (routing, property identification; the reviewers use one bounded batch queue) runs on a bounded thread pool via `packages/agents/concurrency.run_llm_tasks` (`LLM_MAX_CONCURRENCY`, default 4). Worker functions are pure (LLM + parse only — no `Session` access); persistence happens on the caller's thread in input order. Contract analysis now inserts only the clauses that survive filtering (no insert-then-delete churn). **One document's failed request never discards the stage** (`isolate_failures=True`, also on `document_coverage.collect_documents_payloads` for the financial batch queue): a document whose model request fails (output truncated at the token limit after the single compact retry, refusal, malformed JSON) comes back as a `TaskFailure` in its slot, the stage persists the other documents, records the gap through `packages/agents/stage_failures.record_unanalysed_documents` (a medium-priority `OpenQuestion` per document in the report language, replaced on every run of the stage, plus `failed_documents` in the stage result) and completes. A stage still fails when *every* document failed, so a systemic fault (credentials, a broken prompt) stays loud. A truncated answer (`LLMTruncatedError`) is retried once by `_complete_json` with a compactness instruction, since a runaway generation is stochastic; the partial records of a truncated answer are never used. Clause extraction caps its output budget at the batch length (min 3072 tokens), because clauses are quotations of the batch and a runaway on a two-page contract must stop early.
- **No DB transaction across the LLM phase** (`packages/agents/stage_tx.release_connection_before_llm`): every fan-out stage (routing, property identification, the four reviewers) opens its running `AgentRun`, copies the worker inputs out of the ORM into plain values, **commits** (connection back to the pool, running row visible to the SSE stream), fans out, and only then — in a fresh transaction — deletes the previous outputs and persists the new ones. Before this, the contract stage held an idle transaction for 925 s on a 66-document data room; the managed Postgres proxy closed the connection and the first write failed with `SSL connection has been closed unexpectedly`, rolling back the whole stage. A failed stage still rolls its deletes back (previous outputs survive). Worker lambdas must never touch ORM instances (expired after the commit). Belt and braces: `db/session.py` sets TCP keepalives + `pool_recycle=1800` on Postgres connections.

- **Prepaid credits** (`app/services/credits.py`, migration `023`): off unless `CREDITS_ENABLED`. One credit = one analysed page (`page_count`, else 3000 characters a page, at least 1 per document), because the model bill grows with the data room, not the number of runs. `/analyze` charges at admission in the same commit as the `analyzing` claim (a rejected claim rolls the charge back) and refunds when the job cannot be queued; `/resume-analysis` is free, since it finishes a run already paid. `/ask` and `POST /report` charge `ASK_CREDIT_COST` / `REPORT_CREDIT_COST`, committed before the model call, and refund on failure. The charge is a conditional `UPDATE ... WHERE credit_balance >= cost` (no overspend under concurrency) plus a `credit_transactions` row; insufficient balance → **402** with `code=insufficient_credits`, `required`, `balance`. New accounts (password or Microsoft/Google) receive `SIGNUP_CREDITS`; existing ones start at 0. `CREDITS_UNLIMITED_EMAILS` are never charged. The ledger is not under RLS (user-scoped, like `users`), is in the GDPR export and cascades on account deletion. The deal page shows cost and balance next to "Avvia Analisi"; the nav bar shows the balance on every signed-in page, and the account page the ledger. **Administrators** (`ADMIN_EMAILS`) grant or remove credits for any account at `/admin/credits` (ledger reason `grant`, the note records the administrator's address). The role needs a provider-vouched address: the account must carry a Microsoft/Google `OAuthIdentity` under the same email, because password registration does not verify email and anyone could otherwise register an administrator's address before its owner did.

- **Sign-in with Microsoft and Google** (`app/services/oauth.py`, `app/api/routes/oauth.py`): OpenID Connect authorization code + PKCE; both browser legs go through the frontend's `/api` proxy, so the redirect URI is `{FRONTEND_URL}/api/auth/oauth/{provider}/callback` and the session cookie lands on the frontend origin like the password login's. State, nonce and PKCE verifier travel in a signed 10-minute HttpOnly cookie (`dm_oauth`), nothing server-side. The ID token is the only identity evidence: RS256 signature against the provider's JWKS (one refetch on an unknown `kid`), issuer (Microsoft's `{tenantid}` template filled from the token's `tid`), audience, expiry, nonce. An identity is keyed by provider + subject; a first sign-in links to the account with the same email, or creates one, **only when the provider vouches for the address** (Google `email_verified`; Microsoft `xms_edov` or the consumer tenant), since a Microsoft tenant admin can put any address on a work account. Linking to an existing account **replaces its password with the unusable marker**: registration does not verify email, so the password may belong to someone who registered the address before its owner (pre-account hijacking — on an `ADMIN_EMAILS` address it would have made them administrator); the change of fingerprint also ends every session opened with it, and the owner gets a password back through the reset flow. Addresses are stored in lower case and unique case-insensitively (`ix_users_email_lower`, migration `024`, which stops and names the accounts if two differ only in case). Accounts created this way store an unusable marker (`!` + random) as `hashed_password`, so the session/reset fingerprints keep working, no password matches, and "Password dimenticata?" gives them one. Deleting such an account needs a session issued in the last ten minutes (`iat`, `reauth_required`) instead of the password; the account page sends the person through the provider again with `?confirm=delete`. `oauth_identities` is not under RLS (read before a tenant is known), like `users`. Migration `022` grants it to every role that has DML on `users` (the production API runs as a non-owner role, and 021 left the table unreadable to it: the first sign-in failed with `permission denied`), and sets default privileges so tables created by later migrations are granted too.

- **Postgres Row-Level Security (RLS)** — defense-in-depth on top of the application-level filters. Migration `012` enables RLS + `FORCE` + tenant-isolation policies on every workspace/deal/document-scoped table (incl. `company_profiles`; `r026` adds `property_profiles` with the same policy and grants, and `validate_beta_database` expects 13 protected tables). The auth dependency and every fresh `SessionLocal` (HTTP request, BackgroundTask, Arq worker, SSE stream) bind the tenant via `set_tenant_context(db, user_id)`, which writes the `app.current_user_id` GUC. A pool `checkin` event clears the GUC when a connection is returned. SQLite (test env) and superuser Postgres connections are no-ops — see "Enforcing RLS in production" below.

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
| `PROXY_SHARED_SECRET` | _(empty)_ | Same random value on **API and frontend**: the frontend middleware sends it with the browser's address so rate limits key on the real client. Empty → limits key on the proxy's address (shared by all users) |
| `LOGIN_FAILURES_PER_ACCOUNT` / `PASSWORD_RESETS_PER_ACCOUNT` | `10/15minutes` / `3/hour` | Failed password logins per account, reset emails per mailbox, from any address |
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
| `CREDITS_ENABLED` | `false` | Charge prepaid credits for analyses, questions and report regeneration |
| `SIGNUP_CREDITS` | `300` | Opening balance of every new account |
| `ASK_CREDIT_COST` / `REPORT_CREDIT_COST` | `1` / `5` | Credits per document question / per regenerated report (an analysis costs one per page) |
| `CREDITS_UNLIMITED_EMAILS` | `[]` | JSON list of addresses never charged (e.g. the owner) |
| `ADMIN_EMAILS` | `[]` | JSON list of addresses that may grant credits at `/admin/credits`; effective only on an account signed in with Microsoft/Google under that address |
| `LLM_MAX_CONCURRENCY` | `4` | Max parallel per-document LLM calls within an analysis stage (`1` = sequential) |
| `WORKER_JOB_TIMEOUT_SECONDS` | `10800` | Arq job timeout for one whole analysis run (every stage, including the aggregation and its source-fidelity review); the child process gets the same deadline. A 66-document data room needs well over the previous default of one hour |
| `REDIS_URL` | _(empty)_ | If set, `/analyze` and `/upload` enqueue jobs to Arq instead of FastAPI BackgroundTasks. Run a worker alongside the API: `arq app.worker.WorkerSettings`. Format: `redis://default:<pw>@host:port` or `rediss://...` (TLS, recommended on Upstash). |
