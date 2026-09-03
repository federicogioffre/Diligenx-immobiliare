from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file so it works regardless of the
# working directory from which uvicorn is launched.
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    # App
    APP_NAME: str = "Diligenx"
    DEBUG: bool = False

    # Database — default to PostgreSQL
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/diligenx"

    # Auth
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h
    # Secure attribute on the auth cookies. Keep True everywhere except local
    # development over plain http (Safari refuses Secure cookies on
    # http://localhost, unlike Chrome/Firefox).
    AUTH_COOKIE_SECURE: bool = True

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # File uploads
    UPLOAD_DIR: str = str(Path("uploads").resolve())
    MAX_UPLOAD_SIZE_MB: int = 50

    # Cloud storage (S3 / Cloudflare R2)
    # Leave S3_BUCKET empty to use local disk (development default)
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str = ""        # R2: https://<account_id>.r2.cloudflarestorage.com
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_REGION: str = "auto"          # "auto" for R2, e.g. "eu-west-1" for AWS

    # Embeddings
    OPENAI_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536

    # AI Analysis
    ANTHROPIC_API_KEY: str = ""
    ANALYSIS_MODEL: str = "claude-sonnet-4-6"
    # Max concurrent LLM calls within a pipeline stage (per-document fan-out).
    # The analysis pipeline parallelises independent per-document calls with a
    # bounded thread pool of this size; 1 restores fully sequential behaviour.
    LLM_MAX_CONCURRENCY: int = 4

    # Durable job queue (Arq + Redis). Leave empty to use FastAPI
    # BackgroundTasks — the original in-process path. When set, /analyze
    # and /documents/upload enqueue jobs to Arq so they survive worker
    # restarts and can be retried independently. Format:
    #   redis://default:<password>@<host>:<port>
    #   rediss://...                          (TLS, recommended on Upstash)
    REDIS_URL: str = ""

    # Error monitoring (Sentry). Leave empty to run without Sentry — the
    # SDK is only initialised when a DSN is provided, so the dependency
    # is inert in local dev and tests. traces_sample_rate is kept low by
    # default: errors are always captured, performance traces are sampled.
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    SENTRY_ENVIRONMENT: str = "production"

    # Outbound email (SMTP). Leave SMTP_HOST empty to disable sending —
    # flows that email (password reset) then log the message instead, so
    # they stay testable without mailboxes. Hostinger Titan example:
    #   SMTP_HOST=smtp.titan.email  SMTP_PORT=465 (SSL)
    #   SMTP_USER=privacy@diligenx.it  SMTP_FROM=privacy@diligenx.it
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # Public URL of the frontend, used to build links in outbound email
    # (password reset). No trailing slash.
    FRONTEND_URL: str = "https://www.diligenx.it"


settings = Settings()
