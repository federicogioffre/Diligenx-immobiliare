---
name: verify
description: Build/launch/drive recipe for verifying Diligenx changes end-to-end (FastAPI backend + Next.js frontend).
---

# Verifying Diligenx changes

## Backend (FastAPI) — isolated instance over real HTTP

```bash
S=$(mktemp -d)
export DATABASE_URL="sqlite:///$S/verify.db" AUTH_COOKIE_SECURE=false
cd apps/api
# Create tables (no alembic needed on SQLite):
python -c "from app.db.session import Base, engine; import app.models; Base.metadata.create_all(engine); print('ok')"
nohup python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 > $S/uvicorn.log 2>&1 &
until curl -s http://127.0.0.1:8765/health >/dev/null; do sleep 0.5; done
```

Gotchas:
- `AUTH_COOKIE_SECURE=false` is required over plain http or curl's cookie
  jar won't send the session cookie back.
- SQLite `DATABASE_URL` also exempts the app from the production
  `SECRET_KEY` startup guard in `app/main.py`.
- Missing native deps (ocr, pdf) only matter for ingestion of scanned PDFs;
  auth/deals/SSE flows work without them.

## Driving the auth + SSE flow (curl)

```bash
B=http://127.0.0.1:8765; JAR=$S/cookies.txt
curl -s -X POST $B/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"v@t.it","password":"verifypass123"}'
curl -s -D - -c $JAR -X POST $B/auth/login -d 'username=v@t.it&password=verifypass123'
# → expect Set-Cookie: dm_token (HttpOnly) + dm_authed, Cache-Control: no-store
curl -s -b $JAR $B/workspaces/            # cookie-only auth
TICKET=$(curl -s -b $JAR -X POST $B/deals/1/stream-ticket | jq -r .ticket)
curl -s --max-time 5 "$B/deals/1/analysis-stream?ticket=$TICKET"
# → a draft deal emits ONE data: frame and closes (no infinite stream)
curl -s -b $JAR -c $JAR -X POST $B/auth/logout   # then /workspaces → 401
```

Adversarial probes that must all return 401: stream ticket as Bearer or as
`dm_token` cookie on a normal endpoint; session JWT as `?ticket=`; ticket
minted for another deal_id; garbage ticket.

## Frontend (Next.js)

- `cd apps/web && pnpm install --frozen-lockfile && pnpm build` — build doubles
  as the typecheck; `output: standalone` must produce `.next/standalone/server.js`.
- Full UI flow: `pnpm dev` (proxies `/api` → `NEXT_PUBLIC_API_URL`, default
  `http://localhost:8000`) + backend with `AUTH_COOKIE_SECURE=false`.
- Playwright smoke: `pnpm test:e2e` (needs both servers running).

## Tests

`cd apps/api && python -m pytest ../../tests -q` — SQLite + Fake providers,
no services needed. Full suite ~4 min.
