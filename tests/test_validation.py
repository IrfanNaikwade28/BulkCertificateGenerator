import pytest
from sqlalchemy import func, select

from app.db import get_session_factory
from app.models import Job


def _job_count() -> int:
    session = get_session_factory()()
    try:
        return session.scalar(select(func.count()).select_from(Job)) or 0
    finally:
        session.close()


def test_empty_recipients_rejected(client):
    response = client.post("/api/v1/jobs", json={"recipients": []})

    assert response.status_code == 422
    assert _job_count() == 0


def test_missing_recipients_field_rejected(client):
    response = client.post("/api/v1/jobs", json={})

    assert response.status_code == 422
    assert _job_count() == 0


def test_batch_above_maximum_rejected(client, recipients, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_batch_size", 5)
    response = client.post("/api/v1/jobs", json={"recipients": recipients(6)})

    assert response.status_code == 422
    assert "maximum" in response.text.lower()
    assert _job_count() == 0


def test_batch_at_maximum_accepted(client, no_background, recipients, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_batch_size", 5)
    response = client.post("/api/v1/jobs", json={"recipients": recipients(5)})

    assert response.status_code == 202
    assert response.json()["total_count"] == 5


def test_duplicate_emails_rejected(client, recipients):
    payload = {
        "recipients": [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Alicia", "email": "ALICE@example.com"},
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)

    assert response.status_code == 422
    assert "duplicate" in response.text.lower()
    assert _job_count() == 0


def test_invalid_email_rejected(client):
    response = client.post(
        "/api/v1/jobs",
        json={"recipients": [{"name": "Alice", "email": "not-an-email"}]},
    )

    assert response.status_code == 422
    assert _job_count() == 0


def test_missing_email_rejected(client):
    response = client.post(
        "/api/v1/jobs", json={"recipients": [{"name": "Alice"}]}
    )

    assert response.status_code == 422
    assert _job_count() == 0


def test_blank_name_rejected(client):
    response = client.post(
        "/api/v1/jobs",
        json={"recipients": [{"name": "   ", "email": "alice@example.com"}]},
    )

    assert response.status_code == 422
    assert _job_count() == 0


def test_overlong_name_rejected(client):
    response = client.post(
        "/api/v1/jobs",
        json={"recipients": [{"name": "x" * 101, "email": "alice@example.com"}]},
    )

    assert response.status_code == 422
    assert _job_count() == 0


def test_recipients_wrong_type_rejected(client):
    response = client.post("/api/v1/jobs", json={"recipients": "alice"})

    assert response.status_code == 422
    assert _job_count() == 0


def test_single_recipient_accepted(client, no_background):
    response = client.post(
        "/api/v1/jobs",
        json={"recipients": [{"name": "Solo", "email": "solo@example.com"}]},
    )

    assert response.status_code == 202
    assert response.json()["total_count"] == 1


@pytest.mark.parametrize("title", ["", "   ", "x" * 101])
def test_invalid_certificate_title_rejected(client, recipients, title):
    response = client.post(
        "/api/v1/jobs",
        json={"recipients": recipients(1), "certificate_title": title},
    )

    assert response.status_code == 422
    assert _job_count() == 0


@pytest.mark.parametrize("event_name", ["", "   ", "x" * 151])
def test_invalid_event_name_rejected(client, recipients, event_name):
    response = client.post(
        "/api/v1/jobs",
        json={"recipients": recipients(1), "event_name": event_name},
    )

    assert response.status_code == 422
    assert _job_count() == 0


def test_title_and_event_name_are_trimmed_and_persisted(
    client, no_background, recipients
):
    response = client.post(
        "/api/v1/jobs",
        json={
            "recipients": recipients(1),
            "certificate_title": "  My Custom Title  ",
            "event_name": "  My Event  ",
        },
    )

    assert response.status_code == 202

    session = get_session_factory()()
    try:
        job = session.scalar(select(Job))
        assert job.certificate_title == "My Custom Title"
        assert job.event_name == "My Event"
    finally:
        session.close()
