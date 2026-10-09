from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PSYCOPG_URL_PREFIX = "postgresql+psycopg://"


def normalize_database_url(url: str) -> str:
    """Normalize a PostgreSQL URL to SQLAlchemy's psycopg driver format.

    Accepts ``postgres://``, ``postgresql://`` and ``postgresql+psycopg://``
    schemes (as handed out by providers such as Neon) and rewrites the first
    two to ``postgresql+psycopg://``. Everything after the scheme — including
    credentials, host, database, and query parameters such as
    ``sslmode=require`` — is preserved untouched. Idempotent.
    """
    normalized = url.strip()
    if normalized.startswith("postgres://"):
        normalized = PSYCOPG_URL_PREFIX + normalized[len("postgres://") :]
    elif normalized.startswith("postgresql://"):
        normalized = PSYCOPG_URL_PREFIX + normalized[len("postgresql://") :]
    return normalized


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = f"{PSYCOPG_URL_PREFIX}certgen:certgen@localhost:5432/certgen"
    max_batch_size: int = 100
    storage_dir: str = "storage/certificates"
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _apply_database_url_normalization(cls, value: str) -> str:
        # Runs for both environment-provided and explicitly passed values, so
        # the application engine and Alembic (which read get_settings()) always
        # share the same normalized connection string.
        return normalize_database_url(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()
