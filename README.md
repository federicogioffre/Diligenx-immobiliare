# DealMind AI

AI-powered deal intelligence platform. Analyze, score, and track deals using Claude AI.

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + SQLAlchemy + Pydantic v2 |
| Frontend | Next.js 15 (App Router) |
| AI | Anthropic Claude (claude-sonnet-4-6) |
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
| `ANTHROPIC_API_KEY` | Claude API key |
| `SECRET_KEY` | JWT signing key |
| `DATABASE_URL` | DB connection string |
| `ALLOWED_ORIGINS` | CORS origins (JSON array) |
