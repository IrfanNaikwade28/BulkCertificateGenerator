import uuid
from datetime import datetime

from sqlalchemy import select

from app.db import get_session_factory
from app.models import Certificate, CertificateStatus, Job, JobStatus


def test_create_job_returns_202_with_job_id(client, no_background, recipients):
    payload = {"recipients": recipients(3)}

    response = client.post("/api/v1/jobs", json=payload)

    assert response.status_code == 202
    body = response.json()
    uuid.UUID(body["job_id"])  # must be a UUID
    assert body["status"] == "pending"
    assert body["total_count"] == 3


def test_create_job_persists_job_and_certificate_rows(client, no_background, recipients):
    response = client.post("/api/v1/jobs", json={"recipients": recipients(3)})
    job_id = response.json()["job_id"]

    session = get_session_factory()()
    try:
        job = session.get(Job, uuid.UUID(job_id))
        assert job is not None
        assert job.status == JobStatus.PENDING
        assert job.total_count == 3
        assert job.processed_count == 0
        assert job.succeeded_count == 0
        assert job.failed_count == 0
        assert job.started_at is None
        assert job.finished_at is None

        certificates = session.scalars(
            select(Certificate).where(Certificate.job_id == job.id)
        ).all()
        assert len(certificates) == 3
        assert all(c.status == CertificateStatus.PENDING for c in certificates)
        assert {c.recipient_name for c in certificates} == {
            "Recipient 1",
            "Recipient 2",
            "Recipient 3",
        }
        # emails are normalised to lowercase
        assert all(c.email == c.email.lower() for c in certificates)
    finally:
        session.close()


def test_background_processing_completes_job(client, recipients):
    response = client.post("/api/v1/jobs", json={"recipients": recipients(3)})
    job_id = response.json()["job_id"]

    status = client.get(f"/api/v1/jobs/{job_id}").json()

    assert status["status"] == "completed"
    assert status["total_count"] == 3
    assert status["processed_count"] == 3
    assert status["succeeded_count"] == 3
    assert status["failed_count"] == 0
    assert status["progress"] == 1.0

    created_at = datetime.fromisoformat(status["created_at"])
    started_at = datetime.fromisoformat(status["started_at"])
    finished_at = datetime.fromisoformat(status["finished_at"])
    assert created_at <= started_at <= finished_at


def test_unknown_job_id_returns_404(client):
    response = client.get(f"/api/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}


def test_malformed_job_id_returns_422(client):
    response = client.get("/api/v1/jobs/not-a-uuid")

    assert response.status_code == 422
