import pytest

from app.services import pdf_service

INTERNAL_ERROR_MARKER = "SECRET_INTERNAL_DETAIL_98765"


@pytest.fixture
def one_failing_recipient(monkeypatch):
    """Make the middle recipient fail PDF generation; the rest succeed."""
    original = pdf_service.render_certificate

    def flaky(**kwargs):
        if kwargs["recipient_name"] == "Recipient 2":
            raise RuntimeError(INTERNAL_ERROR_MARKER)
        return original(**kwargs)

    monkeypatch.setattr(pdf_service, "render_certificate", flaky)


def test_one_failure_does_not_stop_other_recipients(client, recipients, one_failing_recipient):
    payload = {"recipients": recipients(3)}
    create = client.post("/api/v1/jobs", json=payload)
    assert create.status_code == 202
    job_id = create.json()["job_id"]

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["status"] == "completed_with_errors"
    assert status["total_count"] == 3
    assert status["processed_count"] == 3
    assert status["succeeded_count"] == 2
    assert status["failed_count"] == 1
    assert status["progress"] == 1.0
    assert status["finished_at"] is not None

    listing = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    by_name = {item["recipient_name"]: item for item in listing["items"]}

    assert by_name["Recipient 1"]["status"] == "succeeded"
    assert by_name["Recipient 3"]["status"] == "succeeded"
    assert by_name["Recipient 1"]["error_code"] is None
    assert by_name["Recipient 1"]["generated_at"] is not None

    failed = by_name["Recipient 2"]
    assert failed["status"] == "failed"
    assert failed["error_code"] == "GENERATION_FAILED"
    assert failed["generated_at"] is None


def test_failed_certificate_exposes_no_internal_details(client, recipients, one_failing_recipient):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(3)}).json()[
        "job_id"
    ]
    listing = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    failed = next(i for i in listing["items"] if i["status"] == "failed")

    detail = client.get(f"/api/v1/certificates/{failed['certificate_id']}")

    assert detail.status_code == 200
    assert INTERNAL_ERROR_MARKER not in detail.text
    assert "RuntimeError" not in detail.text
    assert "Traceback" not in detail.text
    assert "file_path" not in detail.text
    assert detail.json()["error_code"] == "GENERATION_FAILED"


def test_failed_certificate_is_not_downloadable(client, recipients, one_failing_recipient):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(3)}).json()[
        "job_id"
    ]
    listing = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    failed = next(i for i in listing["items"] if i["status"] == "failed")

    response = client.get(f"/api/v1/certificates/{failed['certificate_id']}/download")

    assert response.status_code == 409
    assert response.json() == {"detail": "Certificate is not ready for download"}


def test_successful_certificates_still_download_after_failure(client, recipients, one_failing_recipient):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(3)}).json()[
        "job_id"
    ]
    listing = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    succeeded = [i for i in listing["items"] if i["status"] == "succeeded"]

    assert len(succeeded) == 2
    for item in succeeded:
        response = client.get(
            f"/api/v1/certificates/{item['certificate_id']}/download"
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")
