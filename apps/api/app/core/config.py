from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_NAME: str = "DealMind AI"
    DEBUG: bool = False

    # Database — default to PostgreSQL
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/dealmind"

    # Auth
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # File uploads
    UPLOAD_DIR: str = str(Path("uploads").resolve())
    MAX_UPLOAD_SIZE_MB: int = 50

    # Embeddings
    OPENAI_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536


settings = Settings()
