# DealMind AI — Project Context

## Stack
- **Backend:** FastAPI + SQLAlchemy 2.0 (mapped_column style) + Pydantic v2
- **Database:** PostgreSQL (default) + pgvector extension; SQLite for tests
- **Auth:** JWT Bearer → `python-jose` + `bcrypt` (no passlib)
- **Migrations:** Alembic (`apps/api/alembic/`)
- **Embeddings:** OpenAI `text-embedding-3-small` (1536 dims); `FakeEmbeddingProvider` for tests
- **Env:** `.env` via `pydantic-settings`
- **Frontend:** Next.js 15 (App Router, TypeScript) — scaffold only, not yet functional
- **Tests:** pytest + FastAPI TestClient (SQLite), **62 passing, 4 skipped** (PDF tests need reportlab)

## Project Root
```
C:/Dealmind/
```

## Structure

```
C:/Dealmind/
├── apps/api/                             # FastAPI backend
│   ├── app/
│   │   ├── main.py                       # App entry, CORS, routers (health, auth, deals, documents)
│   │   ├── core/
│   │   │   ├── config.py                 # Settings: DATABASE_URL, SECRET_KEY, UPLOAD_DIR, OPENAI_API_KEY, EMBEDDING_*
│   │   │   └── security.py              # bcrypt hashing, JWT create/decode
│   │   ├── db/session.py                 # engine, SessionLocal, Base, get_db(); pool_pre_ping=True
│   │   ├── models/
│   │   │   ├── base.py                   # TimestampMixin (created_at, updated_at)
│   │   │   ├── user.py                   # User → owns Workspaces
│   │   │   ├── workspace.py              # Workspace → owner_id FK to User
│   │   │   ├── deal.py                   # Deal + DealStatus(draft|analyzing|reviewed|closed) → workspace_id FK
│   │   │   ├── document.py               # Document + DocumentStatus(pending|processing|processed|failed) + language col
│   │   │   ├── document_chunk.py         # DocumentChunk + VectorType (pgvector on PG, JSON on SQLite) + EMBEDDING_DIM=1536
│   │   │   ├── clause_finding.py         # ClauseFinding + ClauseType enum (10 types)
│   │   │   ├── red_flag.py               # RedFlag + Severity(low|medium|high|critical)
│   │   │   ├── report.py                 # Report + ReportType + ReportStatus enums
│   │   │   └── __init__.py               # Re-exports all models
│   │   ├── schemas/                      # Pydantic v2 (from_attributes=True)
│   │   │   ├── user.py                   # UserCreate, UserRead, Token
│   │   │   ├── workspace.py              # WorkspaceCreate, WorkspaceRead
│   │   │   ├── deal.py                   # DealCreate, DealRead
│   │   │   ├── document.py               # DocumentRead (includes language), DocumentUploadResponse
│   │   │   ├── clause_finding.py         # ClauseFindingRead
│   │   │   ├── red_flag.py               # RedFlagRead
│   │   │   └── report.py                 # ReportRead
│   │   ├── services/auth.py              # get_current_user() — HTTPBearer dependency
│   │   └── api/routes/
│   │       ├── health.py                 # GET /health
│   │       ├── auth.py                   # POST /auth/register, /auth/login
│   │       ├── deals.py                  # GET|POST /deals/ (requires workspace_id query param)
│   │       └── documents.py              # POST /documents/upload, GET /documents/deals/{id}/documents
│   ├── alembic/
│   │   ├── env.py                        # Reads DATABASE_URL from settings, imports all models
│   │   ├── script.py.mako
│   │   └── versions/001_initial_schema.py  # All 8 tables
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── pyproject.toml                    # pytest config: testpaths, pythonpath
│   ├── Dockerfile
│   └── .env.example
│
├── apps/web/                             # Next.js 15 frontend (scaffold only)
│   ├── src/app/{layout,page}.tsx
│   ├── src/lib/api.ts                    # Typed API client
│   ├── package.json, next.config.ts, Dockerfile
│
├── packages/
│   ├── agents/                           # AI agents (scaffold — not yet integrated)
│   │   ├── base.py                       # BaseAgent ABC
│   │   └── deal_agent.py                 # DealAnalysisAgent (uses anthropic SDK)
│   ├── schemas/                          # Shared Pydantic schemas
│   │   └── deal.py                       # DealPayload, DealAnalysisResult
│   ├── prompts/
│   │   └── deal_prompts.py               # DEAL_ANALYSIS_PROMPT, DEAL_SCORING_PROMPT
│   ├── parsing/                          # ★ Document ingestion pipeline
│   │   ├── pdf_parser.py                 # extract_pdf() → list[PageText] (per-page), pdf_page_count()
│   │   ├── docx_parser.py                # extract_docx() → list[PageText]
│   │   ├── text_parser.py                # extract_txt() → list[PageText]
│   │   ├── language.py                   # detect_language(text) → 'it' | 'en' (word-frequency heuristic)
│   │   ├── chunker.py                    # chunk_pages() → list[Chunk]; 1000 chars, 200 overlap, sentence-aware
│   │   ├── ingestion_pipeline.py         # ★ process_document(doc_id, db): extract → detect lang → chunk → embed → store
│   │   └── __init__.py
│   └── retrieval/                        # ★ Embedding / vector search
│       ├── embedding_service.py          # ★ EmbeddingProvider ABC, OpenAIEmbeddingProvider, FakeEmbeddingProvider
│       │                                 #   generate_embeddings_for_document(doc_id, db, provider?)
│       │                                 #   get/set_embedding_provider() — singleton with auto-detection
│       ├── vector_store.py               # VectorStore placeholder (in-memory)
│       └── __init__.py
│
├── infra/
│   ├── docker/
│   └── migrations/README.md              # Alembic usage notes
│
├── tests/                                # 62 passing, 4 skipped
│   ├── conftest.py                       # SQLite test DB, FakeEmbeddingProvider auto-set, fixtures:
│   │                                     #   db, client, test_user, auth_headers, test_workspace, test_deal
│   ├── test_health.py                    # 1 test
│   ├── test_auth.py                      # 4 tests (register, dup, login, bad pwd)
│   ├── test_deals.py                     # 6 tests (CRUD, auth, workspace scoping)
│   ├── test_documents.py                 # 5 tests (upload, type validation, listing)
│   ├── test_models.py                    # 11 tests (all models, relationships, cascade delete)
│   ├── test_ingestion.py                 # 20 tests (extractors, language, chunker, pipeline, upload integration)
│   └── test_embeddings.py               # 15 tests (FakeProvider, generate_embeddings, pipeline integration, idempotency)
│
├── docker-compose.yml
├── .gitignore
├── README.md
└── CLAUDE.md                             # ← this file
```

