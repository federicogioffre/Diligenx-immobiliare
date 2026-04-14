# Migrations

Uses **Alembic** for database migrations.

## Setup

```bash
cd apps/api
alembic init infra/migrations
# Edit alembic.ini → sqlalchemy.url = sqlite:///./diligenx.db
```

## Commands

```bash
# Generate a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```
