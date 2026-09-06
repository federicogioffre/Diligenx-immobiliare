# Diligenx — Project Context

## Stack
- **Backend:** FastAPI + SQLAlchemy 2.0 (mapped_column style) + Pydantic v2
- **Database:** PostgreSQL (default) + pgvector extension; SQLite for tests
- **Auth:** JWT via HttpOnly session cookie (browser) or Bearer header (API clients) → `python-jose` + `bcrypt` (no passlib); SSE authenticated by short-lived deal-scoped tickets
- **Migrations:** Alembic (`apps/api/alembic/`)
- **Embeddings:** OpenAI `text-embedding-3-small` (1536 dims); `FakeEmbeddingProvider` for tests
- **LLM:** Anthropic Claude (`claude-sonnet-4-6` by default); `FakeLLMProvider` for tests
- **Storage:** S3-compatible (Cloudflare R2 in prod); local disk fallback when `S3_BUCKET` empty
- **Rate limiting:** `slowapi` (in-memory); disabled in tests via autouse fixture
- **Background jobs:** `BackgroundTasks` by default; **Arq + Redis** opt-in via `REDIS_URL` for durable jobs
- **Env:** `.env` via `pydantic-settings`
- **Frontend:** Next.js 15 (App Router, TypeScript) — login + dashboard + insights + deals UI, server-side auth via cookie
- **Frontend tests:** Playwright smoke suite (3 tests) in `apps/web/tests/e2e/`
- **Tests:** pytest + FastAPI TestClient (SQLite), **855 passing**

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
│   │   │   ├── user.py                   # User → owns Workspaces
│   │   │   ├── workspace.py              # Workspace → owner_id FK to User
│   │   │   ├── deal.py                   # Deal + DealStatus(draft|analyzing|reviewed|closed) → workspace_id FK
│   │   │   ├── document.py               # Document + DocumentStatus(pending|processing|processed|failed) + language + raw_text
│   │   │   ├── document_chunk.py         # DocumentChunk + VectorType (pgvector on PG, JSON on SQLite) + EMBEDDING_DIM=1536
│   │   │   ├── clause_finding.py         # ClauseFinding + ClauseType enum
│   │   │   ├── red_flag.py               # RedFlag (issue/risk/recommendation triple) + Severity(low|medium|high) + DueDiligenceArea (11 standard DD report sections, incl. tax + financial) + source_document_id/source_page citation
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
│   │   │   ├── auth.py                   # get_current_user() — HTTPBearer dependency
│   │   │   ├── storage.py                # S3/R2 client + save_file/read_file (local fallback)
│   │   │   ├── jobs.py                   # enqueue_or_run() — Arq pool if REDIS_URL set, else BackgroundTasks
│   │   │   └── report_export.py          # Markdown → PDF (reportlab) / DOCX (python-docx)
│   │   ├── worker.py                     # Arq WorkerSettings; consumes jobs enqueued by the API
│   │   └── api/routes/
│   │       ├── health.py                 # GET /health
│   │       ├── auth.py                   # POST /auth/register, /auth/login
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
├── tests/                                # 855 passing
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
4b. **Corporate intro extraction** (`CorporateIntroAgent`) — extracts the Corporate Introductory Information for each target company (visure / atti / statuti) → `CompanyProfile` rows. Auto-detects corporate-looking docs via filename + first-1500-chars keyword match.
4c. **Tax documentary review** (`TaxAgent`) — analyses tax documents (avvisi di accertamento, cartelle, rateizzazioni, crediti d'imposta, regimi speciali, TP, DURF) selected by keyword auto-detection ∪ routing classification (`document_type=tax`). LLM findings + deterministic keyword heuristics as a floor (a notified accertamento can never be silently dropped) → `AgentFinding` rows (`agent_name=tax_analysis`) that flow into stage 5 with `area=tax`. Each finding carries a **`defensibility`** grade (`actual|high|medium|low` — how the position would hold up *if challenged*, the scale real tax advisers use; it is **not** a probability of being audited, which nothing in the pipeline estimates), plus `tax_kind`, `legal_basis`, `fiscal_years`, `mitigating_factors` and an `amount_eur` **only when the document itself states one**. `severity` is derived from the grade in code (`actual` → high, never downgraded). Statutory references and assessment-period expiry per fiscal year come from `tax_rules_registry`. Documentary review only — the report boilerplate states it does not substitute a full tax/financial DD by the client's advisors.
4d. **Financial documentary review** (`FinancialAgent`) — analyses financial statements and their annexes (bilanci, note integrative, relazioni sulla gestione / del collegio sindacale / della società di revisione) selected by keyword auto-detection ∪ routing classification (`document_type=financial_statement`). LLM findings (auditor_opinion, going_concern, capital_loss, covenant, related_party, guarantee, subsequent_event, equity_position) + deterministic keyword heuristics as a floor (a going-concern paragraph or an art. 2446/2482-bis c.c. loss can never be silently dropped; article numbers match only with an `art.` prefix or `c.c.` suffix, so amounts in the accounts don't false-positive) → `AgentFinding` rows (`agent_name=financial_analysis`) that flow into stage 5 with `area=financial`. A **legal** review of financial documents, not an accounting analysis: no ratios, no valuation.
5. **Red-flag aggregation** — produce `RedFlag` rows (Issue/Risk/Recommendation triple, severity low|medium|high, DD area, `source_document_id` + validated `source_page` pinpoint citation) + `OpenQuestion` items for high-severity flags. A cited `source_page` is kept only if it matches a real page of that document's ClauseFindings (guards against hallucinated citations).
6. **Report generation** (`report_agent.generate_due_diligence_report`) — bilingual (IT/EN — explicit `deal.report_language` or majority language of processed documents, fallback EN; LLM prose follows, boilerplate localized faithfully to studio practice: title/Executive Summary/Key Findings stay English) deterministic template (Introduction / Corporate Introductory Information from `CompanyProfile` / Executive Summary via LLM / Key Findings tabellari per DD area / Observations / Information Requests / Appendix Documents); stored as Markdown in `Report` table.

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
python -m pytest ../../tests -q   # 855 passed
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
- **Anthropic prompt caching**: every LLM prompt is sent with `cache_control={"type":"ephemeral"}` so the idempotent `/analyze` re-runs hit Anthropic's cache (~90% input-cost reduction within the 5-minute TTL).
- **Parallel LLM fan-out**: per-document LLM work inside each pipeline stage (routing, contract, corporate, corporate-intro) runs on a bounded thread pool via `packages/agents/concurrency.run_llm_tasks` (`LLM_MAX_CONCURRENCY`, default 4). Worker functions are pure (LLM + parse only — no `Session` access); persistence happens on the caller's thread in input order. Contract analysis now inserts only the clauses that survive filtering (no insert-then-delete churn).

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
| `ALLOWED_ORIGINS` | `["http://localhost:3000"]` | CORS origins |
| `UPLOAD_DIR` | `uploads` | Local file upload directory (when `S3_BUCKET` empty) |
| `MAX_UPLOAD_SIZE_MB` | `50` | Max upload size |
| `S3_BUCKET` | _(empty)_ | If set, files go to S3/R2 instead of local disk |
| `S3_ENDPOINT_URL` | _(empty)_ | R2: `https://<account_id>.r2.cloudflarestorage.com` |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | _(empty)_ | S3 credentials |
| `S3_REGION` | `auto` | `auto` for R2, `eu-west-1` for AWS |
| `OPENAI_API_KEY` | _(empty)_ | For real embeddings; omit for FakeEmbeddingProvider |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI model name |
| `EMBEDDING_DIMENSION` | `1536` | Vector dimension |
| `ANTHROPIC_API_KEY` | _(empty)_ | For real LLM calls; omit for FakeLLMProvider |
| `ANALYSIS_MODEL` | `claude-sonnet-4-6` | Claude model for the analysis pipeline |
| `LLM_MAX_CONCURRENCY` | `4` | Max parallel per-document LLM calls within an analysis stage (`1` = sequential) |
| `REDIS_URL` | _(empty)_ | If set, `/analyze` and `/upload` enqueue jobs to Arq instead of FastAPI BackgroundTasks. Run a worker alongside the API: `arq app.worker.WorkerSettings`. Format: `redis://default:<pw>@host:port` or `rediss://...` (TLS, recommended on Upstash). |
