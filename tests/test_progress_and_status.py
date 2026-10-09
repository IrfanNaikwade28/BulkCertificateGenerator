import uuid
from datetime import datetime, timezone

from app.db import get_session_factory
from app.models import Certificate, CertificateStatus, Job, JobStatus


def test_progress_is_zero_while_pending(client, no_background, recipients):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(4)}).json()[
        "job_id"
    ]

    status = client.get(f"/api/v1/jobs/{job_id}").json()

    assert status["status"] == "pending"
    assert status["progress"] == 0.0
    assert status["processed_count"] == 0
    assert status["started_at"] is None
    assert status["finished_at"] is None


def test_partial_progress_is_reported(client, no_background, recipients):
    """A job in flight reports processed/total as its progress fraction."""
    payload = {"recipients": recipients(3)}
    job_id = client.post("/api/v1/jobs", json=payload).json()["job_id"]

    session = get_session_factory()()
    try:
        job = session.get(Job, uuid.UUID(job_id))
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now(timezone.utc)
        job.processed_count = 1
        job.succeeded_count = 1
        session.commit()
    finally:
        session.close()

    status = client.get(f"/api/v1/jobs/{job_id}").json()

    assert status["status"] == "processing"
    assert status["total_count"] == 3
    assert status["processed_count"] == 1
    assert status["succeeded_count"] == 1
    assert status["failed_count"] == 0
    assert status["progress"] == 1 / 3
    assert status["finished_at"] is None


def test_completed_job_progress_is_one(client, recipients):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(2)}).json()[
        "job_id"
    ]

    status = client.get(f"/api/v1/jobs/{job_id}").json()

    assert status["status"] == "completed"
    assert status["progress"] == 1.0
    assert status["processed_count"] == status["total_count"]
    assert status["finished_at"] is not None


def test_completed_with_errors_counts(client, recipients, monkeypatch):
    from app.services import pdf_service

    original = pdf_service.render_certificate

    def fail_one(**kwargs):
        if kwargs["recipient_name"] == "Recipient 2":
            raise RuntimeError("boom")
        return original(**kwargs)

    monkeypatch.setattr(pdf_service, "render_certificate", fail_one)
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(3)}).json()[
        "job_id"
    ]

    status = client.get(f"/api/v1/jobs/{job_id}").json()

    assert status["status"] == "completed_with_errors"
    assert status["processed_count"] == 3
    assert status["succeeded_count"] == 2
    assert status["failed_count"] == 1
    assert status["progress"] == 1.0


def test_certificate_timestamps_after_processing(client, recipients):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(2)}).json()[
        "job_id"
    ]

    listing = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    assert listing["total"] == 2
    for item in listing["items"]:
        assert item["generated_at"] is not None
        assert item["status"] == "succeeded"
