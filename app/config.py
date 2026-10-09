from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://certgen:certgen@localhost:5432/certgen"
    max_batch_size: int = 100
    storage_dir: str = "storage/certificates"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