## Data Model

```
User 1──* Workspace 1──* Deal 1──* Document 1──* DocumentChunk (has embedding VECTOR(1536))
                              │           └──* ClauseFinding
                              ├──* RedFlag (optional source_document_id → Document)
                              └──* Report
```

## API Endpoints (all 🔒 except auth & health)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/auth/register` | Register → UserRead |
| POST | `/auth/login` | Login (form) → Token |
| GET | `/deals/?workspace_id=N` | List deals in workspace |
| POST | `/deals/?workspace_id=N` | Create deal |
| GET | `/deals/{deal_id}` | Get deal |
| POST | `/documents/upload?deal_id=N` | Upload file → auto-ingestion + embedding |
| GET | `/documents/deals/{deal_id}/documents` | List deal's documents |

## Ingestion Pipeline (what happens on upload)
```
Upload file → save to disk → create Document(status=pending)
  → process_document(doc_id, db):
      1. status → processing
      2. Extract text per-page (PDF/DOCX/TXT)
      3. Detect language (IT or EN)
      4. Chunk text (1000 chars, 200 overlap, sentence boundaries)
      5. Store chunks in DocumentChunk table
      6. generate_embeddings_for_document() → embed all chunks via OpenAI (or Fake for tests)
      7. status → processed
      (on error: status → failed)
```

## Running (dev)

```bash
cd C:/Dealmind/apps/api
pip install -r requirements.txt
cp .env.example .env          # set DATABASE_URL, SECRET_KEY, OPENAI_API_KEY
alembic upgrade head          # apply migrations (needs PostgreSQL + pgvector extension)
uvicorn app.main:app --reload # http://localhost:8000/docs
```

## Running Tests

```bash
cd C:/Dealmind/apps/api
python -m pytest ../../tests -v   # 62 passed, 4 skipped (SQLite, FakeEmbeddings)
```

## Key Design Decisions
- **PostgreSQL + pgvector** for production embeddings; **SQLite + JSON** fallback in tests via custom `VectorType` TypeDecorator
- **bcrypt** used directly (not passlib) — compatible with Python 3.14
- `DocumentChunk.embedding` column: `VECTOR(1536)` on PG, `TEXT` (JSON-serialized list) on SQLite
- `EmbeddingProvider` is pluggable: `set_embedding_provider()` in tests injects `FakeEmbeddingProvider`
- Ingestion pipeline is **idempotent** — re-running deletes old chunks and re-embeds
- No AI agents wired yet — `packages/agents/` and `packages/prompts/` are scaffolded but not connected to routes
- MIME types allowed: `application/pdf`, `text/plain`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`

## Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/dealmind` | Database connection |
| `SECRET_KEY` | `change-me-in-production` | JWT signing key |
| `ALLOWED_ORIGINS` | `["http://localhost:3000"]` | CORS origins |
| `UPLOAD_DIR` | `uploads` | File upload directory |
| `MAX_UPLOAD_SIZE_MB` | `50` | Max upload size |
| `OPENAI_API_KEY` | _(empty)_ | For real embeddings; omit for FakeProvider |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI model name |
| `EMBEDDING_DIMENSION` | `1536` | Vector dimension |
