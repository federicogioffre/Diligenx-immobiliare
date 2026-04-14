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


settings = Settings()
