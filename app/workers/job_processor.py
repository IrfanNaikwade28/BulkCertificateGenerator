"""In-process background processing of generation jobs.

Design notes (documented honestly in the README):
- A fresh SQLAlchemy session is created per job and closed when the job ends.
- Each certificate is handled in its own short transaction; no transaction is
  held open while ReportLab renders a PDF.
- A failure for one recipient is caught, logged, persisted as a per-recipient
  failure, and never stops processing of the remaining recipients.
"""

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.models.certificate import ERROR_GENERATION_FAILED
from app.models.job import utcnow
from app.services import job_service, pdf_service, storage

logger = logging.getLogger(__name__)


def process_job(job_id: uuid.UUID) -> None:
    """Entry point scheduled via FastAPI BackgroundTasks."""
    session = get_session_factory()()
    try:
        _run_job(session, job_id)
    except Exception:
        logger.exception("Job %s crashed; marking it failed", job_id)
        _mark_job_failed(session, job_id)
    finally:
        session.close()


def _run_job(session: Session, job_id: uuid.UUID) -> None:
    job = session.get(Job, job_id)
    if job is None:
        logger.warning("Job %s no longer exists; skipping", job_id)
        return
    if job.status in (JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED):
        return

    job.status = JobStatus.PROCESSING
    job.started_at = utcnow()
    session.commit()

    certificate_ids = session.scalars(
        select(Certificate.id)
        .where(Certificate.job_id == job_id)
        .order_by(Certificate.created_at, Certificate.id)
    ).all()

    for certificate_id in certificate_ids:
        _process_certificate(session, job_id, certificate_id)

    job = session.get(Job, job_id)
    job.status = job_service.final_job_status(
        total_count=job.total_count, failed_count=job.failed_count
    )
    job.finished_at = utcnow()
    session.commit()


def _process_certificate(session: Session, job_id: uuid.UUID, certificate_id: uuid.UUID) -> None:
    """Generate one certificate; never let an error escape to the caller."""
    certificate = session.get(Certificate, certificate_id)
    if certificate is None or certificate.status in (
        CertificateStatus.SUCCEEDED,
        CertificateStatus.FAILED,
    ):
        return

    try:
        job = session.get(Job, job_id)
        certificate.status = CertificateStatus.PROCESSING
        session.commit()

        file_size = pdf_service.render_certificate(
            recipient_name=certificate.recipient_name,
            recipient_email=certificate.email,
            certificate_title=job.certificate_title,
            event_name=job.event_name,
            issue_date=date.today(),
            certificate_id=certificate.id,
            output_path=storage.certificate_file_path(job_id, certificate.id),
        )

        # Succeeded status is only ever set after the PDF file is fully written.
        certificate.status = CertificateStatus.SUCCEEDED
        certificate.error_code = None
        certificate.file_size_bytes = file_size
        certificate.generated_at = utcnow()

        job.processed_count += 1
        job.succeeded_count += 1
        session.commit()
    except Exception:
        logger.exception("Certificate %s generation failed", certificate_id)
        session.rollback()
        _record_certificate_failure(session, job_id, certificate_id)


def _record_certificate_failure(
    session: Session, job_id: uuid.UUID, certificate_id: uuid.UUID
) -> None:
    """Persist a per-recipient failure. Only a sanitized error code is stored."""
    try:
        certificate = session.get(Certificate, certificate_id)
        job = session.get(Job, job_id)
        if certificate.status not in (CertificateStatus.SUCCEEDED, CertificateStatus.FAILED):
            certificate.status = CertificateStatus.FAILED
            certificate.error_code = ERROR_GENERATION_FAILED
        job.processed_count += 1
        job.failed_count += 1
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Could not record failure for certificate %s", certificate_id)


def _mark_job_failed(session: Session, job_id: uuid.UUID) -> None:
    """Catastrophic path: the processing loop itself crashed."""
    try:
        job = session.get(Job, job_id)
        if job is None or job.status in (
            JobStatus.COMPLETED,
            JobStatus.COMPLETED_WITH_ERRORS,
        ):
            return
        job.status = JobStatus.FAILED
        job.finished_at = utcnow()
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Could not mark job %s as failed", job_id)
