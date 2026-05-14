# Diligenx — Project Context

## Stack
- **Backend:** FastAPI + SQLAlchemy 2.0 (mapped_column style) + Pydantic v2
- **Database:** PostgreSQL (default) + pgvector extension; SQLite for tests
- **Auth:** JWT Bearer → `python-jose` + `bcrypt` (no passlib)
- **Migrations:** Alembic (`apps/api/alembic/`)
- **Embeddings:** OpenAI `text-embedding-3-small` (1536 dims); `FakeEmbeddingProvider` for tests
- **LLM:** Anthropic Claude (`claude-sonnet-4-6` by default); `FakeLLMProvider` for tests
- **Storage:** S3-compatible (Cloudflare R2 in prod); local disk fallback when `S3_BUCKET` empty
- **Rate limiting:** `slowapi` (in-memory); disabled in tests via autouse fixture
- **Env:** `.env` via `pydantic-settings`
- **Frontend:** Next.js 15 (App Router, TypeScript) — login + dashboard + deals UI, server-side auth via cookie
- **Tests:** pytest + FastAPI TestClient (SQLite), **573 passing**

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
│   │   │   ├── red_flag.py               # RedFlag + Severity(low|medium|high|critical)
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
│   │   │   └── report_export.py          # Markdown → PDF (reportlab) / DOCX (python-docx)
│   │   └── api/routes/
│   │       ├── health.py                 # GET /health
│   │       ├── auth.py                   # POST /auth/register, /auth/login
│   │       ├── workspaces.py             # GET|POST|PATCH|DELETE /workspaces
│   │       ├── deals.py                  # CRUD + /analyze /report /ask /agent-runs /risk-score etc.
│   │       └── documents.py              # /upload, /upload-batch, list, delete
│   ├── alembic/versions/                 # 001..007 + language column migration
│   ├── alembic.ini, requirements.txt, pyproject.toml, Dockerfile, .env.example
│
├── apps/web/                             # Next.js 15 frontend (functional)
│   ├── src/app/
│   │   ├── layout.tsx, page.tsx, globals.css
│   │   ├── login/                        # email/password form → cookie
│   │   ├── dashboard/                    # workspace switcher, deal list
│   │   └── deals/[id]/                   # deal detail, upload, analyze, report
│   ├── src/components/                   # shared UI (toasts, modals, upload zone)
│   ├── src/lib/api.ts                    # typed API client
│   ├── src/middleware.ts                 # server-side auth guard via cookie
│   ├── package.json, next.config.ts, Dockerfile
│
├── packages/
│   ├── agents/                           # ★ Multi-agent analysis pipeline (fully wired)
│   │   ├── base.py                       # BaseAgent ABC
│   │   ├── deal_analysis_agent.py        # LLMProvider ABC + AnthropicLLMProvider + FakeLLMProvider, grounding check
│   │   ├── orchestrator.py               # ★ run_deal_analysis_pipeline() — 6 stages, AgentRun tracking
│   │   ├── intake_agent.py               # Stage 1: validates deal, records MissingDocument
│   │   ├── contract_agent.py             # Stage 3: extracts ClauseFinding via grounded LLM
│   │   ├── corporate_agent.py            # Stage 4: corporate governance analysis
│   │   ├── red_flag_aggregator.py        # Stage 5: produces RedFlag + OpenQuestion
│   │   ├── report_agent.py               # Stage 6: Markdown report → Report row
│   │   ├── deal_qa_agent.py              # RAG Q&A over deal documents
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
├── tests/                                # 573 passing
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
| POST | `/auth/login` | Login (form) → Token |
| GET/POST/PATCH/DELETE | `/workspaces/...` | Workspace CRUD (last workspace and non-empty workspaces protected from deletion) |
| GET/POST | `/deals/?workspace_id=N` | List / create deals in workspace |
| GET/PATCH/DELETE | `/deals/{deal_id}` | Deal CRUD |
| POST | `/deals/{deal_id}/analyze` | **202** → queues multi-agent pipeline in BackgroundTask |
| GET | `/deals/{deal_id}/agent-runs` | List AgentRun rows in pipeline order |
| GET | `/deals/{deal_id}/analysis-stream` | SSE stream of pipeline progress |
| POST | `/deals/{deal_id}/report` | Generate Markdown due-diligence report |
| GET | `/deals/{deal_id}/report` | Get current report |
| GET | `/deals/{deal_id}/report/export?format=pdf\|docx` | Branded export |
| POST | `/deals/{deal_id}/ask` | RAG Q&A with citations |
| GET | `/deals/{deal_id}/clause-findings` | List clauses |
| GET | `/deals/{deal_id}/red-flags` | List red flags |
| GET | `/deals/{deal_id}/risk-score` | Computed risk score |
| POST | `/documents/upload?deal_id=N` | **201** → file saved, ingestion runs in BackgroundTask |
| POST | `/documents/upload-batch?deal_id=N` | Multi-file upload |
| GET | `/documents/deals/{deal_id}/documents` | List deal's documents |
| DELETE | `/documents/{document_id}` | Delete document |

## Analysis Pipeline (`packages/agents/orchestrator.run_deal_analysis_pipeline`)
Triggered async by `POST /deals/{id}/analyze`. Each stage gets its own `AgentRun`; a failing stage marks itself failed but does not abort the pipeline. All stages are idempotent.

1. **Intake** — validate deal, set status → `analyzing`, inventory documents, record `MissingDocument` for absent standard categories (contract / financial / legal / insurance).
2. **Document routing** — classify each processed document → `AgentFinding`.
3. **Contract analysis** (`ContractAgent`) — extract clauses → `ClauseFinding` (with grounding check + min confidence).
4. **Corporate governance** (`CorporateAgent`) — bylaws / shareholder agreement insights.
5. **Red-flag aggregation** — produce `RedFlag` rows + `OpenQuestion` items.
6. **Report generation** (`report_agent.generate_due_diligence_report`) — Markdown stored in `Report` table.

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
python -m pytest ../../tests -q   # 573 passed
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

## Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/diligenx` | Database connection |
| `SECRET_KEY` | `change-me-in-production` | JWT signing key |
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
