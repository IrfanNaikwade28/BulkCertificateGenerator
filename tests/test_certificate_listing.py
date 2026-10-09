import uuid


def test_list_certificates_returns_all_results(client, recipients):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(3)}).json()[
        "job_id"
    ]

    response = client.get(f"/api/v1/jobs/{job_id}/certificates")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert len(body["items"]) == 3
    assert {item["status"] for item in body["items"]} == {"succeeded"}
    for item in body["items"]:
        uuid.UUID(item["certificate_id"])
        assert "file_path" not in item


def test_list_certificates_pagination(client, recipients):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(5)}).json()[
        "job_id"
    ]

    page1 = client.get(f"/api/v1/jobs/{job_id}/certificates?page=1&page_size=2").json()
    page2 = client.get(f"/api/v1/jobs/{job_id}/certificates?page=2&page_size=2").json()
    page3 = client.get(f"/api/v1/jobs/{job_id}/certificates?page=3&page_size=2").json()

    assert page1["total"] == 5
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert len(page3["items"]) == 1
    ids = {i["certificate_id"] for i in page1["items"] + page2["items"] + page3["items"]}
    assert len(ids) == 5


def test_list_certificates_status_filter(client, no_background, recipients):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(3)}).json()[
        "job_id"
    ]

    pending = client.get(
        f"/api/v1/jobs/{job_id}/certificates?status=pending"
    ).json()
    succeeded = client.get(
        f"/api/v1/jobs/{job_id}/certificates?status=succeeded"
    ).json()

    assert pending["total"] == 3
    assert succeeded["total"] == 0
    assert succeeded["items"] == []


def test_list_certificates_unknown_job_returns_404(client):
    response = client.get(f"/api/v1/jobs/{uuid.uuid4()}/certificates")

    assert response.status_code == 404


def test_list_certificates_invalid_pagination_returns_422(client, recipients):
    job_id = client.post("/api/v1/jobs", json={"recipients": recipients(1)}).json()[
        "job_id"
    ]

    assert client.get(f"/api/v1/jobs/{job_id}/certificates?page=0").status_code == 422
    assert client.get(f"/api/v1/jobs/{job_id}/certificates?page_size=0").status_code == 422
    assert (
        client.get(f"/api/v1/jobs/{job_id}/certificates?page_size=500").status_code
        == 422
    )
