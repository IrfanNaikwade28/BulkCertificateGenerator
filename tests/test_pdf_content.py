"""Verify that generated PDFs reflect the job's submitted title and event name.

ReportLab encodes content streams as ASCII85 + Flate, so the tests decode them
(base64 + zlib from the standard library) before asserting on drawn text.
"""

import base64
import re
import uuid
import zlib

from app.db import get_session_factory
from app.models import Job


def _decode_stream(raw: bytes) -> bytes:
    data = raw.strip()
    if data.endswith(b"~>"):
        if data.startswith(b"<~"):
            data = data[2:]
        data = base64.a85decode(data[:-2], adobe=False)
    try:
        return zlib.decompress(data)
    except zlib.error:
        return data


def _pdf_text(data: bytes) -> str:
    parts: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        parts.append(_decode_stream(match.group(1)).decode("latin-1"))
    return "\n".join(parts)


def _create_job(client, recipients, **fields) -> str:
    payload = {"recipients": recipients(1), **fields}
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202
    return response.json()["job_id"]


def _download_first_certificate(client, job_id: str) -> bytes:
    listing = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    certificate_id = listing["items"][0]["certificate_id"]
    response = client.get(f"/api/v1/certificates/{certificate_id}/download")
    assert response.status_code == 200
    return response.content


def test_pdf_uses_supplied_certificate_title(client, recipients):
    job_id = _create_job(
        client,
        recipients,
        certificate_title="EXCELLENCE IN ROBOTICS",
        event_name="the Robotics Bootcamp 2026",
    )

    text = _pdf_text(_download_first_certificate(client, job_id))

    assert "EXCELLENCE IN ROBOTICS" in text
    assert "CERTIFICATE OF ACHIEVEMENT" not in text


def test_pdf_uses_supplied_event_name(client, recipients):
    job_id = _create_job(client, recipients, event_name="the Robotics Bootcamp 2026")

    text = _pdf_text(_download_first_certificate(client, job_id))

    assert "the Robotics Bootcamp 2026" in text
    assert "completion of the program" not in text
    # default title still applies when only the event name is supplied
    assert "CERTIFICATE OF ACHIEVEMENT" in text


def test_pdf_defaults_are_backward_compatible(client, recipients):
    job_id = _create_job(client, recipients)

    text = _pdf_text(_download_first_certificate(client, job_id))

    assert "CERTIFICATE OF ACHIEVEMENT" in text
    assert "in recognition of successful completion of the program" in text


def test_job_row_persists_title_and_event_name(client, recipients):
    job_id = _create_job(
        client,
        recipients,
        certificate_title="AWARD OF EXCELLENCE",
        event_name="Summer Internship 2026",
    )

    session = get_session_factory()()
    try:
        job = session.get(Job, uuid.UUID(job_id))
        assert job is not None
        assert job.certificate_title == "AWARD OF EXCELLENCE"
        assert job.event_name == "Summer Internship 2026"
    finally:
        session.close()


def test_job_row_uses_defaults_when_fields_absent(client, recipients):
    job_id = _create_job(client, recipients)

    session = get_session_factory()()
    try:
        job = session.get(Job, uuid.UUID(job_id))
        assert job.certificate_title == "CERTIFICATE OF ACHIEVEMENT"
        assert job.event_name == "the program"
    finally:
        session.close()
