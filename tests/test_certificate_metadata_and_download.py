import uuid

from app.config import get_settings

EXPECTED_DETAIL_KEYS = {
    "certificate_id",
    "job_id",
    "recipient_name",
    "email",
    "status",
    "error_code",
    "file_size_bytes",
    "created_at",
    "generated_at",
    "download_url",
}


def _create_and_get_certificate_id(client, recipients) -> str:
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(1)}).json()[
        "job_id"
    ]
    listing = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    return listing["items"][0]["certificate_id"]


def test_certificate_metadata_shape(client, recipients):
    certificate_id = _create_and_get_certificate_id(client, recipients)

    response = client.get(f"/api/v1/certificates/{certificate_id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == EXPECTED_DETAIL_KEYS
    assert body["certificate_id"] == certificate_id
    assert body["status"] == "succeeded"
    assert body["recipient_name"] == "Recipient 1"
    assert body["email"] == "recipient1@example.com"
    assert body["file_size_bytes"] > 0
    assert body["download_url"] == f"/api/v1/certificates/{certificate_id}/download"
    # no internal filesystem paths
    assert "file_path" not in body
    assert "path" not in body


def test_certificate_metadata_unknown_id_returns_404(client):
    response = client.get(f"/api/v1/certificates/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Certificate not found"}


def test_download_returns_valid_pdf(client, recipients):
    certificate_id = _create_and_get_certificate_id(client, recipients)

    response = client.get(f"/api/v1/certificates/{certificate_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")
    assert response.content.rstrip().endswith(b"%%EOF")


def test_download_unknown_certificate_returns_404(client):
    response = client.get(f"/api/v1/certificates/{uuid.uuid4()}/download")

    assert response.status_code == 404


def test_download_before_generation_returns_409(client, no_background, recipients):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(1)}).json()[
        "job_id"
    ]
    listing = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    certificate_id = listing["items"][0]["certificate_id"]

    response = client.get(f"/api/v1/certificates/{certificate_id}/download")

    assert response.status_code == 409
    assert response.json() == {"detail": "Certificate is not ready for download"}


def test_api_responses_never_leak_internal_paths(client, recipients):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(2)}).json()[
        "job_id"
    ]
    listing = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    certificate_id = listing["items"][0]["certificate_id"]

    responses = [
        client.get(f"/api/v1/jobs/{job_id}"),
        client.get(f"/api/v1/jobs/{job_id}/certificates"),
        client.get(f"/api/v1/certificates/{certificate_id}"),
    ]
    storage_dir = get_settings().storage_dir

    for response in responses:
        assert "Traceback" not in response.text
        assert "file_path" not in response.text
        assert storage_dir not in response.text
