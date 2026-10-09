"""Shared test fixtures.

Environment variables are set before any application import so that settings,
the engine, and Alembic all point at the dedicated test database and a
temporary certificate storage directory.
"""

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

_TEST_ROOT = tempfile.mkdtemp(prefix="certgen-tests-")
os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://certgen:certgen@localhost:5432/certgen_test"
)
os.environ["STORAGE_DIR"] = str(Path(_TEST_ROOT) / "certificates")
os.environ["LOG_LEVEL"] = "WARNING"

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import get_session_factory
from app.main import app
from app.models import Certificate, Job

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def database_schema() -> None:
    """Apply Alembic migrations once per test session (also exercises migrations)."""
    config = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    alembic_command.upgrade(config, "head")


@pytest.fixture(autouse=True)
def clean_tables() -> None:
    def _clean() -> None:
        session = get_session_factory()()
        try:
            session.execute(delete(Certificate))
            session.execute(delete(Job))
            session.commit()
        finally:
            session.close()

    _clean()
    yield
    _clean()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def no_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable background processing so records stay in their initial state."""
    monkeypatch.setattr("app.workers.job_processor.process_job", lambda job_id: None)


@pytest.fixture
def recipients() -> Callable[..., list[dict[str, str]]]:
    """Factory for valid recipient payloads."""

    def _make(count: int, *, names: list[str] | None = None) -> list[dict[str, str]]:
        if names is not None:
            assert len(names) == count
        return [
            {
                "name": names[i] if names else f"Recipient {i + 1}",
                "email": f"recipient{i + 1}@example.com",
            }
            for i in range(count)
        ]

    return _make
