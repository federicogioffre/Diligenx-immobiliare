# Diligenx

AI-powered deal intelligence platform. Analyze, score, and track deals using OpenAI GPT-5.6 Luna.

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + SQLAlchemy + Pydantic v2 |
| Frontend | Next.js 15 (App Router) |
| AI | OpenAI GPT-5.6 Luna (gpt-5.6-luna) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Containers | Docker + docker-compose |

## Quick Start

### Backend

```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate  # or .venv/Scripts/activate on Windows
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

API docs at http://localhost:8000/docs

### Frontend

```bash
cd apps/web
npm install
npm run dev
```

App at http://localhost:3000

### Docker

```bash
cp apps/api/.env.example .env
docker-compose up --build
```

## Analysis model

The default model is `gpt-5.6-luna`, used for every analysis stage, source review,
report generation and document Q&A. OpenAI Responses calls use `reasoning.effort=none`
so existing limits remain answer budgets, `store=false`, and no automatic input
truncation. Structured results use one forced function call; source reviews also
enforce their strict schema. Refusals and incomplete results fail before publication.
Token usage (including cached input and reasoning) is recorded in `llm_usage` logs.

Set `OPENAI_API_KEY` on both API and worker. Existing `ANALYSIS_MODEL` overrides
take precedence and must be updated on both services. An explicitly configured
`claude-*` model still uses Anthropic and requires `ANTHROPIC_API_KEY`; a missing
selected-provider key never triggers a switch to the other provider. Development
without either key may use deterministic test data; beta deployments cannot.
Embeddings continue using `text-embedding-3-small` and their existing dimensions.

## Project Structure

```
apps/api/       → FastAPI backend
apps/web/       → Next.js frontend
packages/
  agents/       → AI agent logic (DealAnalysisAgent)
  schemas/      → Shared Pydantic models
  prompts/      → Prompt templates
  parsing/      → Document parsers (PDF, text)
  retrieval/    → Vector search abstraction
infra/          → Docker configs, DB migrations
tests/          → pytest test suite
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key for analysis and embeddings |
| `ANTHROPIC_API_KEY` | Optional key for explicitly selected Claude models |
| `ANALYSIS_MODEL` | Analysis and Q&A model, default `gpt-5.6-luna` |
| `SECRET_KEY` | JWT signing key |
| `DATABASE_URL` | DB connection string |
| `ALLOWED_ORIGINS` | CORS origins (JSON array) |
