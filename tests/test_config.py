"""Focused tests for database URL normalization and settings behaviour."""

from app.config import Settings, normalize_database_url

# Obviously fake Neon-style URL: no real host, credentials, or database.
NEON_STYLE_URL = (
    "postgres://dbuser:dbpass@ep-example.region.aws.neon.tech"
    "/validatedb?sslmode=require&channel_binding=require"
)


def test_postgres_scheme_is_normalized_to_psycopg():
    result = normalize_database_url("postgres://user:pass@localhost:5432/db")

    assert result == "postgresql+psycopg://user:pass@localhost:5432/db"


def test_postgresql_scheme_is_normalized_to_psycopg():
    result = normalize_database_url("postgresql://user:pass@localhost:5432/db")

    assert result == "postgresql+psycopg://user:pass@localhost:5432/db"


def test_neon_style_url_preserves_ssl_query_parameters():
    result = normalize_database_url(NEON_STYLE_URL)

    assert result.startswith("postgresql+psycopg://")
    assert "ep-example.region.aws.neon.tech/validatedb" in result
    assert result.endswith("?sslmode=require&channel_binding=require")


def test_already_normalized_url_is_untouched():
    url = "postgresql+psycopg://user:pass@localhost:5432/db?sslmode=require"

    assert normalize_database_url(url) == url


def test_normalization_is_idempotent():
    once = normalize_database_url(NEON_STYLE_URL)

    assert normalize_database_url(once) == once


def test_surrounding_whitespace_is_stripped():
    result = normalize_database_url(f"  {NEON_STYLE_URL}\n")

    assert result == normalize_database_url(NEON_STYLE_URL)
    assert not result.startswith(" ")


def test_settings_normalize_explicit_database_url():
    settings = Settings(database_url=NEON_STYLE_URL)

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in settings.database_url


def test_settings_default_uses_psycopg_driver():
    settings = Settings()

    assert settings.database_url.startswith("postgresql+psycopg://")


def test_other_postgres_drivers_are_left_alone():
    url = "postgresql+asyncpg://user:pass@localhost/db"

    assert normalize_database_url(url) == url
