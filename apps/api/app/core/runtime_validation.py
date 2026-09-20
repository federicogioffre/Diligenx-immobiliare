"""Fail closed when a deployment opts in to accepting external beta users."""
from app.core.config import settings


def validate_beta_configuration() -> None:
    if not settings.BETA_MODE:
        return
    from packages.llm_config import DEFAULT_ANALYSIS_MODEL, analysis_api_key_name
    key_name = analysis_api_key_name(settings.ANALYSIS_MODEL or DEFAULT_ANALYSIS_MODEL)
    required = {"REDIS_URL", "S3_BUCKET", "OPENAI_API_KEY", key_name}
    missing = [name for name in sorted(required) if not getattr(settings, name)]
    if missing:
        raise RuntimeError("BETA_MODE requires: " + ", ".join(missing))
    if not settings.DATABASE_URL.startswith("postgresql") or settings.DEBUG:
        raise RuntimeError("BETA_MODE requires PostgreSQL and DEBUG=false")
    if settings.SECRET_KEY == "change-me-in-production" or len(settings.SECRET_KEY) < 32:
        raise RuntimeError("BETA_MODE requires a strong SECRET_KEY (>=32 characters)")
    if not settings.AUTH_COOKIE_SECURE:
        raise RuntimeError("BETA_MODE requires secure auth cookies and HTTPS")
    if min(settings.WORKER_MAX_JOBS, settings.WORKER_JOB_TIMEOUT_SECONDS,
           settings.WORKER_MAX_TRIES, settings.LLM_MAX_CONCURRENCY, settings.LLM_MAX_IN_FLIGHT) < 1:
        raise RuntimeError("Worker and LLM concurrency/timeout/retry limits must be positive")


def validate_beta_database() -> None:
    if not settings.BETA_MODE:
        return
    from sqlalchemy import text
    from app.db.session import engine
    with engine.connect() as conn:
        role = conn.execute(text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )).one()
        if role.rolsuper or role.rolbypassrls:
            raise RuntimeError("BETA_MODE requires an application role without SUPERUSER or BYPASSRLS")
        protected = conn.execute(text("""
            SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname IN (
                'workspaces','deals','documents','document_chunks','clause_findings',
                'red_flags','reports','agent_runs','agent_findings','open_questions',
                'missing_documents','company_profiles')
              AND c.relrowsecurity AND c.relforcerowsecurity
        """)).scalar_one()
        if protected != 12:
            raise RuntimeError("BETA_MODE requires all tenant tables to have forced row-level security")
        from pathlib import Path
        from alembic.script import ScriptDirectory
        scripts = ScriptDirectory(str(Path(__file__).resolve().parents[2] / "alembic"))
        revisions = set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
        if revisions != set(scripts.get_heads()):
            raise RuntimeError("BETA_MODE requires all current database migrations")
